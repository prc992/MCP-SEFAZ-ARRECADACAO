from typing import Any

from pydantic import BaseModel, Field

from app.shared.contracts import QuerySpec


class TemporalContext(BaseModel):
    reference_year: int | None = None
    year_relation: str | None = None
    explicit_year: int | None = None


class ToolCall(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgentPlan(BaseModel):
    can_answer: bool = False
    guidance: str | None = None
    reasoning: str | None = None
    temporal_context: TemporalContext | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    query_spec: QuerySpec | None = None


class AgentResponse(BaseModel):
    can_answer: bool
    message: str
    guidance: str | None = None
    query_spec: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    sql: str | None = None
    data: list[dict[str, Any]] = Field(default_factory=list)
    chart_json: dict[str, Any] | None = None