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
    if spec.report_type == "icms_fecop":
        return executar_relatorio_icms_fecop(spec)

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

# Relatório fiscal ICMS/FECOP: A = ICMS; B = FECOP; C = A-B; D = 60% de C.
def executar_relatorio_icms_fecop(spec: QuerySpec):
    if spec.analysis_type not in ("aggregate", "compare_periods"):
        raise ValueError("O relatório ICMS/FECOP aceita aggregate ou compare_periods.")
    if spec.group_by not in ("decendio", "total"):
        raise ValueError("O relatório ICMS/FECOP aceita group_by decendio ou total.")
    if spec.subgrupo and spec.subgrupo.strip().upper() != "ICMS":
        raise ValueError("O relatório ICMS/FECOP é exclusivo do subgrupo ICMS.")
    if spec.receita:
        raise ValueError("O relatório ICMS/FECOP não aceita filtro por receita individual.")

    filtros = ["a.receita_class_subgrupo = 'ICMS'"]
    if spec.segmento:
        # Escapa aspas simples, como proteção básica ao interpolar valores.
        segmento = spec.segmento.replace("'", "''")
        filtros.append(f"LOWER(a.dsc_segmento) LIKE LOWER('%{segmento}%')")
    if spec.decendio is not None:
        filtros.append(f"dr.decendio = '{spec.decendio} Decêndio'")

    def intervalo(inicio, fim):
        from datetime import date
        if not inicio or not fim:
            raise ValueError("Informe as datas inicial e final do relatório ICMS/FECOP.")
        data_inicio = date.fromisoformat(inicio)
        data_fim = date.fromisoformat(fim)
        if data_inicio > data_fim:
            raise ValueError("A data inicial não pode ser posterior à final.")
        return (f"a.dat_pagamento >= DATE '{data_inicio.isoformat()}' "
                f"AND a.dat_pagamento < DATEADD(day, 1, DATE '{data_fim.isoformat()}')")

    agrupamento = "dr.decendio" if spec.group_by == "decendio" else "'Total'"
    group_by_sql = "GROUP BY 1" if spec.group_by == "decendio" else ""
    order_by_sql = "ORDER BY 1" if spec.group_by == "decendio" else ""

    if spec.analysis_type == "aggregate":
        filtros.append(intervalo(spec.start_date, spec.end_date))
        where_sql = " AND ".join(filtros)
        sql = f"""
        WITH base AS (
            SELECT {agrupamento} AS categoria,
                   COUNT(*) AS qtd_registros,
                   SUM(a.vlr_arrecadado) AS icms_a,
                   SUM(CASE WHEN a.tip_fecop = 1 THEN a.vlr_arrecadado ELSE 0 END) AS fecop_b
            FROM {TABLE_NAME}
            WHERE {where_sql}
            {group_by_sql}
        )
        SELECT categoria, qtd_registros, icms_a, fecop_b,
               icms_a - fecop_b AS icms_sem_fecop_c,
               (icms_a - fecop_b) * 0.60 AS icms_liquido_tesouro_d
        FROM base
        {order_by_sql}
        """
        linhas = executar_sql(sql)
        dados = []
        for row in linhas:
            if not row["qtd_registros"]:
                continue
            dados.append({
                spec.group_by: row["categoria"],
                **{chave: float(row[chave]) if row[chave] is not None else None
                   for chave in ("icms_a", "fecop_b", "icms_sem_fecop_c", "icms_liquido_tesouro_d")}
            })
        return {"dados": dados, "sql": sql}

    periodo_1 = intervalo(spec.period_1_start, spec.period_1_end)
    periodo_2 = intervalo(spec.period_2_start, spec.period_2_end)
    filtros.append(f"(({periodo_1}) OR ({periodo_2}))")
    where_sql = " AND ".join(filtros)
    sql = f"""
    WITH base AS (
        SELECT {agrupamento} AS categoria,
               CASE WHEN {periodo_1} THEN 1 ELSE 2 END AS periodo,
               COUNT(*) AS qtd_registros,
               SUM(a.vlr_arrecadado) AS icms_a,
               SUM(CASE WHEN a.tip_fecop = 1 THEN a.vlr_arrecadado ELSE 0 END) AS fecop_b
        FROM {TABLE_NAME}
        WHERE {where_sql}
        GROUP BY 1, 2
    )
    SELECT categoria, periodo, qtd_registros, icms_a, fecop_b,
           icms_a - fecop_b AS icms_sem_fecop_c,
           (icms_a - fecop_b) * 0.60 AS icms_liquido_tesouro_d
    FROM base
    ORDER BY categoria, periodo
    """
    # Cada linha identifica explicitamente o período, facilitando quatro gráficos agrupados.
    dados = []
    for row in executar_sql(sql):
        dados.append({
            spec.group_by: row["categoria"],
            "periodo": ((spec.period_1_label or "periodo_1") if row["periodo"] == 1
                        else (spec.period_2_label or "periodo_2")),
            **{chave: float(row[chave]) if row[chave] is not None else None
               for chave in ("icms_a", "fecop_b", "icms_sem_fecop_c", "icms_liquido_tesouro_d")}
        })
    return {"dados": dados, "sql": sql}
