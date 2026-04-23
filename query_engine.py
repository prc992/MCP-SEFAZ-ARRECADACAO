from schemas import QuerySpec

dados_mock = [
    {"mes": "2025-01", "municipio": "Fortaleza", "valor_arrecadado": 100, "qtd_documentos": 10},
    {"mes": "2025-02", "municipio": "Fortaleza", "valor_arrecadado": 150, "qtd_documentos": 12},
    {"mes": "2025-03", "municipio": "Fortaleza", "valor_arrecadado": 120, "qtd_documentos": 9},
    {"mes": "2025-01", "municipio": "Caucaia", "valor_arrecadado": 80, "qtd_documentos": 8},
    {"mes": "2025-02", "municipio": "Caucaia", "valor_arrecadado": 90, "qtd_documentos": 7},
    {"mes": "2025-03", "municipio": "Caucaia", "valor_arrecadado": 110, "qtd_documentos": 11},
]


def executar_query(spec: QuerySpec):
    agregados = {}

    for row in dados_mock:
        if spec.municipio and row["municipio"] != spec.municipio:
            continue

        if spec.start_mes and row["mes"] < spec.start_mes:
            continue
        if spec.end_mes and row["mes"] > spec.end_mes:
            continue

        chave = row[spec.group_by]
        valor = row.get(spec.metric, 0)

        if chave not in agregados:
            agregados[chave] = 0

        agregados[chave] += valor

    resultado = []
    for chave, soma in agregados.items():
        resultado.append({
            spec.group_by: chave,
            spec.metric: soma
        })

    resultado.sort(key=lambda row: row[spec.metric], reverse=spec.order_desc)

    if spec.top_n is not None:
        resultado = resultado[:spec.top_n]

    if spec.group_by == "mes":
        resultado.sort(key=lambda row: row["mes"])

    return resultado