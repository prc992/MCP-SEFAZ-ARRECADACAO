"""Disponibilidade mensal de arrecadação efetivamente carregada no Redshift.

A presença de registros não comprova o fechamento contábil do mês.
"""
from datetime import date
from threading import Lock
from time import monotonic

from redshift_client import executar_sql
from schemas import QuerySpec

_CACHE_SECONDS = 600
_cache_lock = Lock()
_cache_data = None
_cache_until = 0.0


def _consultar_meses():
    # Não usa JOIN com decendios_regra: a fonte de disponibilidade é a própria arrecadação.
    sql = """
    SELECT
        TO_CHAR(DATE_TRUNC('month', dat_pagamento), 'YYYY-MM') AS mes,
        MIN(dat_pagamento) AS primeira_data,
        MAX(dat_pagamento) AS ultima_data,
        COUNT(*) AS qtd_registros
    FROM arrecadacao.f_arrecadacao_diaria_consolidada
    WHERE dat_pagamento IS NOT NULL
    GROUP BY 1
    ORDER BY 1
    """
    return executar_sql(sql)


def meses_disponiveis():
    """Resultado em cache por 10 min, permitindo novas cargas sem reiniciar a API."""
    global _cache_data, _cache_until
    with _cache_lock:
        if _cache_data is not None and monotonic() < _cache_until:
            return _cache_data
        linhas = _consultar_meses()
        meses = {str(row['mes']) for row in linhas if row.get('mes') and int(row.get('qtd_registros') or 0) > 0}
        _cache_data = meses
        _cache_until = monotonic() + _CACHE_SECONDS
        return meses


def _meses_entre(inicio: date, fim: date):
    ano, mes = inicio.year, inicio.month
    while (ano, mes) <= (fim.year, fim.month):
        yield f'{ano:04d}-{mes:02d}'
        mes += 1
        if mes == 13:
            ano += 1
            mes = 1


def _intervalos(spec: QuerySpec):
    if spec.analysis_type == 'compare_periods':
        return [
            (spec.period_1_label or 'período 1', spec.period_1_start, spec.period_1_end),
            (spec.period_2_label or 'período 2', spec.period_2_start, spec.period_2_end),
        ]
    if spec.analysis_type == 'time_series' and spec.months_back:
        if spec.months_back < 1:
            raise ValueError('months_back deve ser positivo.')
        hoje = date.today()
        total_meses = hoje.year * 12 + (hoje.month - 1) - (spec.months_back - 1)
        inicio = date(total_meses // 12, total_meses % 12 + 1, 1)
        return [('série temporal', inicio.isoformat(), hoje.isoformat())]
    if spec.start_date or spec.end_date:
        return [('período solicitado', spec.start_date, spec.end_date)]
    return []


def validar_disponibilidade(spec: QuerySpec) -> dict:
    """Valida presença de registros em cada mês solicitado antes de somar ou comparar."""
    intervalos = _intervalos(spec)
    if not intervalos:
        return {'disponivel': True, 'aviso': None, 'meses_ausentes': []}

    pedidos = []
    for nome, inicio, fim in intervalos:
        if not inicio or not fim:
            return {
                'disponivel': False,
                'mensagem': f'Não foi possível determinar as datas de {nome}. Informe mês e ano.',
                'meses_ausentes': [],
            }
        try:
            data_inicio, data_fim = date.fromisoformat(inicio), date.fromisoformat(fim)
        except ValueError:
            return {'disponivel': False, 'mensagem': f'Data inválida em {nome}.', 'meses_ausentes': []}
        if data_inicio > data_fim:
            return {'disponivel': False, 'mensagem': f'O início de {nome} é posterior ao fim.', 'meses_ausentes': []}
        pedidos.append((nome, list(_meses_entre(data_inicio, data_fim))))

    disponiveis = meses_disponiveis()
    mes_atual = date.today().strftime('%Y-%m')
    faltantes = [(nome, mes) for nome, meses in pedidos for mes in meses
                if mes not in disponiveis or mes > mes_atual]
    if faltantes:
        detalhe = '; '.join(f'{nome}: {mes}' for nome, mes in faltantes[:12])
        if len(faltantes) > 12:
            detalhe += f' (e mais {len(faltantes) - 12} meses)'
        limite = (f' Meses encontrados na base: {min(disponiveis)} a {max(disponiveis)}.'
                  if disponiveis else ' Não há meses com registros na tabela.')
        return {
            'disponivel': False,
            'mensagem': ('Não é possível executar a consulta porque não existem registros de arrecadação '
                         f'para todos os meses solicitados ({detalhe}).' + limite
                         + ' Nenhum valor ausente foi tratado como zero.'),
            'meses_ausentes': sorted({mes for _, mes in faltantes}),
        }

    pedidos_mes_atual = any(mes_atual in meses for _, meses in pedidos)
    aviso = ('O período inclui o mês corrente; os dados podem estar parciais e não representam fechamento.'
             if pedidos_mes_atual else None)
    return {'disponivel': True, 'aviso': aviso, 'meses_ausentes': []}
