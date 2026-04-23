def get_metadata():
    return {
        "dataset": "arrecadacao_mock",
        "description": "API de teste para consulta agregada de arrecadação",
        "metrics": [
            {
                "name": "valor_arrecadado",
                "label": "Valor arrecadado",
                "aggregations": ["sum"]
            },
            {
                "name": "qtd_documentos",
                "label": "Quantidade de documentos",
                "aggregations": ["sum"]
            }
        ],
        "group_by_options": [
            {
                "name": "mes",
                "label": "Mês"
            },
            {
                "name": "municipio",
                "label": "Município"
            }
        ],
        "chart_types": [
            {
                "name": "line",
                "label": "Line chart"
            },
            {
                "name": "bar",
                "label": "Bar chart"
            }
        ],
        "filters": {
            "municipio": "string opcional",
            "start_mes": "YYYY-MM opcional",
            "end_mes": "YYYY-MM opcional",
            "top_n": "int opcional",
            "order_desc": "bool opcional"
        }
    }