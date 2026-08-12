import logging

import plotly.graph_objects as go
import streamlit as st

from app.execution.chat_agent import chat_agent
from app.shared.logging_utils import log_exception_tree, preview_text, setup_console_logging


logger = logging.getLogger(__name__)


def _render_result_block(result: dict[str, object], expanded: bool) -> None:
    with st.expander("Resultados", expanded=expanded):
        chart_json = result.get("chart_json")
        if chart_json:
            fig = go.Figure(chart_json)
            st.plotly_chart(fig, use_container_width=True)

        query_spec = result.get("query_spec")
        sql = result.get("sql")
        data = result.get("data", [])

        if query_spec:
            st.subheader("QuerySpec")
            st.json(query_spec)

        if sql:
            st.subheader("SQL")
            st.code(sql, language="sql")

        st.subheader("Dados")
        st.dataframe(data, use_container_width=True)


def _latest_assistant_result_index(messages: list[dict[str, object]]) -> int | None:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("role") == "assistant" and message.get("result"):
            return index
    return None


def main() -> None:
    setup_console_logging()
    logger.info("Streamlit UI iniciada")
    st.set_page_config(page_title="MCP SEFAZ Arrecadação", page_icon="SA", layout="wide")

    st.title("Chat de Arrecadação com MCP")
    st.caption(
        "As perguntas são convertidas pelo chat_agent em chamadas de query_tool e chart_tool via servidor MCP local."
    )

    if "messages" not in st.session_state:
        st.session_state.messages = []

    latest_result_index = _latest_assistant_result_index(st.session_state.messages)

    for index, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant" and message.get("result"):
                _render_result_block(message["result"], expanded=index == latest_result_index)

    question = st.chat_input("Ex.: compare valor arrecadado por segmento entre abril e maio de 2026")

    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner("Orquestrando ferramentas MCP..."):
                try:
                    history_payload = [
                        {"role": m["role"], "content": m["content"]}
                        for m in st.session_state.messages
                    ]
                    logger.info(
                        "Chamando chat_agent: question=%s history_items=%s",
                        preview_text(question),
                        len(history_payload),
                    )
                    result = chat_agent(question, history_payload)
                    logger.info(
                        "chat_agent respondeu: can_answer=%s keys=%s",
                        result.get("can_answer"),
                        sorted(result.keys()),
                    )
                except Exception as exc:
                    log_exception_tree(logger, exc, "Falha ao consultar o chat_agent")
                    result = {
                        "can_answer": False,
                        "message": "Falha ao consultar o chat_agent.",
                        "guidance": str(exc),
                    }

            st.markdown(result.get("message", "Sem mensagem."))

            if result.get("can_answer"):
                _render_result_block(result, expanded=True)

            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": result.get("message", "Sem mensagem."),
                    "result": result if result.get("can_answer") else None,
                }
            )


if __name__ == "__main__":
    main()
