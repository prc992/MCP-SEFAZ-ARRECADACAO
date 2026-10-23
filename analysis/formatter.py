"""Apresentação determinística; recebe valores calculados, nunca os recalcula."""
from decimal import Decimal
import re

from .schemas import AnalysisResult
from .domain import DomainCatalog, resolve_catalog


def _br(v, percentual=False, inteiro=False, *, currency_symbol="R$", numeric=False):
    """Formatação legada (pt-BR); currency/unit vêm do catálogo."""
    if v is None:
        return "indefinida (referência zero)"
    n = Decimal(str(v))
    if inteiro:
        fmt = f"{n:,.0f}"
    else:
        fmt = f"{n:,.2f}"
    fmt = fmt.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{fmt}%" if percentual else (fmt if inteiro or numeric else f"{currency_symbol} {fmt}")


def _rotulo(valor, catalog: DomainCatalog | None = None):
    return resolve_catalog(catalog).display_category(valor)


def format_analysis_result(result: AnalysisResult, catalog: DomainCatalog | None = None) -> str:
    domain = resolve_catalog(catalog)
    status = result.status
    spec = result.spec
    op = spec.operation
    nome = domain.label(spec.metric)
    if status == "too_many_rows":
        return ("Há muitas linhas para um cálculo confiável no chat. "
                "Peça um recorte ou agrupamento específico antes de calcular.")
    if status == "metric_required":
        return domain.metric_question
    if status == "invalid_data":
        return ("Não há dados numéricos completos para realizar esse cálculo com segurança. "
                "Solicite uma consulta mais específica ou verifique se ambos os períodos possuem registros.")
    if status == "category_not_found":
        return "A categoria solicitada não está presente nos dados exibidos. Solicite uma nova consulta."
    if status == "others_target_required":
        return "Indique a categoria que deseja comparar com as demais, em uma consulta de período único."
    if status == "all_percent_references_zero":
        return "Não é possível calcular variações percentuais: os valores de referência são zero."
    if status == "percent_reference_zero":
        return (f"Não é possível calcular a variação percentual de {_rotulo(result.category, domain)}: "
                f"o valor de referência em {spec.period_1_label or 'período 1'} é zero.")
    if status == "comparison_period_required":
        return ("A consulta atual contém somente um período. "
                "Para calcular a variação, solicite uma comparação entre dois períodos.")
    if status == "comparison_extreme_period_required":
        return "Em qual período deseja identificar o maior ou menor valor?"
    if status == "category_period_required":
        return "De qual categoria e período você deseja o valor?"
    if status == "category_required":
        if spec.analysis_type == "compare_periods" and op in ("variacao", "variacao_percentual", "diferenca"):
            return f"De qual categoria você deseja a variação de {nome}?"
        return f"De qual categoria você deseja o valor de {nome}?"
    if status != "ok":
        return "Para esse cálculo, indique o indicador, a categoria e os períodos desejados."

    val = result.values
    unit = domain.unit(spec.metric)
    fmt = lambda x: _br(x, percentual=unit == "percent", inteiro=unit == "count",
                        numeric=unit == "number", currency_symbol=domain.currency_symbol)
    p1 = spec.period_1_label or "período 1"
    p2 = spec.period_2_label or "período 2"
    cat = _rotulo(result.category, domain)

    if op == "outros":
        return (f"{'Sim' if val['value'] > val['other_sum'] else 'Não'}. {cat}: {fmt(val['value'])}; "
                f"demais categorias juntas: {fmt(val['other_sum'])}; "
                f"diferença: {fmt(val['difference'])}.")
    if spec.analysis_type != "compare_periods" and op in ("maximo", "minimo", "amplitude"):
        if op == "amplitude":
            return (f"Diferença entre maior e menor {nome}: {fmt(val['difference'])}, "
                    f"de {cat} ({fmt(val['maximum'])}) "
                    f"para {_rotulo(result.counterpart, domain)} ({fmt(val['minimum'])}).")
        return f"{cat} apresentou o {'maior' if op == 'maximo' else 'menor'} valor de {nome}: {fmt(val['value'])}."

    if spec.analysis_type == "compare_periods":
        if op.startswith("crescimento_"):
            percentual = op.endswith("percentual")
            menor = "_min" in op
            return (f"{cat} apresentou a {'menor' if menor else 'maior'} "
                    f"variação {'percentual' if percentual else 'absoluta'} de {nome} entre {p1} e {p2}: "
                    f"{fmt(val['first'])} → {fmt(val['second'])}; diferença {fmt(val['difference'])}; "
                    f"variação {_br(val['percent'], percentual=True)}.")
        if op in ("variacao", "variacao_percentual", "diferenca"):
            return (f"{cat}, {nome}, {p1} → {p2}: {fmt(val['first'])} → {fmt(val['second'])}; "
                    f"diferença {fmt(val['difference'])}; variação {_br(val['percent'], percentual=True)}.")
        if op in ("maximo", "minimo"):
            return f"{cat}: {'maior' if op == 'maximo' else 'menor'} {nome} em {result.selected_period} ({fmt(val['value'])})."
        if op == "valor":
            return f"{cat}: {p1} = {fmt(val['first'])}; {p2} = {fmt(val['second'])}."

    if op == "valor":
        return f"{cat}: {nome} = {fmt(val['value'])}."
    return "Para esse cálculo, indique o indicador, a categoria e os períodos desejados."


def __getattr__(name):
    if name == "METRIC_NAMES":
        domain = resolve_catalog()
        return {key: metric.label for key, metric in domain.metrics.items()}
    raise AttributeError(name)
