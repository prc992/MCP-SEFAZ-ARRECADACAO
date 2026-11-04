import json
import logging
import os
from datetime import date
from typing import cast

import httpx
from dotenv import load_dotenv
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

from app.execution.chat_agent.dtos import AgentPlan, TemporalContext, ToolCall
from app.execution.chat_agent.guardrail_policy import get_guidance_message, guardrails_policy_for_prompt
from app.execution.tools.tool_registry import get_planner_catalog
from app.shared.contracts import QuerySpec
from app.shared.logging_utils import exception_chain_text, log_exception_tree, preview_text


load_dotenv()


logger = logging.getLogger(__name__)


def _reference_today() -> date:
    reference_date = os.getenv("APP_REFERENCE_DATE")
    if reference_date:
        try:
            return date.fromisoformat(reference_date)
        except ValueError:
            logger.warning("APP_REFERENCE_DATE inválida: %s", reference_date)
    return date.today()


def _normalize_compare_periods(plan: AgentPlan) -> AgentPlan:
    if not plan.query_spec or plan.query_spec.analysis_type != "compare_periods":
        return plan

    today = _reference_today()
    temporal_context = plan.temporal_context or TemporalContext(reference_year=today.year, year_relation="current")
    reference_year = temporal_context.reference_year or today.year
    spec = plan.query_spec.model_copy(deep=True)

    def _normalize_date(value: str | None) -> str | None:
        if not value:
            return None
        try:
            parsed_date = date.fromisoformat(value)
        except ValueError:
            return value
        if temporal_context.year_relation in {None, "current", "previous", "next"} and parsed_date.year != reference_year:
            parsed_date = parsed_date.replace(year=reference_year)
        return parsed_date.isoformat()

    def _period_label(start_value: str | None, end_value: str | None) -> str | None:
        if not start_value or not end_value:
            return None
        return f"{start_value[5:7]}/{start_value[0:4]}"

    for start_field, end_field, label_field in (
        ("period_1_start", "period_1_end", "period_1_label"),
        ("period_2_start", "period_2_end", "period_2_label"),
    ):
        setattr(spec, start_field, _normalize_date(getattr(spec, start_field)))
        setattr(spec, end_field, _normalize_date(getattr(spec, end_field)))
        setattr(spec, label_field, _period_label(getattr(spec, start_field), getattr(spec, end_field)))

    logger.info(
        "Normalização temporal aplicada year=%s relation=%s period_1=%s..%s period_2=%s..%s",
        reference_year,
        temporal_context.year_relation,
        spec.period_1_start,
        spec.period_1_end,
        spec.period_2_start,
        spec.period_2_end,
    )

    return plan.model_copy(update={"query_spec": spec})


def _build_system_prompt(available_tools: list[dict[str, object]]) -> str:
    today = _reference_today()
    policy_text = guardrails_policy_for_prompt()
    tools_text = json.dumps(available_tools, ensure_ascii=True, indent=2)

    return f"""
Você é um planejador de chamadas de ferramentas para análises de arrecadação.
Use a política de guardrails abaixo como fonte de verdade para o escopo suportado.
Use apenas as ferramentas registradas abaixo. Se nenhuma delas for suficiente, can_answer=false.

Data atual de referência: {today.isoformat()}
Regras de data:
- Resolva referências temporais relativas usando a data de referência acima.
- Se houver ambiguidade temporal, expresse-a em temporal_context e mantenha query_spec com datas concretas.
- Para comparações por períodos, devolva datas finais em YYYY-MM-DD.

Política:
{policy_text}

Ferramentas registradas no servidor MCP:
{tools_text}

Sua tarefa é produzir apenas JSON válido com este formato:
{{
    "can_answer": boolean,
    "reasoning": string,
    "guidance": string|null,
    "temporal_context": {{
        "reference_year": integer|null,
        "year_relation": "current"|"previous"|"next"|"explicit"|null,
        "explicit_year": integer|null
    }}|null,
    "query_spec": object|null,
    "tool_calls": [
        {{
            "tool_name": "query_tool"|"chart_tool",
            "arguments": object
        }}
    ]
}}

Regras:
- can_answer=false quando a pergunta não puder ser traduzida para uma sequência válida de tool_calls dentro da política.
- Nunca invente tool_name fora do catálogo.
- Query tools devem receber a especificação estruturada necessária para executar a busca.
- Se uma ferramenta consumir o resultado da anterior, a execução do agente fornecerá o payload automaticamente.
- Se o usuário pedir gráfico, visualização, chart, plot, barras, linhas, mostrar ou mostre, chart_tool é obrigatório após query_tool quando a consulta for suportada.
- Para comparação entre períodos ou série temporal, inclua chart_tool quando a visualização ajudar a responder a pergunta.
- Não use chart_tool para respostas pedidas só em texto.
- Use analysis_type="time_series" apenas quando a pergunta pedir evolução por mês ou série mensal explícita.
- Para "últimos N meses" sem pedir evolução mensal explícita, prefira analysis_type="aggregate" com months_back=N.
- Se a pergunta disser "por receita" e "últimos 12 meses", mas não pedir evolução mensal, agrupe por receita em aggregate.
- chart_tool recebe o mesmo QuerySpec da query_tool em arguments.spec. Não invente spec de layout de gráfico.
- Quando usar chart_tool, reaproveite o mesmo QuerySpec planejado para query_tool.
- Só marque can_answer=true se as ferramentas registradas forem suficientes para executar a resposta.
- Se can_answer=false, guidance deve conter orientação clara usando: {get_guidance_message()}
- Não responda texto livre fora do JSON.

Especificação obrigatória para query_spec:
- Não use chaves chamadas intent, filters, period, periods ou intervalos soltos.
- Para consultas normais, use:
    {{
        "metric": "valor_arrecadado"|"qtd_documentos",
        "group_by": "data_pagamento"|"mes"|"receita"|"codigo_receita"|"subgrupo"|"segmento",
        "analysis_type": "aggregate"|"time_series",
        "chart_type": "bar"|"line",
        "top_n": 20,
        "order_desc": true|false,
        "months_back": 6|null,
        "start_date": "YYYY-MM-DD"|null,
        "end_date": "YYYY-MM-DD"|null,
        "segmento": string|null,
        "subgrupo": string|null,
        "receita": string|null
    }}
- Para comparações entre dois períodos, use obrigatoriamente:
    {{
        "metric": "valor_arrecadado"|"qtd_documentos",
        "group_by": "data_pagamento"|"mes"|"receita"|"codigo_receita"|"subgrupo"|"segmento",
        "analysis_type": "compare_periods",
        "chart_type": "bar",
        "top_n": 20,
        "order_desc": true,
        "period_1_start": "YYYY-MM-DD",
        "period_1_end": "YYYY-MM-DD",
        "period_1_label": string,
        "period_2_start": "YYYY-MM-DD",
        "period_2_end": "YYYY-MM-DD",
        "period_2_label": string,
        "segmento": string|null,
        "subgrupo": string|null,
        "receita": string|null
    }}
- Para perguntas do tipo "compare valor arrecadado por segmento entre abril e maio de 2026", preencha:
    - metric = "valor_arrecadado"
    - group_by = "segmento"
    - analysis_type = "compare_periods"
    - period_1_start = primeiro dia de abril
    - period_1_end = último dia de abril
    - period_2_start = primeiro dia de maio
    - period_2_end = último dia de maio
    - period_1_label = "abril/2026"
    - period_2_label = "maio/2026"
    - can_answer = true
- Para qualquer pergunta com referência temporal relativa, use temporal_context para refletir a relação temporal interpretada sem depender de expressões literais específicas.
""".strip()


def _compress_history(history: list[dict[str, str]] | None, max_items: int = 8) -> str:
    if not history:
        return "[]"

    normalized: list[dict[str, str]] = []
    for entry in history[-max_items:]:
        role = entry.get("role", "")
        content = entry.get("content", "")
        if role not in {"user", "assistant"}:
            continue
        if not content:
            continue
        normalized.append({"role": role, "content": content[:600]})

    return json.dumps(normalized, ensure_ascii=True)


def _build_client() -> OpenAI | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY não configurada")
        return None
    logger.info("Criando cliente OpenAI com trust_env=False")
    return OpenAI(api_key=api_key, http_client=httpx.Client(trust_env=False))


def _parse_agent_plan(raw_text: str) -> AgentPlan:
    raw = json.loads(raw_text)

    temporal_context = raw.get("temporal_context")
    if temporal_context:
        raw["temporal_context"] = TemporalContext(**temporal_context)

    tool_calls = raw.get("tool_calls") or []
    raw["tool_calls"] = [ToolCall(**call) if isinstance(call, dict) else call for call in tool_calls]

    query_spec = raw.get("query_spec")
    if query_spec:
        raw["query_spec"] = QuerySpec(**query_spec)
    else:
        first_query_call = next(
            (
                call
                for call in raw["tool_calls"]
                if isinstance(call, ToolCall)
                and call.tool_name == "query_tool"
                and isinstance(call.arguments.get("spec"), dict)
            ),
            None,
        )
        raw["query_spec"] = QuerySpec(**first_query_call.arguments["spec"]) if first_query_call else None

    return AgentPlan(**raw)


def _llm_plan(
    question: str,
    history: list[dict[str, str]] | None = None,
    available_tools: list[dict[str, object]] | None = None,
) -> AgentPlan:
    client = _build_client()
    if client is None:
        raise RuntimeError("OPENAI_API_KEY não configurada")

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    tool_catalog = available_tools or get_planner_catalog()
    system_prompt = _build_system_prompt(tool_catalog)
    history_payload = _compress_history(history)
    logger.info(
        "Iniciando planejamento LLM model=%s question=%s history_len=%s tools=%s",
        model,
        preview_text(question),
        len(history or []),
        len(tool_catalog),
    )

    messages = cast(
        list[ChatCompletionMessageParam],
        [
            {"role": "system", "content": system_prompt},
            {
                "role": "system",
                "content": (
                    "Contexto das últimas interações do chat (JSON): "
                    f"{history_payload}. Use apenas como contexto de continuidade."
                ),
            },
            {"role": "user", "content": question},
        ],
    )

    max_repairs = 2
    for attempt in range(max_repairs + 1):
        logger.debug("Chamando LLM tentativa=%s", attempt + 1)
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=messages,
            )
        except Exception as exc:
            logger.error("Falha na chamada LLM: %s", exception_chain_text(exc))
            log_exception_tree(logger, exc, "Detalhes da falha na chamada LLM")
            raise

        content = response.choices[0].message.content or "{}"
        logger.debug("Resposta LLM recebida tamanho=%s", len(content))

        try:
            plan = _parse_agent_plan(content)
            plan = _normalize_compare_periods(plan)
            logger.info(
                "Plano LLM validado can_answer=%s tool_calls=%s",
                plan.can_answer,
                len(plan.tool_calls),
            )
            return plan
        except Exception as exc:
            log_exception_tree(logger, exc, f"Falha ao validar saída da LLM na tentativa={attempt + 1}")
            if attempt >= max_repairs:
                raise RuntimeError(f"llm_plan_invalid_output: {exc}") from exc

            messages.append({"role": "assistant", "content": content})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Sua última resposta não seguiu o schema JSON esperado. "
                        f"Erro de validação: {str(exc)}. "
                        "Retorne novamente APENAS um JSON válido no formato exigido."
                    ),
                }
            )

    raise RuntimeError("llm_plan_retries_exhausted")


def plan_question(
    question: str,
    history: list[dict[str, str]] | None = None,
    available_tools: list[dict[str, object]] | None = None,
) -> AgentPlan:
    try:
        return _llm_plan(question, history=history, available_tools=available_tools)
    except Exception as exc:
        log_exception_tree(logger, exc, "Falha no planejamento; retornando can_answer=False")
        return AgentPlan(
            can_answer=False,
            guidance=get_guidance_message(),
            reasoning="planning_failed",
            tool_calls=[],
            query_spec=None,
        )
