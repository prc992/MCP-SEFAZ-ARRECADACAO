from redshift_client import executar_sql


TABLE_NAME = "arrecadacao.f_arrecadacao_diaria_consolidada"


def listar_segmentos():
    sql = f"""
    SELECT DISTINCT
        TRIM(dsc_segmento) AS valor
    FROM {TABLE_NAME}
    WHERE dsc_segmento IS NOT NULL
      AND TRIM(dsc_segmento) <> ''
    ORDER BY 1
    """

    rows = executar_sql(sql)

    return [row["valor"] for row in rows if row["valor"]]


def listar_subgrupos_receita():
    sql = f"""
    SELECT DISTINCT
        TRIM(receita_class_subgrupo) AS valor
    FROM {TABLE_NAME}
    WHERE receita_class_subgrupo IS NOT NULL
      AND TRIM(receita_class_subgrupo) <> ''
    ORDER BY 1
    """

    rows = executar_sql(sql)

    return [row["valor"] for row in rows if row["valor"]]