from redshift_client import executar_sql

sql = """
SELECT
    dsc_segmento,
    SUM(vlr_arrecadado) AS valor_arrecadado,
    SUM(qtd_dae_pag) AS qtd_documentos
FROM arrecadacao.f_arrecadacao_diaria_consolidada
GROUP BY dsc_segmento
ORDER BY valor_arrecadado DESC
LIMIT 10
"""

dados = executar_sql(sql)

for row in dados:
    print(row)