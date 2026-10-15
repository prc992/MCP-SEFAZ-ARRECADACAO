from schemas import QuerySpec
from redshift_client import executar_sql


TABLE_NAME = """arrecadacao.f_arrecadacao_diaria_consolidada a
INNER JOIN arrecadacao.decendios_regra dr
    ON dr.dat_pagamento = a.dat_pagamento"""


METRIC_MAP = {
    "valor_arrecadado": "a.vlr_arrecadado",
    "qtd_documentos": "a.qtd_dae_pag"
}

GROUP_BY_MAP = {
    "data_pagamento": "a.dat_pagamento",
    "mes": "DATE_TRUNC('month', a.dat_pagamento)",
    "receita": "a.dsc_receita",
    "codigo_receita": "a.cod_receita",
    "subgrupo": "a.receita_class_subgrupo",
    "segmento": "a.dsc_segmento",
    "decendio": "dr.decendio"
}

def executar_serie_temporal(spec: QuerySpec):
    metric_col = METRIC_MAP[spec.metric]

    where_clauses = []

    if spec.months_back:
        where_clauses.append(
            f"a.dat_pagamento >= DATEADD(month, -{spec.months_back - 1}, DATE_TRUNC('month', CURRENT_DATE))"
        )

    if spec.start_date:
        where_clauses.append(f"a.dat_pagamento >= '{spec.start_date}'")

    if spec.end_date:
        where_clauses.append(f"a.dat_pagamento <= '{spec.end_date}'")

    if spec.segmento:
        where_clauses.append(f"LOWER(a.dsc_segmento) LIKE LOWER('%{spec.segmento}%')")

    if spec.subgrupo:
        where_clauses.append(f"LOWER(a.receita_class_subgrupo) LIKE LOWER('%{spec.subgrupo}%')")

    if spec.receita:
        where_clauses.append(f"LOWER(a.dsc_receita) LIKE LOWER('%{spec.receita}%')")

    if spec.decendio is not None:
        where_clauses.append(
            f"dr.decendio = '{spec.decendio} Decêndio'"
        )    

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    sql = f"""
    SELECT
        TO_CHAR(DATE_TRUNC('month', a.dat_pagamento), 'YYYY-MM') AS mes,
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

    group_sql = (
        None if spec.group_by == "total"
        else GROUP_BY_MAP[spec.group_by]
    )

    where_clauses = []

    if spec.start_date:
        where_clauses.append(f"a.dat_pagamento >= '{spec.start_date}'")

    if spec.end_date:
        where_clauses.append(f"a.dat_pagamento <= '{spec.end_date}'")

    if spec.segmento:
        where_clauses.append(f"LOWER(a.dsc_segmento) LIKE LOWER('%{spec.segmento}%')")

    if spec.subgrupo:
        where_clauses.append(f"LOWER(a.receita_class_subgrupo) LIKE LOWER('%{spec.subgrupo}%')")

    if spec.receita:
        where_clauses.append(f"LOWER(a.dsc_receita) LIKE LOWER('%{spec.receita}%')")

    if spec.decendio is not None:
        where_clauses.append(
            f"dr.decendio = '{spec.decendio} Decêndio'"
        )    

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    order_direction = "DESC" if spec.order_desc else "ASC"

    limit_sql = ""
    if spec.top_n:
        limit_sql = f"LIMIT {spec.top_n}"

    order_sql = "categoria ASC" if spec.group_by == "decendio" else f"valor {order_direction}"

    if spec.group_by == "total":
        sql = f"""
        SELECT
            SUM({metric_col}) AS valor
        FROM {TABLE_NAME}
        {where_sql}
        """
    else:
        sql = f"""
        SELECT
            {group_sql} AS categoria,
            SUM({metric_col}) AS valor
        FROM {TABLE_NAME}
        {where_sql}
        GROUP BY 1
        ORDER BY {order_sql}
        {limit_sql}
        """

    dados = executar_sql(sql)


    resultado = []

    for row in dados:
        valor = float(row["valor"]) if row["valor"] is not None else 0

        if spec.group_by == "total":
            resultado.append({
                "total": "Total",
                spec.metric: valor
            })
        else:
            resultado.append({
                spec.group_by: row["categoria"],
                spec.metric: valor
            })


    if spec.group_by == "data_pagamento":
        resultado.sort(key=lambda row: row[spec.group_by])

    return {
    "dados": resultado,
    "sql": sql
}

def executar_comparacao_periodos(spec: QuerySpec):
    metric_col = METRIC_MAP[spec.metric]

    group_sql = (
        None if spec.group_by == "total"
        else GROUP_BY_MAP[spec.group_by]
    )

    label_1 = spec.period_1_label or "periodo_1"
    label_2 = spec.period_2_label or "periodo_2"

    where_clauses = [
        f"""(
            (a.dat_pagamento >= '{spec.period_1_start}'
            AND a.dat_pagamento <= '{spec.period_1_end}')
            OR
            (a.dat_pagamento >= '{spec.period_2_start}'
            AND a.dat_pagamento <= '{spec.period_2_end}')
        )"""
    ]

    if spec.segmento:
        where_clauses.append(f"LOWER(a.dsc_segmento) LIKE LOWER('%{spec.segmento}%')")

    if spec.subgrupo:
        where_clauses.append(f"LOWER(a.receita_class_subgrupo) LIKE LOWER('%{spec.subgrupo}%')")

    if spec.receita:
        where_clauses.append(f"LOWER(a.dsc_receita) LIKE LOWER('%{spec.receita}%')")

    if spec.decendio is not None:
        where_clauses.append(
            f"dr.decendio = '{spec.decendio} Decêndio'"
        )    

    where_sql = "WHERE " + " AND ".join(where_clauses)


    select_categoria = (
        "'Total' AS categoria,"
        if spec.group_by == "total"
        else f"{group_sql} AS categoria,"
    )

    compare_order_sql = "categoria ASC" if spec.group_by == "decendio" else "valor_periodo_2 DESC"

    group_order_sql = (
        ""
        if spec.group_by == "total"
        else f"""
        GROUP BY 1
        ORDER BY {compare_order_sql}
        LIMIT {spec.top_n or 20}
        """
    )

    sql = f"""
    SELECT
        {select_categoria}

        SUM(
            CASE
                WHEN a.dat_pagamento >= '{spec.period_1_start}'
                 AND a.dat_pagamento <= '{spec.period_1_end}'
                THEN {metric_col}
                ELSE 0
            END
        ) AS valor_periodo_1,

        SUM(
            CASE
                WHEN a.dat_pagamento >= '{spec.period_2_start}'
                 AND a.dat_pagamento <= '{spec.period_2_end}'
                THEN {metric_col}
                ELSE 0
            END
        ) AS valor_periodo_2

    FROM {TABLE_NAME}
    {where_sql}
    {group_order_sql}
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