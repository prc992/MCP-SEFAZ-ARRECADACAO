"""Etapa 2: contrato estruturado, roteamento semântico, regressão e shadow.

IMPORTANTE: a LLM é SIMULADA. Estes testes NÃO validam a precisão semântica do
modelo real; validam decisão, execução, isolamento e segurança após o parse.
"""
import json
import logging
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import chat_service
from analysis.planner import AnalysisIntent, AnalysisPlanner
from schemas import QuerySpec


ROWS = [
    {"segmento": "Comércio", "valor_arrecadado": 1000},
    {"segmento": "Indústria", "valor_arrecadado": 250},
    {"segmento": "Serviços", "valor_arrecadado": 500},
]
CMP_ROWS = [
    {"segmento": "Comércio", "agosto_2026": 100, "setembro_2026": 150},
    {"segmento": "Indústria", "agosto_2026": 50, "setembro_2026": 100},
    {"segmento": "Serviços", "agosto_2026": 400, "setembro_2026": 350},
]


def make_req(question, rows=None, **kw):
    compare = kw.get("analysis_type", "aggregate") == "compare_periods"
    spec = QuerySpec(metric="valor_arrecadado", group_by=kw.get("group_by", "segmento"),
                     analysis_type=kw.get("analysis_type", "aggregate"),
                     period_1_label="agosto_2026" if compare else None,
                     period_2_label="setembro_2026" if compare else None,
                     start_date="2026-09-01" if not compare else None,
                     end_date="2026-09-30" if not compare else None)
    return chat_service.ChatRequest(question=question, previous_spec=spec,
                                    previous_data=ROWS if rows is None else rows,
                                    history=kw.get("history", []))


def intent(action="analyze", operation="maximo", metric=None, category=None, source="none"):
    return AnalysisIntent(action=action, operation=operation if action == "analyze" else None,
                          metric=metric if action == "analyze" else None,
                          category=category if action == "analyze" else None,
                          category_source=source if action == "analyze" else "none")


class FakeResponses:
    def __init__(self, intent_value=None, query_decision=None, error=False):
        self.intent_value = intent_value
        self.query_decision = query_decision
        self.error = error
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise RuntimeError("mock_timeout")
        if kwargs["text_format"] is AnalysisIntent:
            return SimpleNamespace(output_parsed=self.intent_value)
        if kwargs["text_format"] is chat_service.ChatDecision:
            return SimpleNamespace(output_parsed=self.query_decision)
        raise AssertionError("Formato de chamada inesperado")


def use_responses(monkeypatch, fake):
    monkeypatch.setattr(chat_service, "_client", lambda: SimpleNamespace(responses=fake))
    return fake


def test_intent_rejects_inconsistent_and_unstructured_payloads():
    with pytest.raises(ValidationError):
        AnalysisIntent(action="analyze", operation=None, metric=None, category=None, category_source="none")
    with pytest.raises(ValidationError):
        AnalysisIntent(action="query", operation="maximo", metric=None, category=None, category_source="none")
    with pytest.raises(ValidationError):
        AnalysisIntent(action="analyze", operation="sql_exec", metric=None, category=None, category_source="none")
    with pytest.raises(ValidationError):
        AnalysisIntent(action="analyze", operation="valor", metric=None, category="Comércio", category_source="none")
    with pytest.raises(ValidationError):
        AnalysisIntent(action="defer", operation=None, metric=None, category=None, category_source="none", extra_key=True)


def test_semantic_fixes_order_of_words_in_active(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    fake = use_responses(monkeypatch, FakeResponses(intent("analyze", "maximo")))
    req = make_req("Qual segmento arrecadou mais?")
    assert chat_service._op(req) is None  # Limitação original preservada.
    answer = chat_service.decidir_continuacao(req)
    assert answer.origin == "deterministic"
    assert answer.action == "answer"
    assert "Comércio" in answer.answer and "R$ 1.000,00" in answer.answer
    assert len(fake.calls) == 1


def test_active_cross_period_ranking_runs_math_in_engine(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    fake = use_responses(monkeypatch, FakeResponses(intent(operation="crescimento_max_percentual")))
    req = make_req("Quem teve a maior alta proporcional?", CMP_ROWS,
                   analysis_type="compare_periods")
    response = chat_service.decidir_continuacao(req)
    assert response.origin == "deterministic"
    assert "Indústria" in response.answer
    assert "100,00%" in response.answer
    assert "R$ 50,00" in response.answer
    assert len(fake.calls) == 1


def test_active_uses_last_turn_explicitly_for_ellipsis(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    fake = use_responses(monkeypatch, FakeResponses(
        intent(operation="variacao_percentual", category="Comércio", source="previous")))
    req = make_req("E proporcionalmente?", CMP_ROWS, analysis_type="compare_periods",
                   history=[{"user": "Qual a diferença do Comércio?",
                             "assistant": "Comércio: diferença de R$ 50,00"}])
    response = chat_service.decidir_continuacao(req)
    assert "Comércio" in response.answer and "50,00%" in response.answer
    assert len(fake.calls) == 1


def test_planner_only_receives_metadata_and_no_numeric_measures(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    fake = use_responses(monkeypatch, FakeResponses(intent()))
    chat_service.decidir_continuacao(make_req("Quem liderou?"))
    inputs = fake.calls[0]["input"]
    data = json.loads(inputs[1]["content"])
    assert "dados_atuais" not in data
    assert "previous_data" not in data
    assert data["categorias_disponiveis"] == ["Comércio", "Indústria", "Serviços"]
    assert data["metricas_disponiveis"] == ["valor_arrecadado"]
    assert "1000" not in inputs[1]["content"]


def test_active_invalid_metric_cannot_execute_or_go_to_free_llm(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    fake = use_responses(monkeypatch, FakeResponses(intent(metric="lucro_liquido")))
    result = chat_service.decidir_continuacao(make_req("Qual maior lucro líquido?"))
    assert result.action == "answer"
    assert "não foi validada" in result.answer
    assert "1.000" not in result.answer
    assert len(fake.calls) == 1


def test_active_unknown_category_cannot_trigger_keyerror_or_hallucination(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    fake = use_responses(monkeypatch, FakeResponses(
        intent(operation="valor", category="Categoria inexistente", source="current")))
    result = chat_service.decidir_continuacao(make_req("Quanto ganhou a Categoria inexistente?"))
    assert result.action == "answer"
    assert "não foi validada" in result.answer
    assert len(fake.calls) == 1


def test_active_query_route_not_hijacked_by_legacy_quanto(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    new_spec = QuerySpec(metric="valor_arrecadado", group_by="total",
                         start_date="2026-10-01", end_date="2026-10-31")
    fake = use_responses(monkeypatch, FakeResponses(
        intent_value=intent("query"),
        query_decision=chat_service.ChatDecision(action="query", query_spec=new_spec)))
    req = make_req("Quanto o estado arrecadou em outubro de 2026?")
    assert chat_service._op(req) == "valor"  # Perigo no parser antigo.
    result = chat_service.decidir_continuacao(req)
    assert result.action == "query"
    assert result.query_spec.start_date == "2026-10-01"
    assert result.origin == "llm_query"
    assert len(fake.calls) == 2


def test_active_query_route_blocks_old_dataset_answer(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    fake = use_responses(monkeypatch, FakeResponses(
        intent_value=intent("query"),
        query_decision=chat_service.ChatDecision(action="answer", answer="O total é R$ 1000.")))
    result = chat_service.decidir_continuacao(make_req("Quanto arrecadamos em outubro?"))
    assert result.action == "answer"
    assert "precisa de uma nova consulta" in result.answer
    assert "R$ 1000" not in result.answer


def test_active_defer_preserves_explanatory_llm_answers(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    fake = use_responses(monkeypatch, FakeResponses(
        intent_value=intent("defer"),
        query_decision=chat_service.ChatDecision(action="answer", answer="Sem evidência causal.")))
    result = chat_service.decidir_continuacao(make_req("Por que aconteceu a mudança?"))
    assert result.action == "answer" and result.answer == "Sem evidência causal."
    assert result.origin == "llm"


def test_shadow_records_both_decisions_without_changing_answer(monkeypatch, caplog):
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "shadow")
    fake = use_responses(monkeypatch, FakeResponses(intent(operation="maximo")))
    req = make_req("Qual segmento mais arrecadou?")
    baseline = chat_service._responder_deterministico(req)
    with caplog.at_level(logging.INFO, logger=chat_service.logger.name):
        result = chat_service.decidir_continuacao(req)
    assert result.origin == "deterministic"
    assert result.answer == baseline
    assert "answer_matches=True" in caplog.text
    assert "legacy_op=maximo" in caplog.text
    assert len(fake.calls) == 1


def test_shadow_reports_semantic_candidate_for_old_parser_gap(monkeypatch, caplog):
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "shadow")
    old_decision = chat_service.ChatDecision(action="answer", answer="Resposta do modo anterior")
    fake = use_responses(monkeypatch, FakeResponses(intent_value=intent(), query_decision=old_decision))
    with caplog.at_level(logging.INFO, logger=chat_service.logger.name):
        result = chat_service.decidir_continuacao(make_req("Qual segmento arrecadou mais?"))
    assert result.answer == "Resposta do modo anterior"
    assert "legacy_op=None" in caplog.text
    assert "semantic_op=maximo" in caplog.text
    assert "answer_matches=None" in caplog.text


def test_shadow_preserves_legacy_and_active_fails_closed_on_timeout(monkeypatch):
    for mode in ("shadow", "active"):
        monkeypatch.setenv("ANALYSIS_PLANNER_MODE", mode)
        fake = use_responses(monkeypatch, FakeResponses(error=True))
        result = chat_service.decidir_continuacao(make_req("Qual segmento mais arrecadou?"))
        assert result.origin == "deterministic"
        if mode == "shadow":
            assert "Comércio" in result.answer
        else:
            assert "Não foi possível validar" in result.answer
            assert "1.000" not in result.answer
        assert len(fake.calls) == 1


def test_default_mode_legacy_does_not_call_semantic_llm(monkeypatch):
    monkeypatch.delenv("ANALYSIS_PLANNER_MODE", raising=False)
    fake = use_responses(monkeypatch, FakeResponses(error=True))
    result = chat_service.decidir_continuacao(make_req("Qual segmento mais arrecadou?"))
    assert result.origin == "deterministic"
    assert not fake.calls


def test_truncation_protected_even_when_semantic_planner_recognizes_operation(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    rows = [{"segmento": f"segmento_{i}", "valor_arrecadado": i} for i in range(101)]
    fake = use_responses(monkeypatch, FakeResponses(intent()))
    result = chat_service.decidir_continuacao(make_req("Qual segmento arrecadou mais?", rows))
    assert "muitas linhas" in result.answer
    assert len(fake.calls) == 1


def test_truncation_does_not_block_new_query(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    rows = [{"segmento": f"segmento_{i}", "valor_arrecadado": i} for i in range(101)]
    new_spec = QuerySpec(metric="valor_arrecadado", group_by="total",
                         start_date="2026-10-01", end_date="2026-10-31")
    fake = use_responses(monkeypatch, FakeResponses(
        intent_value=intent("query"),
        query_decision=chat_service.ChatDecision(action="query", query_spec=new_spec)))
    result = chat_service.decidir_continuacao(make_req("Quanto arrecadamos em outubro?", rows))
    assert result.action == "query"
    assert len(fake.calls) == 2


def test_invalid_others_request_rejected_by_planner(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    fake = use_responses(monkeypatch, FakeResponses(
        intent(operation="outros", category="Comércio", source="previous")))
    result = chat_service.decidir_continuacao(make_req("Os outros juntos superaram?"))
    assert "não foi validada" in result.answer


def test_semantic_action_with_missing_metric_asks_instead_of_fabricating(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    fake = use_responses(monkeypatch, FakeResponses(intent(operation="maximo")))
    bad = make_req("Qual teve a maior arrecadação?", [{"segmento": "Comércio", "qtd_documentos": 5}])
    # A menção explícita a arrecadação NÃO pode ser reinterpretada como documentos.
    response = chat_service.decidir_continuacao(bad)
    assert response.action == "answer"  # Nunca gera SQL ou números livres.
    assert "não está disponível" in response.answer
    assert "documentos pagos:" not in response.answer


def test_semantic_comparison_with_numeric_protection_zero_reference(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    fake = use_responses(monkeypatch, FakeResponses(
        intent(operation="variacao_percentual", category="Comércio", source="current")))
    rows = [{"segmento": "Comércio", "agosto_2026": 0, "setembro_2026": 100}]
    response = chat_service.decidir_continuacao(make_req("Variação do Comércio?", rows,
                                                       analysis_type="compare_periods"))
    assert "referência" in response.answer


def test_model_returning_none_is_safe_in_active(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    fake = use_responses(monkeypatch, FakeResponses(intent_value=None, query_decision=None))
    response = chat_service.decidir_continuacao(make_req("Quem mais arrecadou?"))
    assert "não foi validada" in response.answer
    assert len(fake.calls) == 1


def test_previous_category_must_be_grounded_in_last_turn(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    use_responses(monkeypatch, FakeResponses(
        intent(operation="valor", category="Comércio", source="previous")))
    response = chat_service.decidir_continuacao(make_req(
        "E esse valor?", history=[{"user": "E a indústria?", "assistant": "Indústria = R$ 250,00"}]))
    assert "não foi validada" in response.answer


def test_previous_decendio_ordinal_grounded(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    use_responses(monkeypatch, FakeResponses(intent(
        operation="valor", category="1 Decêndio", source="previous")))
    rows = [{"decendio": "1 Decêndio", "valor_arrecadado": 100},
            {"decendio": "2 Decêndio", "valor_arrecadado": 200}]
    response = chat_service.decidir_continuacao(make_req(
        "E o valor?", rows, group_by="decendio",
        history=[{"user": "Qual o primeiro decêndio?", "assistant": "1º decêndio: R$ 100,00"}]))
    assert "1º decêndio" in response.answer
    assert "R$ 100,00" in response.answer


def test_explicit_metric_disagreement_rejected(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    use_responses(monkeypatch, FakeResponses(intent(operation="maximo", metric="icms_a")))
    rows = [{"decendio": "1 Decêndio", "icms_a": 100, "fecop_b": 10},
            {"decendio": "2 Decêndio", "icms_a": 50, "fecop_b": 20}]
    spec = QuerySpec(metric="valor_arrecadado", group_by="decendio", report_type="icms_fecop")
    req = chat_service.ChatRequest(question="Qual o maior FECOP?", previous_data=rows,
                                   previous_spec=spec)
    response = chat_service.decidir_continuacao(req)
    assert "não corresponde" in response.answer
    assert "100,00" not in response.answer


def test_fiscal_metric_selected_with_structured_semantics(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    use_responses(monkeypatch, FakeResponses(intent(operation="maximo", metric="fecop_b")))
    rows = [{"decendio": "1 Decêndio", "icms_a": 100, "fecop_b": 10},
            {"decendio": "2 Decêndio", "icms_a": 50, "fecop_b": 20}]
    spec = QuerySpec(metric="valor_arrecadado", group_by="decendio", report_type="icms_fecop")
    req = chat_service.ChatRequest(question="Qual o maior FECOP?", previous_data=rows,
                                   previous_spec=spec)
    response = chat_service.decidir_continuacao(req)
    assert "2º decêndio" in response.answer
    assert "R$ 20,00" in response.answer


def test_engine_rejects_category_not_in_result():
    from analysis.engine import AnalysisEngine
    from analysis.schemas import AnalysisSpec
    spec = AnalysisSpec(operation="valor", metric="valor_arrecadado",
                        group_by="segmento", analysis_type="aggregate",
                        report_type="standard", category="Fantasia")
    result = AnalysisEngine().execute(spec, ROWS)
    assert result.status == "category_not_found"



def test_planner_masks_last_answer_values_but_keeps_referent(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    fake = use_responses(monkeypatch, FakeResponses(intent(
        operation="valor", category="Comércio", source="previous")))
    req = make_req("E seu valor?", history=[
        {"user": "Quanto arrecadou o Comércio?", "assistant": "Comércio: R$ 1.000,00; variação 25,00%"}
    ])
    result = chat_service.decidir_continuacao(req)
    assert "R$ 1.000,00" in result.answer
    sent = json.loads(fake.calls[0]["input"][1]["content"])
    assert "Comércio" in sent["ultima_troca"][0]["assistant"]
    assert "R$ 1.000,00" not in sent["ultima_troca"][0]["assistant"]
    assert "25,00%" not in sent["ultima_troca"][0]["assistant"]
