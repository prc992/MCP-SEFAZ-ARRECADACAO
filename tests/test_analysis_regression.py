"""Compara a etapa 1 com chat_service.py anterior, sem chamadas externas.

Se os módulos de integração não estiverem presentes, instala stubs *só para
os testes*. O projeto real continua dependente dos módulos originais.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import random
import sys
import types
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Ambiente de teste isolado quando o usuário disponibilizou somente chat_service.py.
if importlib.util.find_spec("schemas") is None:
    schemas = types.ModuleType("schemas")
    class QuerySpec(BaseModel):
        metric: str = "valor_arrecadado"
        group_by: str = "segmento"
        analysis_type: str = "aggregate"
        report_type: str = "standard"
        period_1_label: str | None = None
        period_2_label: str | None = None
    schemas.QuerySpec = QuerySpec
    sys.modules["schemas"] = schemas
if importlib.util.find_spec("llm_service") is None:
    llm = types.ModuleType("llm_service")
    llm._client = lambda: (_ for _ in ()).throw(AssertionError("LLM chamada no teste determinístico"))
    sys.modules["llm_service"] = llm
if importlib.util.find_spec("business_metadata") is None:
    meta = types.ModuleType("business_metadata")
    meta.BUSINESS_METADATA = "METADADOS DE TESTE"
    sys.modules["business_metadata"] = meta

import chat_service as novo
from analysis.engine import AnalysisEngine
from analysis.schemas import AnalysisSpec

spec_loader = importlib.util.spec_from_file_location("legacy_chat_service", ROOT / "tests" / "_legacy_chat_service.py")
antigo = importlib.util.module_from_spec(spec_loader)
spec_loader.loader.exec_module(antigo)


def qspec(*, group_by="segmento", metric="valor_arrecadado", analysis_type="aggregate", report_type="standard",
          period_1_label="jan/2026", period_2_label="fev/2026"):
    class QS(SimpleNamespace):
        def model_dump(self):
            return vars(self)
    return QS(group_by=group_by, metric=metric, analysis_type=analysis_type, report_type=report_type,
              period_1_label=period_1_label, period_2_label=period_2_label)


def req(mod, question, data, spec=None, history=None):
    return mod.ChatRequest.model_construct(question=question, previous_spec=spec or qspec(),
                                           previous_data=data, history=history or [])


def assert_same(question, rows, spec=None, history=None):
    v0 = antigo._responder_deterministico(req(antigo, question, rows, spec, history))
    v1 = novo._responder_deterministico(req(novo, question, rows, spec, history))
    assert v1 == v0, f"Diferença na resposta para: {question!r}: {v0!r} != {v1!r}"
    return v1


AGG = [
    {"segmento": "Comércio", "valor_arrecadado": 1000},
    {"segmento": "Indústria", "valor_arrecadado": 500},
    {"segmento": "Serviços", "valor_arrecadado": 200},
]
CMP = [
    {"segmento": "Comércio", "jan/2026": 100, "fev/2026": 150},
    {"segmento": "Indústria", "jan/2026": 50, "fev/2026": 100},
    {"segmento": "Serviços", "jan/2026": 500, "fev/2026": 300},
]


@pytest.mark.parametrize("question", [
    "Qual segmento mais arrecadou?", "Qual foi o menor valor?",
    "Qual a diferença entre o maior e o menor?", "Quanto arrecadou o Comércio?",
    "Quanto foi o valor?", "Os outros dois juntos superam o Comércio?",
    "Os demais dois juntos superam o Comércio?", "Qual a diferença de Comércio?",
    "Qual percentual de Comércio?", "Mostre outra consulta", "Qual o maior?",
    "Qual o menor?", "E em termos percentuais?",
])
def test_single_period_legacy_compat(question):
    assert_same(question, AGG)


@pytest.mark.parametrize("question", [
    "Qual segmento teve maior crescimento?",
    "Qual segmento teve menor crescimento?",
    "Qual segmento teve maior crescimento percentual?",
    "Qual segmento teve menor crescimento percentual?",
    "Qual foi a variação percentual de Comércio?",
    "Qual foi a variação de Comércio?",
    "Qual a diferença de Comércio?", "Qual o maior valor de Comércio?",
    "Qual o menor valor de Comércio?", "Quanto arrecadou Comércio?",
    "Qual o maior valor?", "Qual o menor valor?", "Quanto foi?",
    "E em termos percentuais?", "Qual o crescimento?",
])
def test_compare_periods_legacy_compat(question):
    assert_same(question, CMP, qspec(analysis_type="compare_periods"))


def test_history_follow_up_and_metric_priority():
    hist = [{"user": "Qual a variação do Comércio?", "assistant": "Comércio, arrecadação: diferença R$ 50,00"}]
    assert_same("E em termos percentuais?", CMP, qspec(analysis_type="compare_periods"), hist)
    rows = [
        {"decendio": "1 Decêndio", "icms_a": 1000, "fecop_b": 20},
        {"decendio": "2 Decêndio", "icms_a": 800, "fecop_b": 50},
    ]
    assert_same("Qual o maior ICMS?", rows, qspec(group_by="decendio", metric="icms_a", report_type="icms_fecop"))
    assert_same("Qual o maior FECOP?", rows, qspec(group_by="decendio", metric="icms_a", report_type="icms_fecop"))


def test_icms_fecop_long_format():
    rows = [
        {"decendio": "1 Decêndio", "periodo": "jan/2026", "icms_a": 100},
        {"decendio": "1 Decêndio", "periodo": "fev/2026", "icms_a": 125},
        {"decendio": "2 Decêndio", "periodo": "jan/2026", "icms_a": 50},
        {"decendio": "2 Decêndio", "periodo": "fev/2026", "icms_a": 70},
        {"decendio": "Total geral", "periodo": "jan/2026", "icms_a": 150},
        {"decendio": "Total geral", "periodo": "fev/2026", "icms_a": 195},
    ]
    spec = qspec(group_by="decendio", metric="icms_a", report_type="icms_fecop", analysis_type="compare_periods")
    for question in ("Qual o maior crescimento percentual?", "Qual o crescimento do primeiro decêndio?",
                     "Qual o valor do primeiro decêndio?", "Qual foi a variação percentual do 2º decêndio?"):
        assert_same(question, rows, spec)


@pytest.mark.parametrize("rows,spec", [
    ([], qspec()),
    ([{"segmento": "A", "valor_arrecadado": None}], qspec()),
    (AGG + [AGG[0]], qspec()),
    ([{"segmento": "A", "jan/2026": 0, "fev/2026": 100}], qspec(analysis_type="compare_periods")),
    ([{"segmento": "A", "jan/2026": 0, "fev/2026": 0}], qspec(analysis_type="compare_periods")),
    ([{"segmento": "A", "jan/2026": 100, "fev/2026": None}], qspec(analysis_type="compare_periods")),
    (AGG * 34, qspec()),  # 102 linhas: amostra potencialmente truncada
    ([{"segmento": "A", "valor_arrecadado": True}], qspec()),
])
def test_invalid_or_edge_cases(rows, spec):
    for question in ("Qual o maior?", "Qual a variação percentual de A?", "Quanto A arrecadou?", "Os outros dois juntos superam A?"):
        assert_same(question, rows, spec)


def test_exact_boundary_and_zero_reference():
    assert_same("Qual o maior?", AGG * 33 + AGG[:1], qspec())  # 100 linhas
    assert_same("Qual o maior?", AGG * 33 + AGG[:2], qspec())  # 101 linhas
    zero = [{"segmento": "A", "jan/2026": 0, "fev/2026": 10}]
    answer = assert_same("Qual a variação percentual de A?", zero, qspec(analysis_type="compare_periods"))
    assert "referência" in answer


def test_many_numeric_comparisons_match_baseline():
    rng = random.Random(42)
    qs = (
        "Qual o maior valor?", "Qual o menor valor?", "Qual a diferença entre o maior e o menor?",
        "Qual o maior crescimento?", "Qual o menor crescimento?",
        "Qual o maior crescimento percentual?", "Qual o menor crescimento percentual?",
        "Qual o crescimento de A?", "Qual a variação percentual de B?", "Quanto arrecadou C?",
    )
    for _ in range(100):
        rows = [{"segmento": label, "jan/2026": rng.randint(-200, 200), "fev/2026": rng.randint(-200, 200)}
                for label in ("A", "B", "C")]
        for question in qs:
            assert_same(question, rows, qspec(analysis_type="compare_periods"))


def test_engine_returns_structured_numeric_result():
    spec = AnalysisSpec(operation="crescimento_max_percentual", metric="valor_arrecadado", group_by="segmento",
                        analysis_type="compare_periods", report_type="standard",
                        period_1_label="jan/2026", period_2_label="fev/2026")
    result = AnalysisEngine().execute(spec, CMP)
    assert result.status == "ok"
    assert result.category == "Indústria"
    assert result.values["first"] == 50
    assert result.values["second"] == 100
    assert result.values["percent"] == 100


def test_chat_decision_contract_and_llm_fallback(monkeypatch):
    # O fluxo determinístico não chama a LLM.
    monkeypatch.setattr(novo, "_client", lambda: (_ for _ in ()).throw(AssertionError("LLM não deveria ser chamada")))
    result = novo.decidir_continuacao(req(novo, "Qual o maior valor?", AGG))
    assert result.action == "answer"
    assert "Comércio" in result.answer

    # A decisão de consulta nova continua passando pelo caminho original.
    class FakeResponses:
        def parse(self, **kwargs):
            return SimpleNamespace(output_parsed=novo.ChatDecision(action="query", query_spec=None))
    monkeypatch.setattr(novo, "_client", lambda: SimpleNamespace(responses=FakeResponses()))
    with pytest.raises(ValueError, match="sem QuerySpec"):
        novo.decidir_continuacao(req(novo, "Mostre outro mês", AGG))
