import asyncio
import json
from json import JSONDecodeError
import os
import logging
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from app.shared.logging_utils import preview_text


logger = logging.getLogger(__name__)


def _extract_tool_payload(result: Any) -> dict[str, Any]:
    if hasattr(result, "structuredContent") and result.structuredContent:
        if isinstance(result.structuredContent, dict):
            return result.structuredContent

    if hasattr(result, "content") and result.content:
        texts: list[str] = []
        for item in result.content:
            text = getattr(item, "text", None)
            if text:
                texts.append(text)

        if texts:
            payload_text = "\n".join(texts).strip()
            try:
                return json.loads(payload_text)
            except JSONDecodeError as exc:
                is_error = bool(getattr(result, "isError", False))
                if is_error:
                    raise RuntimeError(f"Servidor MCP retornou erro textual: {payload_text}") from exc
                raise RuntimeError(f"Resposta do servidor MCP não é JSON: {payload_text}") from exc

    raise RuntimeError("Não foi possível interpretar a resposta do servidor MCP")


async def _call_agent_chat(question: str, history: list[dict[str, str]]) -> dict[str, Any]:
    project_root = str(Path(__file__).resolve().parents[2])
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", project_root)

    logger.info(
        "Abrindo sessão MCP stdio: python=%s project_root=%s question=%s history_items=%s",
        sys.executable,
        project_root,
        preview_text(question),
        len(history),
    )

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.execution.mcp_server"],
        env=env,
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            logger.debug("Inicializando sessão MCP")
            await session.initialize()
            logger.debug("Sessão MCP inicializada; chamando agent_tool")
            result = await session.call_tool(
                "agent_tool",
                {
                    "question": question,
                    "history": history,
                },
            )
            logger.info("agent_tool respondeu")
            return _extract_tool_payload(result)


def ask_agent(question: str, history: list[dict[str, str]]) -> dict[str, Any]:
    logger.info("ask_agent invocado")
    return asyncio.run(_call_agent_chat(question, history))