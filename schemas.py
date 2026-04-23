from pydantic import BaseModel
from typing import Literal


class QuerySpec(BaseModel):
    metric: Literal["valor_arrecadado", "qtd_documentos"]
    group_by: Literal["mes", "municipio"]
    municipio: str | None = None
    chart_type: Literal["line", "bar"] = "line"
    top_n: int | None = None
    order_desc: bool = True
    start_mes: str | None = None
    end_mes: str | None = None


class AskRequest(BaseModel):
    question: str