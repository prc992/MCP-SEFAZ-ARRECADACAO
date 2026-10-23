"""Contratos HTTP reais de main.py, com I/O externo simulado.

Use no projeto com main.py presente. Testes não acessam Redshift ou OpenAI.
"""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def api(monkeypatch):
    main_path = ROOT / "main.py"
    if not main_path.exists():
        pytest.skip("main.py não incluído neste pacote; copie testes para a raiz do projeto")

    events = []
    def shim(name, **symbols):
        mod = ModuleType(name)
        for key, value in symbols.items():
            setattr(mod, key, value)
        monkeypatch.setitem(sys.modules, name, mod)

    class PlotlyFigure:
        def to_dict(self):
            return {"data": [], "layout": {}}

    shim("query_engine", executar_query=lambda spec: {
        "dados": [{"subgrupo": "ICMS", "valor_arrecadado": 500}],
        "sql": "SELECT ficticio PARA TESTE",
    })
    shim("chart_engine", gerar_plotly_figure=lambda *a: PlotlyFigure(),
         gerar_graficos_icms_fecop=lambda *a: [PlotlyFigure()])
    shim("metadata_service", get_metadata=lambda: {})
    shim("ask_service", gerar_summary=lambda spec: "Resumo de teste")
    shim("data_availability_service", validar_disponibilidade=lambda spec: {"disponivel": True})
    shim("interaction_logger", novo_id=lambda: "id-123", validar_id=lambda x: x if x else None,
         registrar_interacao=lambda **kwargs: events.append(kwargs), registrar_feedback=lambda **kwargs: True)

    spec = importlib.util.spec_from_file_location("_test_etapa1_main", main_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return TestClient(module.app), events


def _payload(question, rows=None, spec_changes=None):
    spec = {
        "metric": "valor_arrecadado", "group_by": "segmento", "analysis_type": "aggregate",
        "report_type": "standard", "start_date": "2026-09-01", "end_date": "2026-09-30",
    }
    spec.update(spec_changes or {})
    return {
        "question": question,
        "previous_spec": spec,
        "previous_data": rows if rows is not None else [
            {"segmento": "Comércio", "valor_arrecadado": 1000},
            {"segmento": "Indústria", "valor_arrecadado": 250},
        ],
        "history": [],
    }


def test_playground_sends_existing_chat_contract(api):
    client, _ = api
    res = client.get("/playground")
    assert res.status_code == 200
    assert 'fetch("/chat"' in res.text
    assert 'previous_spec:conversaAtual.query_interpretada' in res.text
    assert 'previous_data:(conversaAtual.dados_brutos || []).slice(0, 101)' in res.text
    assert 'history:historicoChat.slice(-8)' in res.text


def test_chat_deterministic_real_query_spec_no_llm(api, monkeypatch):
    import chat_service
    monkeypatch.setattr(chat_service, "_client", lambda: (_ for _ in ()).throw(AssertionError("LLM acionada")))
    client, events = api
    res = client.post("/chat", json=_payload("Qual segmento mais arrecadou?"))
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["action"] == "answer"
    assert "Comércio" in data["answer"]
    assert "R$ 1.000,00" in data["answer"]
    assert data["query_interpretada"]["group_by"] == "segmento"
    assert data["session_id"] == "id-123"
    assert events[-1]["origem"] == "deterministic"


def test_chat_compare_periods_and_zero_baseline(api, monkeypatch):
    import chat_service
    monkeypatch.setattr(chat_service, "_client", lambda: (_ for _ in ()).throw(AssertionError("LLM acionada")))
    client, _ = api
    spec = {"analysis_type": "compare_periods", "period_1_label": "agosto_2026", "period_2_label": "setembro_2026"}
    rows = [
        {"segmento": "Comércio", "agosto_2026": 100, "setembro_2026": 150},
        {"segmento": "Indústria", "agosto_2026": 50, "setembro_2026": 100},
    ]
    res = client.post("/chat", json=_payload("Qual segmento teve maior crescimento percentual?", rows, spec))
    assert res.status_code == 200
    assert res.json()["action"] == "answer"
    assert "Indústria" in res.json()["answer"]
    assert "100,00%" in res.json()["answer"]

    zero = [{"segmento": "Comércio", "agosto_2026": 0, "setembro_2026": 10}]
    res = client.post("/chat", json=_payload("Qual foi a variação percentual do Comércio?", zero, spec))
    assert res.status_code == 200
    assert "referência" in res.json()["answer"]


def test_chat_truncation_guard(api, monkeypatch):
    import chat_service
    monkeypatch.setattr(chat_service, "_client", lambda: (_ for _ in ()).throw(AssertionError("LLM acionada")))
    client, _ = api
    rows = [{"segmento": str(i), "valor_arrecadado": i} for i in range(101)]
    res = client.post("/chat", json=_payload("Qual segmento mais arrecadou?", rows))
    assert res.status_code == 200
    assert res.json()["action"] == "answer"
    assert "muitas linhas" in res.json()["answer"]


def test_chat_new_query_keeps_original_route(api, monkeypatch):
    import chat_service
    from schemas import QuerySpec
    client, events = api

    updated = QuerySpec(metric="valor_arrecadado", group_by="subgrupo", start_date="2026-09-01", end_date="2026-09-30")
    class FakeResponses:
        def parse(self, **kwargs):
            return SimpleNamespace(output_parsed=chat_service.ChatDecision(action="query", query_spec=updated))
    monkeypatch.setattr(chat_service, "_client", lambda: SimpleNamespace(responses=FakeResponses()))

    res = client.post("/chat", json=_payload("Mostre o mesmo período por subgrupo"))
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["action"] == "query"
    assert data["query_interpretada"]["group_by"] == "subgrupo"
    assert data["dados_brutos"] == [{"subgrupo": "ICMS", "valor_arrecadado": 500}]
    assert data["plotly_json"] == {"data": [], "layout": {}}
    assert events[-1]["origem"] == "llm_query"


def test_chat_rejects_invalid_real_query_spec(api):
    client, _ = api
    res = client.post("/chat", json=_payload("Qual o maior?", spec_changes={"group_by": "nao_existe"}))
    assert res.status_code == 422


def test_chat_fiscal_comparison_ignores_total_geral(api, monkeypatch):
    import chat_service
    monkeypatch.setattr(chat_service, "_client", lambda: (_ for _ in ()).throw(AssertionError("LLM acionada")))
    client, _ = api
    spec = {
        "group_by": "decendio", "report_type": "icms_fecop",
        "analysis_type": "compare_periods", "period_1_label": "agosto_2026",
        "period_2_label": "setembro_2026",
    }
    rows = [
        {"decendio": "1 Decêndio", "periodo": "agosto_2026", "icms_a": 100},
        {"decendio": "1 Decêndio", "periodo": "setembro_2026", "icms_a": 150},
        {"decendio": "2 Decêndio", "periodo": "agosto_2026", "icms_a": 100},
        {"decendio": "2 Decêndio", "periodo": "setembro_2026", "icms_a": 120},
        {"decendio": "Total geral", "periodo": "agosto_2026", "icms_a": 200},
        {"decendio": "Total geral", "periodo": "setembro_2026", "icms_a": 270},
    ]
    res = client.post("/chat", json=_payload("Qual decêndio teve maior crescimento percentual do ICMS?", rows, spec))
    assert res.status_code == 200, res.text
    assert res.json()["action"] == "answer"
    assert "1º decêndio" in res.json()["answer"]
    assert "50,00%" in res.json()["answer"]


def test_keyword_limit_remains_until_phase_2():
    from chat_service import _op, ChatRequest
    from schemas import QuerySpec
    spec = QuerySpec(metric="valor_arrecadado", group_by="segmento")
    req = ChatRequest(question="Qual segmento arrecadou mais?", previous_spec=spec)
    assert _op(req) is None


def test_chat_active_semantic_origin_logged_as_deterministic(api, monkeypatch):
    from analysis.planner import AnalysisIntent
    import chat_service

    class FakeResponses:
        def parse(self, **kwargs):
            assert kwargs["text_format"] is AnalysisIntent
            return SimpleNamespace(output_parsed=AnalysisIntent(
                action="analyze", operation="maximo", metric=None,
                category=None, category_source="none"))

    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    monkeypatch.setattr(chat_service, "_client", lambda: SimpleNamespace(responses=FakeResponses()))
    client, events = api
    res = client.post("/chat", json=_payload("Qual segmento arrecadou mais?"))
    assert res.status_code == 200, res.text
    assert res.json()["action"] == "answer"
    assert "R$ 1.000,00" in res.json()["answer"]
    assert events[-1]["origem"] == "deterministic"
    assert res.json()["query_interpretada"]["group_by"] == "segmento"


def test_chat_active_new_query_still_executes_existing_pipeline(api, monkeypatch):
    from analysis.planner import AnalysisIntent
    import chat_service
    from schemas import QuerySpec

    new_spec = QuerySpec(metric="valor_arrecadado", group_by="subgrupo",
                         start_date="2026-10-01", end_date="2026-10-31")

    class FakeResponses:
        def parse(self, **kwargs):
            if kwargs["text_format"] is AnalysisIntent:
                return SimpleNamespace(output_parsed=AnalysisIntent(
                    action="query", operation=None, metric=None,
                    category=None, category_source="none"))
            if kwargs["text_format"] is chat_service.ChatDecision:
                return SimpleNamespace(output_parsed=chat_service.ChatDecision(
                    action="query", query_spec=new_spec))
            raise AssertionError("unexpected format")

    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    monkeypatch.setattr(chat_service, "_client", lambda: SimpleNamespace(responses=FakeResponses()))
    client, events = api
    res = client.post("/chat", json=_payload("Quanto foi arrecadado em outubro por subgrupo?"))
    assert res.status_code == 200, res.text
    assert res.json()["action"] == "query"
    assert res.json()["query_interpretada"]["start_date"] == "2026-10-01"
    assert res.json()["dados_brutos"] == [{"subgrupo": "ICMS", "valor_arrecadado": 500}]
    assert events[-1]["origem"] == "llm_query"

def test_http_active_schema_error_does_not_answer_freely(api, monkeypatch):
    import chat_service
    from analysis.planner import AnalysisIntent
    client, events = api
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")

    class InvalidResponses:
        def __init__(self):
            self.calls = 0

        def parse(self, **kwargs):
            self.calls += 1
            assert kwargs["text_format"] is AnalysisIntent
            AnalysisIntent.model_validate({
                "action": "defer", "operation": "maximo", "metric": None,
                "category": None, "category_source": "none",
            })

    fake = InvalidResponses()
    monkeypatch.setattr(chat_service, "_client", lambda: SimpleNamespace(responses=fake))
    response = client.post("/chat", json=_payload("Quem liderou a arrecadação?"))
    assert response.status_code == 200
    answer = response.json()
    assert answer["action"] == "answer"
    assert "não foi validada" in answer["answer"]
    assert "1.000" not in answer["answer"]
    assert events[-1]["origem"] == "deterministic"
    assert fake.calls == 2


def test_http_active_validator_corrects_unfounded_rank_category(api, monkeypatch):
    """O ranking não pode usar um 'setor' fictício como categoria individual."""
    import chat_service
    from analysis.planner import AnalysisIntent

    class FakeResponses:
        def parse(self, **kwargs):
            assert kwargs["text_format"] is AnalysisIntent
            return SimpleNamespace(output_parsed=AnalysisIntent(
                action="analyze", operation="maximo", metric=None,
                category="setor", category_source="current"))

    client, events = api
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    monkeypatch.setattr(chat_service, "_client", lambda: SimpleNamespace(responses=FakeResponses()))
    response = client.post("/chat", json=_payload("Qual setor ficou na primeira posição?"))
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "answer"
    assert "Comércio" in data["answer"] and "R$ 1.000,00" in data["answer"]
    assert events[-1]["origem"] == "deterministic"


def test_http_active_validator_clarification_never_calls_unstructured_llm(api, monkeypatch):
    import chat_service
    from analysis.planner import AnalysisIntent

    class AlwaysWrong:
        def __init__(self):
            self.calls = []
        def parse(self, **kwargs):
            self.calls.append(kwargs)
            assert kwargs["text_format"] is AnalysisIntent
            return SimpleNamespace(output_parsed=AnalysisIntent(
                action="query", operation=None, metric=None,
                category=None, category_source="none"))

    client, events = api
    fake = AlwaysWrong()
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    monkeypatch.setattr(chat_service, "_client", lambda: SimpleNamespace(responses=fake))
    response = client.post("/chat", json=_payload("Qual segmento ficou na primeira posição?"))
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "answer"
    assert "dados já exibidos" in data["answer"]
    assert "1.000" not in data["answer"]
    assert events[-1]["origem"] == "deterministic"
    assert len(fake.calls) == 2
