"""Regressões de variações temporais sem LLM e sem Redshift."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from analysis.engine import AnalysisEngine
from analysis.formatter import format_analysis_result
from analysis.operations import consecutive_changes
from analysis.validator import AnalysisPlanValidator
from analysis.schemas import AnalysisSpec
from domains.sefaz.catalog import SEFAZ_CATALOG
from schemas import QuerySpec

ROWS = [
    {"mes": "2026-05", "valor_arrecadado": 100},
    {"mes": "2026-06", "valor_arrecadado": 150},
    {"mes": "2026-07", "valor_arrecadado": 120},
    {"mes": "2026-08", "valor_arrecadado": 110},
    {"mes": "2026-09", "valor_arrecadado": 160},
    {"mes": "2026-10", "valor_arrecadado": 80},
]


def req(question, rows=None, group_by="mes"):
    spec = QuerySpec(metric="valor_arrecadado", group_by=group_by,
                     analysis_type="time_series", chart_type="line",
                     start_date="2026-05-01", end_date="2026-10-31")
    return SimpleNamespace(question=question, previous_spec=spec,
                           previous_data=ROWS if rows is None else rows, history=[])


def compute(question, rows=None, group_by="mes"):
    request = req(question, rows, group_by)
    rows = request.previous_data
    verdict = AnalysisPlanValidator(SEFAZ_CATALOG).classify_consecutive(
        request, {"valor_arrecadado"}, [str(r[group_by]) for r in rows])
    assert verdict and verdict.action == "analyze", question
    result = AnalysisEngine(SEFAZ_CATALOG).execute(verdict.spec, rows)
    return result


def test_regression_original_question():
    result = compute("qual mes teve a maior queda na arrecadacao?")
    assert result.status == "ok"
    assert result.spec.operation == "maior_queda_consecutiva"
    assert (result.counterpart, result.category) == ("2026-09", "2026-10")
    assert result.values["difference"] == Decimal("-80")
    assert "-50,00%" in format_analysis_result(result, SEFAZ_CATALOG)


def test_absolute_and_percentual_not_conflated():
    rows = [{"mes": "2026-05", "valor_arrecadado": 1000},
            {"mes": "2026-06", "valor_arrecadado": 700},
            {"mes": "2026-07", "valor_arrecadado": 600},
            {"mes": "2026-08", "valor_arrecadado": 350}]
    a = compute("qual foi a maior queda na arrecadação?", rows)
    p = compute("qual foi a maior queda percentual?", rows)
    assert (a.counterpart, a.category) == ("2026-05", "2026-06")
    assert (p.counterpart, p.category) == ("2026-07", "2026-08")


def test_biggest_increase():
    result = compute("Em qual mês houve o maior crescimento?")
    assert (result.counterpart, result.category) == ("2026-05", "2026-06")
    assert result.values["difference"] == 50


def test_direct_pair_and_all_monthly_changes():
    result = compute("quanto cresceu de agosto para setembro?")
    assert result.spec.operation == "variacao_entre_periodos"
    assert (result.counterpart, result.category) == ("2026-08", "2026-09")
    assert result.values["difference"] == 50
    entire = compute("como variou a arrecadação mês a mês?")
    assert entire.spec.operation == "variacao_consecutiva"
    assert len(entire.series) == 5
    assert "2026-05 → 2026-06" in format_analysis_result(entire, SEFAZ_CATALOG)


def test_unsorted_and_gaps():
    reordered = list(reversed(ROWS))
    assert compute("qual foi a maior queda?", reordered).category == "2026-10"
    gap = ROWS[:2] + ROWS[3:]
    assert compute("qual foi a maior queda?", gap).status == "nonconsecutive_periods"


def test_duplicate_and_null_are_invalid():
    assert compute("qual foi a maior queda?", ROWS + [ROWS[0]]).status == "invalid_data"
    missing = [dict(row) for row in ROWS]
    missing[2]["valor_arrecadado"] = None
    assert compute("qual foi a maior queda?", missing).status == "invalid_data"


def test_zero_percentage_and_no_fall():
    zero = [{"mes": "2026-01", "valor_arrecadado": 0},
            {"mes": "2026-02", "valor_arrecadado": 0},
            {"mes": "2026-03", "valor_arrecadado": 0}]
    assert compute("qual a maior queda percentual?", zero).status == "all_percent_references_zero"
    assert compute("qual foi a maior queda?", zero).status == "no_matching_change"


def test_incomplete_current_month_excluded():
    today = date.today()
    current = today.strftime("%Y-%m")
    prev_key = today.year*12+today.month-2
    before_key = prev_key-1
    def month(key):
        return f"{key//12:04d}-{key%12+1:02d}"
    data = [{"mes": month(before_key), "valor_arrecadado": 200},
            {"mes": month(prev_key), "valor_arrecadado": 160},
            {"mes": current, "valor_arrecadado": 10}]
    r = compute("qual foi a maior queda?", data)
    assert r.status == "ok"
    assert r.category == month(prev_key)
    assert r.values['partial_excluded'] == 1
    assert "parcial" in format_analysis_result(r, SEFAZ_CATALOG)
    assert compute("qual a maior queda?", data[1:]).status == "incomplete_current_period"


def test_context_not_series_and_too_many_rows():
    request = req("qual foi a maior queda?", group_by="segmento")
    assert AnalysisPlanValidator(SEFAZ_CATALOG).classify_consecutive(
        request, {"valor_arrecadado"}, ["a", "b"]) is None
    spec = AnalysisSpec(operation="maior_queda_consecutiva", metric="valor_arrecadado",
                        group_by="mes", analysis_type="time_series", report_type="standard")
    assert AnalysisEngine(SEFAZ_CATALOG).execute(spec, ROWS*20).status == "too_many_rows"


def test_daily_series():
    data = [{"data_pagamento": "2026-09-10", "valor_arrecadado": 400},
            {"data_pagamento": "2026-09-11", "valor_arrecadado": 200},
            {"data_pagamento": "2026-09-12", "valor_arrecadado": 240}]
    r = compute("qual dia teve a maior queda em relação ao anterior?", data, "data_pagamento")
    assert r.status == "ok" and r.category == "2026-09-11"


def test_no_guess_across_years():
    data = [{"mes": "2025-08", "valor_arrecadado": 10},
            {"mes": "2025-09", "valor_arrecadado": 20},
            {"mes": "2026-08", "valor_arrecadado": 30},
            {"mes": "2026-09", "valor_arrecadado": 40}]
    request = req("quanto cresceu de agosto para setembro?", data)
    assert AnalysisPlanValidator(SEFAZ_CATALOG).classify_consecutive(
        request, {"valor_arrecadado"}, [r["mes"] for r in data]) is None

@pytest.mark.parametrize("mode", ["legacy", "shadow", "active"])
def test_chat_modes_answer_original_without_llm(monkeypatch, mode):
    import chat_service
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", mode)
    monkeypatch.setattr(chat_service, "_client", lambda: (_ for _ in ()).throw(AssertionError("LLM não deve calcular")))
    r = req("qual mes teve a maior queda na arrecadacao?")
    request = chat_service.ChatRequest(question=r.question, previous_spec=r.previous_spec,
                                       previous_data=r.previous_data, history=[])
    decision = chat_service.decidir_continuacao(request)
    assert decision.action == "answer"
    assert decision.origin == "deterministic"
    assert "2026-09 para 2026-10" in decision.answer
    assert "R$ -80,00" in decision.answer


def test_legacy_unrelated_segment_question_unchanged(monkeypatch):
    import chat_service
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "legacy")
    spec = QuerySpec(metric="valor_arrecadado", group_by="segmento", analysis_type="aggregate")
    request = chat_service.ChatRequest(question="Qual segmento mais arrecadou?", previous_spec=spec,
        previous_data=[{"segmento": "A", "valor_arrecadado": 20}, {"segmento": "B", "valor_arrecadado": 30}])
    decision = chat_service.decidir_continuacao(request)
    assert decision.action == "answer" and "B" in decision.answer


def test_new_dimension_is_not_silently_reused():
    request = req("qual segmento teve a maior queda na arrecadação por segmento?")
    verdict = AnalysisPlanValidator(SEFAZ_CATALOG).classify_consecutive(
        request, {"valor_arrecadado"}, [r["mes"] for r in request.previous_data])
    assert verdict is None


def test_direct_comparison_with_partial_current_month_is_not_consolidated():
    today = date.today()
    current_key = today.year * 12 + today.month - 1
    def month(key):
        return f"{key//12:04d}-{key%12+1:02d}"
    prev = month(current_key-1)
    current = month(current_key)
    data = [{"mes": prev, "valor_arrecadado": 300},
            {"mes": current, "valor_arrecadado": 20}]
    operation = AnalysisSpec(operation="variacao_entre_periodos", metric="valor_arrecadado",
                             group_by="mes", analysis_type="time_series", report_type="standard",
                             from_period=prev, to_period=current)
    result = AnalysisEngine(SEFAZ_CATALOG).execute(operation, data)
    assert result.status == "incomplete_current_period"


def test_direct_pair_respects_requested_order():
    r = compute("quanto variou de setembro para agosto?")
    assert r.status == "ok"
    assert (r.counterpart, r.category) == ("2026-09", "2026-08")
    assert r.values["difference"] == -50
    assert r.values["percent"] == Decimal("-31.25")
