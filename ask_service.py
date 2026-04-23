from schemas import QuerySpec


def interpretar_pergunta(question: str) -> QuerySpec:
    texto = question.lower()

    metric = None
    if "documento" in texto or "documentos" in texto:
        metric = "qtd_documentos"
    elif "arrecad" in texto or "valor" in texto:
        metric = "valor_arrecadado"

    group_by = None
    if "município" in texto or "municipio" in texto:
        group_by = "municipio"
    elif "mês" in texto or "mes" in texto:
        group_by = "mes"

    chart_type = "line"
    if "barra" in texto or "bar" in texto:
        chart_type = "bar"

    municipio = None
    if "fortaleza" in texto:
        municipio = "Fortaleza"
    elif "caucaia" in texto:
        municipio = "Caucaia"

    top_n = None
    if "top 1" in texto:
        top_n = 1
    elif "top 2" in texto:
        top_n = 2
    elif "top 3" in texto:
        top_n = 3

    if metric is None or group_by is None:
        raise ValueError("Pergunta insuficiente para determinar métrica e agrupamento.")

    return QuerySpec(
        metric=metric,
        group_by=group_by,
        municipio=municipio,
        chart_type=chart_type,
        top_n=top_n
    )

def gerar_summary(spec: QuerySpec) -> str:
    metric_label = {
        "valor_arrecadado": "valor arrecadado",
        "qtd_documentos": "quantidade de documentos"
    }

    group_by_label = {
        "mes": "mês",
        "municipio": "município"
    }

    partes = [
        f"Consulta interpretada como {metric_label[spec.metric]} por {group_by_label[spec.group_by]}"
    ]

    if spec.municipio:
        partes.append(f"filtrando o município {spec.municipio}")

    if spec.top_n is not None:
        partes.append(f"retornando apenas o top {spec.top_n}")

    partes.append(f"com gráfico do tipo {spec.chart_type}")

    return ", ".join(partes) + "."