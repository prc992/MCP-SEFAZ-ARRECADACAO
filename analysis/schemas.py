"""Contratos do processamento determinístico compartilhados pelas etapas 1 e 2.

O planner semântico produz um AnalysisSpec; só o engine calcula.
"""
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


AnalysisOperation = Literal[
    "outros", "amplitude", "maximo", "minimo", "valor", "diferenca",
    "variacao", "variacao_percentual", "crescimento_max",
    "crescimento_min", "crescimento_max_percentual", "crescimento_min_percentual",
    "maior_queda_consecutiva", "maior_alta_consecutiva",
    "maior_queda_percentual_consecutiva", "maior_alta_percentual_consecutiva",
    "variacao_consecutiva", "variacao_entre_periodos",
]

AnalysisStatus = Literal[
    "ok", "too_many_rows", "metric_required", "invalid_data",
    "others_target_required", "category_required", "category_period_required",
    "comparison_period_required", "comparison_extreme_period_required",
    "percent_reference_zero", "all_percent_references_zero", "category_not_found", "unsupported",
    "series_required", "insufficient_periods", "nonconsecutive_periods",
    "incomplete_current_period", "no_matching_change", "periods_required",
]


class AnalysisSpec(BaseModel):
    """Operação e contexto necessários para cálculo, sem depender de QuerySpec."""
    operation: AnalysisOperation
    metric: str | None = None
    category: str | None = None
    explicit_category: str | None = None
    group_by: str
    analysis_type: str
    report_type: str
    period_1_label: str | None = None
    period_2_label: str | None = None
    others_named: bool = False
    from_period: str | None = None
    to_period: str | None = None


class AnalysisResult(BaseModel):
    """Resultado estruturado; nenhum cálculo é delegado ao formatador ou à LLM."""
    spec: AnalysisSpec
    status: AnalysisStatus
    metric_name: str | None = None
    category: str | None = None
    counterpart: str | None = None
    selected_period: str | None = None
    values: dict[str, Decimal | None] = Field(default_factory=dict)
    series: list[dict[str, str | Decimal | None]] = Field(default_factory=list)
