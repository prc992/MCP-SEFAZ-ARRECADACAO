from schemas import QuerySpec
from redshift_client import executar_sql


TABLE_NAME = "arrecadacao.f_arrecadacao_diaria_consolidada"


METRIC_MAP = {
    "valor_arrecadado": "vlr_arrecadado",
    "qtd_documentos": "qtd_dae_pag"
}

GROUP_BY_MAP = {
    "data_pagamento": "dat_pagamento",
    "mes": "DATE_TRUNC('month', dat_pagamento)",
    "receita": "dsc_receita",
    "codigo_receita": "cod_receita",
    "subgrupo": "receita_class_subgrupo",
    "segmento": "dsc_segmento"
}

def executar_serie_temporal(spec: QuerySpec):
    metric_col = METRIC_MAP[spec.metric]

    where_clauses = []

    if spec.months_back:
        where_clauses.append(
            f"dat_pagamento >= DATEADD(month, -{spec.months_back - 1}, DATE_TRUNC('month', CURRENT_DATE))"
        )

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

    sql = f"""
    SELECT
        TO_CHAR(DATE_TRUNC('month', dat_pagamento), 'YYYY-MM') AS mes,
        SUM({metric_col}) AS valor
    FROM {TABLE_NAME}
    {where_sql}
    GROUP BY 1
    ORDER BY 1
    """

    dados = executar_sql(sql)

    resultado = []
    for row in dados:
        resultado.append({
            "mes": row["mes"],
            spec.metric: float(row["valor"]) if row["valor"] is not None else 0
        })

    return {
    "dados": resultado,
    "sql": sql
}

def executar_query(spec: QuerySpec):
    if spec.analysis_type == "compare_periods":
        return executar_comparacao_periodos(spec)

    if spec.analysis_type == "time_series":
        return executar_serie_temporal(spec)

    return executar_agregacao_simples(spec)


def executar_agregacao_simples(spec: QuerySpec):
    metric_col = METRIC_MAP[spec.metric]
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
        SUM({metric_col}) AS valor
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

    return {
    "dados": resultado,
    "sql": sql
}

def executar_comparacao_periodos(spec: QuerySpec):
    metric_col = METRIC_MAP[spec.metric]
    group_sql = GROUP_BY_MAP[spec.group_by]

    label_1 = spec.period_1_label or "periodo_1"
    label_2 = spec.period_2_label or "periodo_2"

    where_clauses = [
        f"dat_pagamento >= '{spec.period_1_start}'",
        f"dat_pagamento <= '{spec.period_2_end}'"
    ]

    if spec.segmento:
        where_clauses.append(f"LOWER(dsc_segmento) LIKE LOWER('%{spec.segmento}%')")

    if spec.subgrupo:
        where_clauses.append(f"LOWER(receita_class_subgrupo) LIKE LOWER('%{spec.subgrupo}%')")

    if spec.receita:
        where_clauses.append(f"LOWER(dsc_receita) LIKE LOWER('%{spec.receita}%')")

    where_sql = "WHERE " + " AND ".join(where_clauses)

    sql = f"""
    SELECT
        {group_sql} AS categoria,

        SUM(
            CASE
                WHEN dat_pagamento >= '{spec.period_1_start}'
                 AND dat_pagamento <= '{spec.period_1_end}'
                THEN {metric_col}
                ELSE 0
            END
        ) AS valor_periodo_1,

        SUM(
            CASE
                WHEN dat_pagamento >= '{spec.period_2_start}'
                 AND dat_pagamento <= '{spec.period_2_end}'
                THEN {metric_col}
                ELSE 0
            END
        ) AS valor_periodo_2

    FROM {TABLE_NAME}
    {where_sql}
    GROUP BY 1
    ORDER BY valor_periodo_2 DESC
    LIMIT {spec.top_n or 20}
    """

    dados = executar_sql(sql)

    resultado = []
    for row in dados:
        valor_1 = float(row["valor_periodo_1"] or 0)
        valor_2 = float(row["valor_periodo_2"] or 0)
        diferenca = valor_2 - valor_1

        if valor_1 == 0:
            variacao_percentual = None
        else:
            variacao_percentual = (diferenca / valor_1) * 100

        if diferenca > 0:
            tendencia = "subiu"
        elif diferenca < 0:
            tendencia = "caiu"
        else:
            tendencia = "estável"

        resultado.append({
            spec.group_by: row["categoria"],
            label_1: valor_1,
            label_2: valor_2,
            "diferenca": diferenca,
            "variacao_percentual": variacao_percentual,
            "tendencia": tendencia
        })

    return {
    "dados": resultado,
    "sql": sql
}