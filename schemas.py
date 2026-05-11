from pydantic import BaseModel
from typing import Literal


class QuerySpec(BaseModel):
    metric: Literal["valor_arrecadado", "qtd_documentos"]
    group_by: Literal[
        "data_pagamento",
        "receita",
        "codigo_receita",
        "subgrupo",
        "segmento"
    ]
    chart_type: Literal["line", "bar"] = "bar"
    top_n: int | None = 20
    order_desc: bool = True
    start_date: str | None = None
    end_date: str | None = None
    segmento: str | None = None
    subgrupo: str | None = None
    receita: str | None = None


class AskRequest(BaseModel):
    question: str