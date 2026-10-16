from pydantic import BaseModel, Field
from typing import Literal


class QuerySpec(BaseModel):
    metric: Literal["valor_arrecadado", "qtd_documentos"]
    group_by: Literal[
        "total",
        "data_pagamento",
        "mes",
        "receita",
        "codigo_receita",
        "subgrupo",
        "segmento",
        "decendio"
    ]
    chart_type: Literal["line", "bar"] = "bar"
    top_n: int | None = 20
    order_desc: bool = True

    analysis_type: Literal["aggregate", "compare_periods", "time_series"] = "aggregate"
    report_type: Literal["standard", "icms_fecop"] = "standard"
    months_back: int | None = None

    start_date: str | None = None
    end_date: str | None = None

    period_1_start: str | None = None
    period_1_end: str | None = None
    period_1_label: str | None = None

    period_2_start: str | None = None
    period_2_end: str | None = None
    period_2_label: str | None = None

    segmento: str | None = None
    subgrupo: str | None = None
    receita: str | None = None

    decendio: int | None = Field(default=None, ge=1, le=3)


class AskRequest(BaseModel):
    question: str
