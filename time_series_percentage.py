"""Variação percentual mensal determinística para relatórios de consulta inicial.

Não altera o contrato matemático do motor conversacional: reutiliza as mesmas
primitivas Decimal de analysis.operations para pares consecutivos.
"""
from datetime import date, timedelta
from decimal import Decimal
from analysis.operations import consecutive_changes, temporal_key


class PercentageSeriesError(ValueError):
    """Mensagem de domínio segura para exibir em /ask ou /chat."""


def calcular_serie_percentual(rows: list[dict], spec) -> tuple[list[dict], str | None]:
    if not spec.start_date or not spec.end_date:
        raise PercentageSeriesError("Informe o período da série para calcular a variação percentual.")
    inicio, fim = date.fromisoformat(spec.start_date), date.fromisoformat(spec.end_date)
    idx_inicio = inicio.year * 12 + inicio.month - 1
    idx_fim = fim.year * 12 + fim.month - 1
    if idx_inicio > idx_fim:
        raise PercentageSeriesError("Intervalo temporal inválido para a série percentual.")
    if inicio.day != 1:
        raise PercentageSeriesError("Para comparar meses completos, o início da série percentual deve ser o primeiro dia do mês.")
    por_mes = {}
    for row in rows:
        rotulo = str(row.get("mes", ""))
        indice = temporal_key(rotulo, "mes")
        if indice is None or indice in por_mes:
            raise PercentageSeriesError("A série contém meses inválidos ou duplicados.")
        valor = row.get(spec.metric)
        if valor is None:
            raise PercentageSeriesError("A série contém valores ausentes; não foram substituídos por zero.")
        try:
            por_mes[indice] = (rotulo, Decimal(str(valor)))
        except Exception as exc:
            raise PercentageSeriesError("A série contém valores numéricos inválidos.") from exc
    # Todo mês exibido deve existir. Um mês usado só como referência é opcional.
    faltantes = [i for i in range(idx_inicio, idx_fim + 1) if i not in por_mes]
    if faltantes:
        raise PercentageSeriesError("A consulta não retornou valores para todos os meses solicitados com os filtros aplicados. Nenhum mês ausente foi tratado como zero.")
    base_index = idx_inicio - 1
    base = por_mes.get(base_index)
    calculaveis = [(rotulo, valor) for i, (rotulo, valor) in sorted(por_mes.items())
                   if base_index <= i <= idx_fim]
    # A primitiva de análise exige série com pelo menos dois pontos.
    percentuais = {}
    if len(calculaveis) >= 2:
        try:
            pares = consecutive_changes(dict(calculaveis), "mes")
        except ValueError as exc:
            raise PercentageSeriesError("Existem lacunas na série mensal. Não foram calculadas variações entre meses não consecutivos.") from exc
        percentuais = {atual: percentual for _, atual, _, _, _, percentual in pares}
    atual_index = date.today().year * 12 + date.today().month - 1
    ultimo_dia = (date(fim.year + (fim.month == 12), fim.month % 12 + 1, 1)
                  - timedelta(days=1)).day
    parcial = idx_fim == atual_index or fim.day < ultimo_dia
    result = []
    for i in range(idx_inicio, idx_fim + 1):
        rotulo, valor = por_mes[i]
        pct = None if parcial and i == idx_fim else percentuais.get(rotulo)
        result.append({"mes": rotulo, spec.metric: float(valor),
                       "variacao_percentual": float(pct) if pct is not None else None})
    avisos = []
    if not base:
        avisos.append("O mês anterior ao primeiro período exibido não possui dados para este filtro; a primeira variação percentual foi omitida.")
    elif base[1] == 0:
        avisos.append("A primeira referência tem valor zero; a variação percentual correspondente é indefinida.")
    if any(por_mes[i-1][1] == 0 for i in range(idx_inicio + 1, idx_fim + 1)):
        avisos.append("Uma ou mais variações não foram calculadas porque o mês anterior teve valor zero.")
    if parcial:
        avisos.append("O último mês do intervalo pode estar parcial: seu valor aparece na tabela, mas sua variação percentual não foi calculada.")
    return result, " ".join(avisos) or None
