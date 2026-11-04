import logging

from mcp.server.fastmcp import FastMCP

from app.execution.tools.tool_registry import AVAILABLE_TOOLS
from app.shared.logging_utils import setup_console_logging


logger = logging.getLogger(__name__)


mcp = FastMCP("sefaz-arrecadacao-agent")

setup_console_logging()
logger.info("Registrando tools MCP de execução")

for tool in AVAILABLE_TOOLS:
    logger.debug("Registrando tool MCP: %s", tool.name)
    tool.register(mcp)


if __name__ == "__main__":
    logger.info("Iniciando servidor MCP em stdio")
    mcp.run(transport="stdio")