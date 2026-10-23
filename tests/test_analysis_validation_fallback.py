"""Falhas reais de parse Pydantic: reclassificação limitada e fallback seguro."""
import logging
from types import SimpleNamespace

import pytest

import chat_service
from analysis.planner import AnalysisIntent
from schemas import QuerySpec


ROWS = [
    {"segmento": "Comercio", "valor_arrecadado": 1000},
    {"segmento": "Industria", "valor_arrecadado": 250},
]


def request(question):
    return chat_service.ChatRequest(
        question=question,
        previous_spec=QuerySpec(metric="valor_arrecadado", group_by="segmento"),
        previous_data=ROWS,
    )


def parsed_intent():
    return AnalysisIntent(action="analyze", operation="maximo", metric=None,
                          category=None, category_source="none")


def invalid_intent():
    # Uma resposta inconsistente parecida com a de um modelo real:
    # intent não-analítico com operação residual.
    return AnalysisIntent.model_validate({
        "action": "defer", "operation": "maximo", "metric": None,
        "category": None, "category_source": "none",
    })


class ParseSimulator:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs["text_format"] is AnalysisIntent, (
            "O resultado não pode ser delegado à segunda LLM de resposta livre"
        )
        outcome = self.outcomes.pop(0)
        if outcome == "invalid":
            invalid_intent()
        if outcome == "timeout":
            raise TimeoutError("simulated timeout")
        return SimpleNamespace(output_parsed=parsed_intent())


def simulate(monkeypatch, outcomes):
    fake = ParseSimulator(outcomes)
    monkeypatch.setattr(chat_service, "_client", lambda: SimpleNamespace(responses=fake))
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    return fake


def test_first_parse_validation_error_then_retry_succeeds(monkeypatch, caplog):
    fake = simulate(monkeypatch, ["invalid", "ok"])
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        answer = chat_service.decidir_continuacao(request("Quem liderou a arrecadação?"))
    assert answer.origin == "deterministic"
    assert "Comercio" in answer.answer and "R$ 1.000,00" in answer.answer
    assert len(fake.calls) == 2
    assert fake.calls[0]["input"][0]["content"] != fake.calls[1]["input"][0]["content"]
    assert "a tentativa anterior não validou" in fake.calls[1]["input"][0]["content"]
    assert "analysis_planner_schema_invalid attempt=1" in caplog.text
    assert "input_value" not in caplog.text


def test_both_validation_errors_fail_closed_not_free_llm(monkeypatch):
    fake = simulate(monkeypatch, ["invalid", "invalid"])
    answer = chat_service.decidir_continuacao(request("Quem liderou a arrecadação?"))
    assert answer.action == "answer" and answer.origin == "deterministic"
    assert "não foi validada" in answer.answer
    assert "1.000" not in answer.answer
    assert len(fake.calls) == 2


def test_unexpected_exception_in_active_fails_closed(monkeypatch):
    fake = simulate(monkeypatch, ["timeout"])
    answer = chat_service.decidir_continuacao(request("Quem liderou a arrecadação?"))
    assert "Não foi possível validar" in answer.answer
    assert "1.000" not in answer.answer
    assert answer.origin == "deterministic"
    assert len(fake.calls) == 1


def test_active_failure_never_runs_old_parser_on_new_period(monkeypatch):
    fake = simulate(monkeypatch, ["timeout"])
    # O parser legado reconheceria 'quanto' como 'valor' dos dados anteriores.
    question = "Quanto foi arrecadado em outubro de 2026?"
    assert chat_service._op(request(question)) == "valor"
    answer = chat_service.decidir_continuacao(request(question))
    assert "Não foi possível validar" in answer.answer
    assert "R$ 1.000,00" not in answer.answer
    assert len(fake.calls) == 1


def test_shadow_failure_preserves_old_behavior(monkeypatch):
    fake = simulate(monkeypatch, ["timeout"])
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "shadow")
    answer = chat_service.decidir_continuacao(request("Qual segmento mais arrecadou?"))
    assert answer.origin == "deterministic"
    assert "R$ 1.000,00" in answer.answer
    assert len(fake.calls) == 1

