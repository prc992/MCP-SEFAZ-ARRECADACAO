"""Teste HTTP /chat com os serviços reais de planejamento e cálculo, sem banco/LLM."""
import importlib
import sys
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

ROWS = [
    {"mes": "2026-05", "valor_arrecadado": 100},
    {"mes": "2026-06", "valor_arrecadado": 150},
    {"mes": "2026-07", "valor_arrecadado": 120},
    {"mes": "2026-08", "valor_arrecadado": 110},
    {"mes": "2026-09", "valor_arrecadado": 160},
    {"mes": "2026-10", "valor_arrecadado": 80},
]


@pytest.mark.parametrize("mode", ["legacy", "shadow", "active"])
def test_http_chat_consecutive_no_sql_and_without_llm(monkeypatch, mode, tmp_path):
    import chat_service
    import interaction_logger
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", mode)
    monkeypatch.setattr(chat_service, "_client", lambda: (_ for _ in ()).throw(AssertionError("LLM não deveria ser chamada")))
    monkeypatch.setattr(interaction_logger, "BASE", tmp_path)
    stub_pdf = ModuleType("pdf_report")
    from pydantic import BaseModel
    class PdfReportRequest(BaseModel):
        pass
    stub_pdf.PdfReportRequest = PdfReportRequest
    stub_pdf.gerar_pdf_relatorio = lambda *a: b""
    monkeypatch.setitem(sys.modules, "pdf_report", stub_pdf)
    # A consulta analítica de continuação não pode executar SQL.
    import query_engine
    monkeypatch.setattr(query_engine, "executar_query", lambda spec: (_ for _ in ()).throw(AssertionError("SQL não deveria ser executado")))
    main = importlib.import_module("main")
    client = TestClient(main.app)
    response = client.post("/chat", json={
        "question": "qual mes teve a maior queda na arrecadacao?",
        "previous_spec": {"metric": "valor_arrecadado", "group_by": "mes",
                          "chart_type": "line", "analysis_type": "time_series",
                          "report_type": "standard", "start_date": "2026-05-01",
                          "end_date": "2026-10-31"},
        "previous_data": ROWS, "history": [],
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["action"] == "answer"
    assert "2026-09 para 2026-10" in data["answer"]
    assert "-50,00%" in data["answer"]
    assert data["query_interpretada"]["group_by"] == "mes"
    # Não deixar main importado com dependências substituídas contaminar outros testes.
    sys.modules.pop("main", None)
