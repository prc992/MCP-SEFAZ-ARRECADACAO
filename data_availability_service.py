"""Disponibilidade mensal de arrecadação efetivamente carregada no Redshift.

A presença de registros não comprova o fechamento contábil do mês.
"""
from datetime import date, datetime
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


def cobertura_mensal() -> dict[str, date]:
    """Última data observada por mês, com cache compartilhado por dez minutos.

    Não representa confirmação de fechamento contábil.
    """
    global _cache_data, _cache_until
    with _cache_lock:
        if _cache_data is not None and monotonic() < _cache_until:
            return _cache_data
        cobertura = {}
        for row in _consultar_meses():
            mes = row.get('mes')
            if not mes or int(row.get('qtd_registros') or 0) <= 0:
                continue
            ultima = row.get('ultima_data')
            if isinstance(ultima, datetime):
                ultima = ultima.date()
            elif not isinstance(ultima, date):
                ultima = date.fromisoformat(str(ultima)[:10])
            cobertura[str(mes)] = ultima
        _cache_data = cobertura
        _cache_until = monotonic() + _CACHE_SECONDS
        return cobertura


def meses_disponiveis():
    """Interface legada: conjunto dos meses com registros, sem presumir fechamento."""
    return set(cobertura_mensal())


def resolver_periodo_serie(spec: QuerySpec) -> tuple[QuerySpec, str | None]:
    """Resolve somente séries relativas sem datas explícitas.

    Produz N meses CONSECUTIVOS até o mês com dados mais recente; jamais pula
    uma lacuna intermediária ou reinterpreta datas explicitamente informadas.
    O QuerySpec original não é modificado.
    """
    if (spec.analysis_type != 'time_series' or spec.months_back is None
            or spec.start_date is not None or spec.end_date is not None):
        return spec, None
    if spec.months_back < 1:
        raise ValueError('months_back deve ser positivo.')

    cobertura = cobertura_mensal()
    hoje = date.today()
    mes_corrente = hoje.strftime('%Y-%m')
    meses_validos = [mes for mes in cobertura if mes <= mes_corrente]
    if not meses_validos:
        # Mantém a validação normal para produzir erro de disponibilidade.
        return spec, None

    mes_final = max(meses_validos)
    fim = min(cobertura[mes_final], hoje)
    indice_mes_final = fim.year * 12 + (fim.month - 1)
    indice_inicio = indice_mes_final - (spec.months_back - 1)
    inicio = date(indice_inicio // 12, indice_inicio % 12 + 1, 1)
    resolvido = spec.model_copy(update={
        'start_date': inicio.isoformat(),
        'end_date': fim.isoformat(),
    })
    periodo = f'{inicio:%m/%Y} a {fim:%m/%Y}'
    if mes_final < mes_corrente:
        aviso = (f'O mês corrente ({mes_corrente}) ainda não possui registros. '
                 f'Os {spec.months_back} meses consecutivos mais recentes foram '
                 f'ajustados para {periodo}, com dados até {fim:%d/%m/%Y}.')
    else:
        aviso = (f'A série de {spec.months_back} meses inclui o mês corrente, '
                 f'com registros disponíveis até {fim:%d/%m/%Y}. '
                 'O mês corrente é parcial.')
    return resolvido, aviso + ' A existência de registros não comprova fechamento contábil.'


def preparar_consulta_temporal(spec: QuerySpec) -> tuple[QuerySpec, dict]:
    """Resolve o intervalo e valida o MESMO QuerySpec usado na execução SQL."""
    resolvido, aviso_ajuste = resolver_periodo_serie(spec)
    disponibilidade = validar_disponibilidade(resolvido)
    if aviso_ajuste and disponibilidade['disponivel']:
        # A mensagem ajustada já descreve a parcialidade do mês corrente.
        disponibilidade['aviso'] = aviso_ajuste
    return resolvido, disponibilidade


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
    # Datas resolvidas ou explícitas têm prioridade sobre months_back.
    # Isso mantém a validação idêntica ao intervalo efetivamente consultado.
    if spec.analysis_type == 'time_series' and (spec.start_date or spec.end_date):
        return [('série temporal', spec.start_date, spec.end_date)]
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
