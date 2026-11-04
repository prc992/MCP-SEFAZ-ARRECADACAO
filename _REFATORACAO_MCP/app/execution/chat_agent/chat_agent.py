import logging
from typing import Any

from app.execution.chat_agent.dtos import AgentResponse, ToolCall
from app.execution.chat_agent.guardrail_policy import get_guidance_message
from app.execution.chat_agent.llm_planner import plan_question
from app.execution.chat_agent.summary_builder import summarize_spec
from app.execution.mcp_stdio_helper import call_mcp_tool
from app.execution.tools.tool_registry import get_planner_catalog, get_tool_names
from app.shared.contracts import QuerySpec
from app.shared.logging_utils import log_exception_tree, preview_text


logger = logging.getLogger(__name__)


FALLBACK_USER_MESSAGE = (
    "Não entendi sua pergunta do jeito que preciso para consultar os dados. "
    "Tente perguntar algo como: 'compare valor arrecadado por segmento entre abril e maio de 2026', "
    "'mostre a arrecadação por receita em junho de 2026' ou "
    "'faça uma série temporal do valor arrecadado nos últimos 6 meses'."
)


TOOL_EXECUTOR_NAMES = get_tool_names()


def _execute_tool_call(
    tool_call: ToolCall,
    prior_result: dict[str, Any] | None,
    fallback_spec: QuerySpec | None = None,
) -> dict[str, Any]:
    logger.info(
        "Executando tool_call=%s arguments=%s",
        tool_call.tool_name,
        preview_text(tool_call.arguments),
    )
    if tool_call.tool_name == "query_tool":
        spec_payload = tool_call.arguments.get("spec")
        if not isinstance(spec_payload, dict):
            raise RuntimeError("query_tool requer arguments.spec como objeto")
        return call_mcp_tool("query_tool", {"spec": spec_payload})

    if tool_call.tool_name == "chart_tool":
        spec_payload = tool_call.arguments.get("spec")
        if not isinstance(spec_payload, dict):
            raise RuntimeError("chart_tool requer arguments.spec como objeto")

        data_payload = tool_call.arguments.get("data")
        if data_payload is None:
            if prior_result is None:
                raise RuntimeError("chart_tool requer dados de uma execução anterior")
            data_payload = prior_result.get("data", [])

        if isinstance(data_payload, list) and not data_payload and prior_result is not None:
            data_payload = prior_result.get("data", [])

        if not isinstance(data_payload, list):
            raise RuntimeError("chart_tool requer arguments.data como lista")

        if fallback_spec is not None:
            try:
                QuerySpec(**spec_payload)
            except Exception:
                spec_payload = fallback_spec.model_dump()

        return call_mcp_tool("chart_tool", {"data": data_payload, "spec": spec_payload})

    raise RuntimeError(f"Tool não suportada: {tool_call.tool_name}")


def chat_agent(
    question: str,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    logger.info("chat_agent iniciado question=%s history_items=%s", preview_text(question), len(history or []))
    available_tools = get_planner_catalog()
    plan = plan_question(question, history=history, available_tools=available_tools)
    logger.info(
        "Planejamento concluído can_answer=%s tool_calls=%s reasoning=%s",
        plan.can_answer,
        len(plan.tool_calls),
        preview_text(plan.reasoning),
    )

    if not plan.can_answer or not plan.tool_calls:
        guidance = plan.guidance or get_guidance_message()
        logger.info("Resposta de fallback para o usuário: %s", preview_text(guidance))
        response = AgentResponse(
            can_answer=False,
            message=FALLBACK_USER_MESSAGE,
            guidance=guidance,
        )
        return response.model_dump()

    unknown_tools = [call.tool_name for call in plan.tool_calls if call.tool_name not in TOOL_EXECUTOR_NAMES]
    if unknown_tools:
        response = AgentResponse(
            can_answer=False,
            message="O plano selecionou ferramentas que não estão registradas no servidor MCP.",
            guidance=f"Ferramentas desconhecidas no plano: {', '.join(sorted(set(unknown_tools)))}.",
        )
        return response.model_dump()

    executed_tools: list[dict[str, Any]] = []
    prior_result: dict[str, Any] | None = None
    query_result: dict[str, Any] | None = None
    chart_json: dict[str, Any] | None = None

    for tool_call in plan.tool_calls:
        logger.info("Iniciando execução de tool=%s", tool_call.tool_name)
        try:
            result = _execute_tool_call(tool_call, prior_result, fallback_spec=plan.query_spec)
        except Exception as exc:
            log_exception_tree(
                logger,
                exc,
                f"Falha executando tool={tool_call.tool_name} question={preview_text(question)}",
            )
            raise
        executed_tools.append(
            {
                "tool_name": tool_call.tool_name,
                "arguments": tool_call.arguments,
            }
        )
        logger.info("Tool %s executada com sucesso", tool_call.tool_name)
        prior_result = result

        if tool_call.tool_name == "query_tool":
            query_result = result
        elif tool_call.tool_name == "chart_tool":
            chart_json = result

    if query_result is None:
        response = AgentResponse(
            can_answer=False,
            message="O plano não executou a tool principal de consulta.",
            guidance="Planeje uma sequência que inclua query_tool quando houver resposta tabular.",
        )
        return response.model_dump()

    data = query_result.get("data", [])
    sql = query_result.get("sql")

    summary = summarize_spec(plan.query_spec) if plan.query_spec else "Consulta executada."
    message = f"{summary} Retornei {len(data)} linhas."

    response = AgentResponse(
        can_answer=True,
        message=message,
        query_spec=plan.query_spec.model_dump() if plan.query_spec else None,
        tool_calls=executed_tools,
        sql=sql,
        data=data,
        chart_json=chart_json,
    )
    logger.info("chat_agent finalizado can_answer=True rows=%s", len(data))
    return response.model_dump()


run_agent = chat_agent
