import logging

from app.infrastructure.redshift_client import execute_sql
from app.shared.contracts import QuerySpec
from app.shared.logging_utils import preview_text
logger = logging.getLogger(__name__)


TABLE_NAME = "arrecadacao.f_arrecadacao_diaria_consolidada"

METRIC_MAP = {
    "valor_arrecadado": "vlr_arrecadado",
    "qtd_documentos": "qtd_dae_pag",
}

GROUP_BY_MAP = {
    "data_pagamento": "dat_pagamento",
    "mes": "DATE_TRUNC('month', dat_pagamento)",
    "receita": "dsc_receita",
    "codigo_receita": "cod_receita",
    "subgrupo": "receita_class_subgrupo",
    "segmento": "dsc_segmento",
}


def _append_like_filter(where_clauses: list[str], params: list[object], column: str, value: str | None) -> None:
    if not value:
        return
    where_clauses.append(f"LOWER({column}) LIKE LOWER(%s)")
    params.append(f"%{value}%")


def _build_filters(spec: QuerySpec, where_clauses: list[str], params: list[object]) -> None:
    if spec.start_date:
        where_clauses.append("dat_pagamento >= %s")
        params.append(spec.start_date)
    if spec.end_date:
        where_clauses.append("dat_pagamento <= %s")
        params.append(spec.end_date)

    _append_like_filter(where_clauses, params, "dsc_segmento", spec.segmento)
    _append_like_filter(where_clauses, params, "receita_class_subgrupo", spec.subgrupo)
    _append_like_filter(where_clauses, params, "dsc_receita", spec.receita)


def _execute_time_series(spec: QuerySpec) -> dict:
    logger.info("Executando time_series metric=%s group_by=%s", spec.metric, spec.group_by)
    metric_col = METRIC_MAP[spec.metric]
    where_clauses: list[str] = []
    params: list[object] = []
    _build_filters(spec, where_clauses, params)

    if spec.months_back:
        where_clauses.append(
            "dat_pagamento >= DATEADD(month, %s, DATE_TRUNC('month', CURRENT_DATE))"
        )
        params.append(-(spec.months_back - 1))

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

    logger.debug("SQL time_series=%s params=%s", preview_text(sql), params)
    rows = execute_sql(sql, tuple(params))
    data = [
        {
            "mes": row["mes"],
            spec.metric: float(row["valor"]) if row["valor"] is not None else 0,
        }
        for row in rows
    ]

    return {"data": data, "sql": sql, "params": params}


def _execute_aggregate(spec: QuerySpec) -> dict:
    logger.info("Executando aggregate metric=%s group_by=%s", spec.metric, spec.group_by)
    metric_col = METRIC_MAP[spec.metric]
    group_sql = GROUP_BY_MAP[spec.group_by]
    where_clauses: list[str] = []
    params: list[object] = []
    _build_filters(spec, where_clauses, params)

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    order_direction = "DESC" if spec.order_desc else "ASC"
    limit_sql = f"LIMIT {int(spec.top_n)}" if spec.top_n else ""

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

    logger.debug("SQL aggregate=%s params=%s", preview_text(sql), params)
    rows = execute_sql(sql, tuple(params))
    data = [
        {
            spec.group_by: row["categoria"],
            spec.metric: float(row["valor"]) if row["valor"] is not None else 0,
        }
        for row in rows
    ]

    if spec.group_by == "data_pagamento":
        data.sort(key=lambda row: row[spec.group_by])

    return {"data": data, "sql": sql, "params": params}


def _execute_compare(spec: QuerySpec) -> dict:
    logger.info("Executando compare_periods metric=%s group_by=%s", spec.metric, spec.group_by)
    metric_col = METRIC_MAP[spec.metric]
    group_sql = GROUP_BY_MAP[spec.group_by]
    label_1 = spec.period_1_label or "periodo_1"
    label_2 = spec.period_2_label or "periodo_2"

    where_clauses = [
        "dat_pagamento >= %s",
        "dat_pagamento <= %s",
    ]
    params: list[object] = [spec.period_1_start, spec.period_2_end]

    _append_like_filter(where_clauses, params, "dsc_segmento", spec.segmento)
    _append_like_filter(where_clauses, params, "receita_class_subgrupo", spec.subgrupo)
    _append_like_filter(where_clauses, params, "dsc_receita", spec.receita)

    where_sql = "WHERE " + " AND ".join(where_clauses)

    sql = f"""
    SELECT
        {group_sql} AS categoria,
        SUM(CASE WHEN dat_pagamento >= %s
                     AND dat_pagamento <= %s
                 THEN {metric_col} ELSE 0 END) AS valor_periodo_1,
        SUM(CASE WHEN dat_pagamento >= %s
                     AND dat_pagamento <= %s
                 THEN {metric_col} ELSE 0 END) AS valor_periodo_2
    FROM {TABLE_NAME}
    {where_sql}
    GROUP BY 1
    ORDER BY valor_periodo_2 DESC
    LIMIT {int(spec.top_n or 20)}
    """

    execution_params = [
        spec.period_1_start,
        spec.period_1_end,
        spec.period_2_start,
        spec.period_2_end,
        *params,
    ]

    logger.debug("SQL compare=%s params=%s", preview_text(sql), execution_params)
    rows = execute_sql(sql, tuple(execution_params))
    data = []
    for row in rows:
        valor_1 = float(row.get("valor_periodo_1") or 0)
        valor_2 = float(row.get("valor_periodo_2") or 0)
        diff = valor_2 - valor_1
        pct = None if valor_1 == 0 else (diff / valor_1) * 100

        trend = "estavel"
        if diff > 0:
            trend = "subiu"
        elif diff < 0:
            trend = "caiu"

        data.append(
            {
                spec.group_by: row["categoria"],
                label_1: valor_1,
                label_2: valor_2,
                "diferenca": diff,
                "variacao_percentual": pct,
                "tendencia": trend,
            }
        )

    return {"data": data, "sql": sql, "params": execution_params}


def run_query(spec: QuerySpec) -> dict:
    logger.info("run_query analysis_type=%s", spec.analysis_type)
    if spec.analysis_type == "compare_periods":
        return _execute_compare(spec)
    if spec.analysis_type == "time_series":
        return _execute_time_series(spec)
    return _execute_aggregate(spec)