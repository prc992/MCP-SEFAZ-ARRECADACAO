from functools import lru_cache

from app.infrastructure.redshift_client import execute_sql


TABLE_NAME = "arrecadacao.f_arrecadacao_diaria_consolidada"


@lru_cache(maxsize=1)
def list_segmentos() -> list[str]:
    sql = f"""
    SELECT DISTINCT
        TRIM(dsc_segmento) AS valor
    FROM {TABLE_NAME}
    WHERE dsc_segmento IS NOT NULL
      AND TRIM(dsc_segmento) <> ''
    ORDER BY 1
    """
    rows = execute_sql(sql)
    return [row["valor"] for row in rows if row.get("valor")]


@lru_cache(maxsize=1)
def list_subgrupos_receita() -> list[str]:
    sql = f"""
    SELECT DISTINCT
        TRIM(receita_class_subgrupo) AS valor
    FROM {TABLE_NAME}
    WHERE receita_class_subgrupo IS NOT NULL
      AND TRIM(receita_class_subgrupo) <> ''
    ORDER BY 1
    """
    rows = execute_sql(sql)
    return [row["valor"] for row in rows if row.get("valor")]