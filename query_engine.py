from schemas import QuerySpec
from redshift_client import executar_sql


TABLE_NAME = "arrecadacao.f_arrecadacao_diaria_consolidada"


METRIC_MAP = {
    "valor_arrecadado": "SUM(vlr_arrecadado)",
    "qtd_documentos": "SUM(qtd_dae_pag)"
}


GROUP_BY_MAP = {
    "data_pagamento": "dat_pagamento",
    "receita": "dsc_receita",
    "codigo_receita": "cod_receita",
    "subgrupo": "receita_class_subgrupo",
    "segmento": "dsc_segmento"
}


def executar_query(spec: QuerySpec):
    metric_sql = METRIC_MAP[spec.metric]
    group_sql = GROUP_BY_MAP[spec.group_by]

    where_clauses = []

    if spec.start_date:
        where_clauses.append(f"dat_pagamento >= '{spec.start_date}'")

    if spec.end_date:
        where_clauses.append(f"dat_pagamento <= '{spec.end_date}'")

    if spec.segmento:
        where_clauses.append(f"LOWER(dsc_segmento) LIKE LOWER('%{spec.segmento}%')")

    if spec.subgrupo:
        where_clauses.append(f"LOWER(receita_class_subgrupo) LIKE LOWER('%{spec.subgrupo}%')")

    if spec.receita:
        where_clauses.append(f"LOWER(dsc_receita) LIKE LOWER('%{spec.receita}%')")

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    order_direction = "DESC" if spec.order_desc else "ASC"

    limit_sql = ""
    if spec.top_n:
        limit_sql = f"LIMIT {spec.top_n}"

    sql = f"""
    SELECT
        {group_sql} AS categoria,
        {metric_sql} AS valor
    FROM {TABLE_NAME}
    {where_sql}
    GROUP BY 1
    ORDER BY valor {order_direction}
    {limit_sql}
    """

    dados = executar_sql(sql)

    resultado = []
    for row in dados:
        resultado.append({
            spec.group_by: row["categoria"],
            spec.metric: float(row["valor"]) if row["valor"] is not None else 0
        })

    if spec.group_by == "data_pagamento":
        resultado.sort(key=lambda row: row[spec.group_by])

    return resultado