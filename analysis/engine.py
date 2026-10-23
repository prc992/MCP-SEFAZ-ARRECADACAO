"""Execução determinística de operações numéricas sobre dados já apresentados.

Sem dependências da LLM, do cliente de dados, de ChatRequest ou de QuerySpec.
"""
from collections import defaultdict
from decimal import Decimal

from .schemas import AnalysisResult, AnalysisSpec
from .operations import amplitude_values, extreme_period, period_changes, rank_values, sum_others


CATEGORIAS = ("decendio", "mes", "data_pagamento", "receita", "codigo_receita", "subgrupo", "segmento", "total")
EXCLUIR_NUMERICAS = {"variacao_percentual", "diferenca", "qtd_registros", "codigo_receita", "periodo"}


def _dec(v):
    if isinstance(v, bool) or not isinstance(v, (int, float, Decimal)):
        return None
    return Decimal(str(v))


def metricas_disponiveis(linhas, spec):
    """Detecta as métricas que efetivamente estão nos registros da resposta."""
    valores = {k for row in linhas for k, v in row.items() if _dec(v) is not None and k not in EXCLUIR_NUMERICAS}
    if spec.analysis_type == "compare_periods" and spec.report_type == "standard":
        a, b = spec.period_1_label or "periodo_1", spec.period_2_label or "periodo_2"
        return {spec.metric} if a in valores and b in valores else set()
    return valores


def _forma_dados(linhas, spec: AnalysisSpec):
    """Forma {categoria: (valor_1, valor_2)}; rejeita pares incompletos e duplicatas.

    Preserve a regra original: valor ausente NÃO equivale a zero.
    """
    linhas = [r for r in linhas if r.get("decendio") != "Total geral"]
    if not linhas or spec.group_by not in CATEGORIAS:
        return None
    matriz = {}
    chave = spec.group_by
    metrica = spec.metric
    if spec.analysis_type == "compare_periods":
        p1, p2 = spec.period_1_label or "periodo_1", spec.period_2_label or "periodo_2"
        if spec.report_type == "icms_fecop":
            temporario = defaultdict(dict)
            for r in linhas:
                cat = r.get(chave)
                per = r.get("periodo")
                val = _dec(r.get(metrica))
                if cat is None or per not in (p1, p2) or val is None or per in temporario[str(cat)]:
                    return None
                temporario[str(cat)][per] = val
            for cat, pares in temporario.items():
                if set(pares) != {p1, p2}:
                    return None
                matriz[cat] = (pares[p1], pares[p2])
        else:
            for r in linhas:
                cat = str(r.get(chave))
                v1, v2 = _dec(r.get(p1)), _dec(r.get(p2))
                if cat in matriz or v1 is None or v2 is None:
                    return None
                matriz[cat] = (v1, v2)
    else:
        for r in linhas:
            cat = str(r.get(chave))
            v = _dec(r.get(metrica))
            if cat in matriz or v is None:
                return None
            matriz[cat] = (v, None)
    return matriz or None


class AnalysisEngine:
    def execute(self, spec: AnalysisSpec, linhas: list[dict]) -> AnalysisResult:
        def result(status, *, category=None, counterpart=None, selected_period=None, **values):
            return AnalysisResult(
                spec=spec, status=status, metric_name=spec.metric,
                category=category, counterpart=counterpart,
                selected_period=selected_period, values=values,
            )

        # Protocolo atual: 101 ou mais linhas podem representar dados truncados.
        if len(linhas) >= 101:
            return result("too_many_rows")
        if not spec.metric:
            return result("metric_required")
        matriz = _forma_dados(linhas, spec)
        if not matriz:
            return result("invalid_data")

        op = spec.operation
        comparacao = spec.analysis_type == "compare_periods"
        cat = spec.category
        if cat is not None and cat not in matriz:
            return result("category_not_found")
        if spec.explicit_category is not None and spec.explicit_category not in matriz:
            return result("category_not_found")

        # Conserva o disparador explícito da operação "outros" na etapa 1.
        if op == "outros" and spec.others_named:
            alvo = spec.explicit_category
            if not alvo or len(matriz) < 2 or comparacao:
                return result("others_target_required")
            valor, outros, diferenca = sum_others({c: x[0] for c, x in matriz.items()}, alvo)
            return result("ok", category=alvo, value=valor, other_sum=outros, difference=diferenca)

        if op in ("maximo", "minimo", "amplitude") and not comparacao:
            valores = {c: x[0] for c, x in matriz.items()}
            maior, menor, amplitude = amplitude_values(valores)
            if op == "amplitude":
                return result("ok", category=maior, counterpart=menor,
                              maximum=matriz[maior][0], minimum=matriz[menor][0],
                              difference=amplitude)
            vencedor = maior if op == "maximo" else menor
            return result("ok", category=vencedor, value=matriz[vencedor][0])

        if comparacao:
            deltas, percentuais = period_changes(matriz)
            if op.startswith("crescimento_"):
                percentual = op.endswith("percentual")
                validos = percentuais if percentual else deltas
                disponiveis = {c: v for c, v in validos.items() if v is not None}
                if not disponiveis:
                    return result("all_percent_references_zero")
                vencedor = rank_values(disponiveis, greatest="_min" not in op)
                a, b = matriz[vencedor]
                return result("ok", category=vencedor, first=a, second=b,
                              difference=b - a, percent=percentuais[vencedor])

            if op in ("variacao", "variacao_percentual", "diferenca"):
                if not cat:
                    return result("category_required")
                a, b = matriz[cat]
                if op == "variacao_percentual" and a == 0:
                    return result("percent_reference_zero", category=cat)
                return result("ok", category=cat, first=a, second=b,
                              difference=b - a, percent=percentuais[cat])

            if op in ("maximo", "minimo"):
                if not cat:
                    return result("comparison_extreme_period_required")
                a, b = matriz[cat]
                p1 = spec.period_1_label or "período 1"
                p2 = spec.period_2_label or "período 2"
                periodo, valor = extreme_period(a, b, p1, p2, greatest=op == "maximo")
                return result("ok", category=cat, selected_period=periodo, value=valor)

            if op == "valor":
                if not cat:
                    return result("category_period_required")
                a, b = matriz[cat]
                return result("ok", category=cat, first=a, second=b)

        if op in ("variacao_percentual", "variacao", "diferenca"):
            return result("comparison_period_required")

        if op == "valor":
            if not cat:
                return result("category_required")
            return result("ok", category=cat, value=matriz[cat][0])

        return result("unsupported")
