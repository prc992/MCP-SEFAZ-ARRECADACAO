from schemas import QuerySpec


def interpretar_pergunta(question: str) -> QuerySpec:
    texto = question.lower()

    if "documento" in texto or "dae" in texto or "quantidade" in texto:
        metric = "qtd_documentos"
    else:
        metric = "valor_arrecadado"

    if "data" in texto or "dia" in texto or "pagamento" in texto or "tempo" in texto:
        group_by = "data_pagamento"
        chart_type = "line"
        top_n = None
    elif "receita" in texto:
        group_by = "receita"
        chart_type = "bar"
        top_n = 10
    elif "código" in texto or "codigo" in texto:
        group_by = "codigo_receita"
        chart_type = "bar"
        top_n = 10
    elif "subgrupo" in texto:
        group_by = "subgrupo"
        chart_type = "bar"
        top_n = 10
    else:
        group_by = "segmento"
        chart_type = "bar"
        top_n = 10

    segmento = None
    subgrupo = None
    receita = None

    return QuerySpec(
        metric=metric,
        group_by=group_by,
        chart_type=chart_type,
        top_n=top_n,
        segmento=segmento,
        subgrupo=subgrupo,
        receita=receita
    )


def gerar_summary(spec: QuerySpec) -> str:
    metric_label = {
        "valor_arrecadado": "valor arrecadado",
        "qtd_documentos": "quantidade de DAE pagos"
    }

    group_by_label = {
        "data_pagamento": "data de pagamento",
        "receita": "receita",
        "codigo_receita": "código da receita",
        "subgrupo": "subgrupo da receita",
        "segmento": "segmento"
    }

    partes = [
        f"Consulta interpretada como {metric_label[spec.metric]} por {group_by_label[spec.group_by]}"
    ]

    if spec.segmento:
        partes.append(f"filtrando o segmento {spec.segmento}")

    if spec.subgrupo:
        partes.append(f"filtrando o subgrupo {spec.subgrupo}")

    if spec.receita:
        partes.append(f"filtrando a receita {spec.receita}")

    if spec.top_n is not None:
        partes.append(f"retornando o top {spec.top_n}")

    partes.append(f"com gráfico do tipo {spec.chart_type}")

    return ", ".join(partes) + "."