"""Geração de resumos textuais a partir do QuerySpec.

A interpretação da pergunta é realizada exclusivamente em llm_service.py.
"""

from schemas import QuerySpec


def gerar_summary(spec: QuerySpec) -> str:
    metric_label = {
        "valor_arrecadado": "valor arrecadado",
        "qtd_documentos": "quantidade de DAE pagos"
    }

    group_by_label = {
        "total": "total",
        "data_pagamento": "data de pagamento",
        "mes": "mês",
        "receita": "receita",
        "codigo_receita": "código da receita",
        "subgrupo": "subgrupo da receita",
        "segmento": "segmento",
        "decendio": "decêndio",
    }

    if spec.analysis_type == "time_series":
        partes = [
            f"Consulta interpretada como série temporal mensal de {metric_label[spec.metric]}"
        ]

        if spec.months_back:
            partes.append(f"nos últimos {spec.months_back} meses")

        if spec.segmento:
            partes.append(f"filtrando o segmento {spec.segmento}")

        if spec.subgrupo:
            partes.append(f"filtrando o grupo de receita {spec.subgrupo}")

        if spec.receita:
            partes.append(f"filtrando a receita {spec.receita}")

        partes.append(f"com gráfico do tipo {spec.chart_type}")

        return ", ".join(partes) + "."    


    if spec.analysis_type == "compare_periods":

        if spec.group_by == "total":
            return (
                f"Consulta interpretada como comparação do total de "
                f"{metric_label[spec.metric]} entre "
                f"{spec.period_1_label} e {spec.period_2_label}, "
                f"com cálculo de diferença, variação percentual e tendência."
            )

        return (
            f"Consulta interpretada como comparação de {metric_label[spec.metric]} "
            f"por {group_by_label[spec.group_by]}, comparando "
            f"{spec.period_1_label} contra {spec.period_2_label}, "
            f"com cálculo de diferença, variação percentual e tendência."
        )


    if spec.group_by == "total":
        partes = [
            f"Consulta interpretada como total de {metric_label[spec.metric]}"
        ]
    else:
        partes = [
            f"Consulta interpretada como {metric_label[spec.metric]} por {group_by_label[spec.group_by]}"
        ]

    if spec.start_date and spec.end_date:
        partes.append(f"no período de {spec.start_date} a {spec.end_date}")

    if spec.top_n is not None:
        partes.append(f"retornando o top {spec.top_n}")

    partes.append(f"com gráfico do tipo {spec.chart_type}")

    return ", ".join(partes) + "."
