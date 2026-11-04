from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.execution.tools.chart_tool import build_chart
from app.execution.tools.query_tool import run_query
from app.shared.contracts import QuerySpec


McpToolHandler = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: McpToolHandler
    planner_visible: bool = True
    consumes_previous_result: bool = False

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "planner_visible": self.planner_visible,
            "consumes_previous_result": self.consumes_previous_result,
        }

    def register(self, mcp: Any) -> None:
        mcp.tool(name=self.name, description=self.description)(self.handler)


def _execute_query_tool(spec: dict[str, Any]) -> dict[str, Any]:
    return run_query(QuerySpec(**spec))


def _execute_chart_tool(data: list[dict[str, Any]], spec: dict[str, Any]) -> dict[str, Any]:
    return build_chart(data, QuerySpec(**spec))


AVAILABLE_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="query_tool",
        description="Executa consulta estruturada de arrecadação a partir de QuerySpec.",
        handler=_execute_query_tool,
        input_schema={
            "type": "object",
            "properties": {
                "spec": {"type": "object"},
            },
            "required": ["spec"],
        },
    ),
    ToolDefinition(
        name="chart_tool",
        description="Gera gráfico Plotly serializado em JSON a partir dos dados e do mesmo QuerySpec usado na consulta. Use quando o usuário pedir gráfico ou quando a visualização ajudar na resposta.",
        handler=_execute_chart_tool,
        input_schema={
            "type": "object",
            "properties": {
                "data": {"type": "array"},
                "spec": {"type": "object"},
            },
            "required": ["data", "spec"],
        },
        consumes_previous_result=True,
    ),
)


def get_tools(include_hidden: bool = False) -> tuple[ToolDefinition, ...]:
    if include_hidden:
        return AVAILABLE_TOOLS
    return tuple(tool for tool in AVAILABLE_TOOLS if tool.planner_visible)


def get_planner_catalog() -> list[dict[str, Any]]:
    return [tool.to_prompt_payload() for tool in get_tools(include_hidden=False)]


def get_tool_names(include_hidden: bool = False) -> set[str]:
    return {tool.name for tool in get_tools(include_hidden=include_hidden)}


def get_tool_definition(name: str) -> ToolDefinition:
    for tool in AVAILABLE_TOOLS:
        if tool.name == name:
            return tool
    raise KeyError(name)