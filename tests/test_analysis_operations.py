from decimal import Decimal

from analysis.operations import (
    amplitude_values, extreme_period, period_changes, rank_values, sum_others,
)
from analysis.schemas import AnalysisSpec
from analysis.engine import AnalysisEngine


def test_operations_are_pure_and_reusable():
    source = {"a": Decimal("100"), "b": Decimal("50"), "c": Decimal("100")}
    assert rank_values(source) == "a"  # empate preserva a primeira
    assert rank_values(source, greatest=False) == "b"
    assert amplitude_values(source) == ("a", "b", Decimal("50"))
    assert sum_others(source, "a") == (Decimal("100"), Decimal("150"), Decimal("-50"))
    assert source == {"a": Decimal("100"), "b": Decimal("50"), "c": Decimal("100")}


def test_variations_and_baseline_zero():
    deltas, percentages = period_changes({
        "a": (Decimal("100"), Decimal("150")),
        "b": (Decimal("0"), Decimal("100")),
    })
    assert deltas == {"a": Decimal("50"), "b": Decimal("100")}
    assert percentages["a"] == Decimal("50")
    assert percentages["b"] is None
    assert extreme_period(Decimal(10), Decimal(10), "p1", "p2", greatest=True) == ("p2", Decimal(10))
    assert extreme_period(Decimal(10), Decimal(10), "p1", "p2", greatest=False) == ("p1", Decimal(10))


def test_engine_rejects_invalid_group_and_duplicated_data():
    invalid = AnalysisSpec(operation="maximo", metric="valor_arrecadado", group_by="not_supported",
                           analysis_type="aggregate", report_type="standard")
    assert AnalysisEngine().execute(invalid, [{"segmento": "A", "valor_arrecadado": 1}]).status == "invalid_data"

    compare = AnalysisSpec(operation="crescimento_max_percentual", metric="valor_arrecadado",
                           group_by="segmento", analysis_type="compare_periods", report_type="standard",
                           period_1_label="P1", period_2_label="P2")
    # Todas as bases zero impedem ranquear crescimento percentual.
    assert AnalysisEngine().execute(compare, [{"segmento": "A", "P1": 0, "P2": 10}]).status == "all_percent_references_zero"
    # Categoria duplicada, ainda que valores sejam idênticos, é ambígua.
    rows = [{"segmento": "A", "P1": 10, "P2": 20}]*2
    assert AnalysisEngine().execute(compare, rows).status == "invalid_data"


def test_engine_rejects_missing_or_duplicate_period_pairs():
    compare = AnalysisSpec(operation="crescimento_max_percentual", metric="icms_a",
                           group_by="decendio", analysis_type="compare_periods", report_type="icms_fecop",
                           period_1_label="P1", period_2_label="P2")
    incomplete = [{"decendio": "1 Decêndio", "periodo": "P1", "icms_a": 100}]
    assert AnalysisEngine().execute(compare, incomplete).status == "invalid_data"
    duplicate = [
        {"decendio": "1 Decêndio", "periodo": "P1", "icms_a": 100},
        {"decendio": "1 Decêndio", "periodo": "P1", "icms_a": 100},
        {"decendio": "1 Decêndio", "periodo": "P2", "icms_a": 130},
    ]
    assert AnalysisEngine().execute(compare, duplicate).status == "invalid_data"


def test_zero_rows_and_row_truncation():
    spec = AnalysisSpec(operation="maximo", metric="valor_arrecadado", group_by="segmento",
                        analysis_type="aggregate", report_type="standard")
    assert AnalysisEngine().execute(spec, []).status == "invalid_data"
    many = [{"segmento": "A", "valor_arrecadado": 1}] * 101
    assert AnalysisEngine().execute(spec, many).status == "too_many_rows"
