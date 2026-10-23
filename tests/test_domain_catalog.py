"""Etapa 3: domínio SEFAZ preservado e núcleo reutilizável em outro MCP."""
from decimal import Decimal
from types import SimpleNamespace
import json

from analysis.domain import DomainCatalog, MetricDefinition
from analysis.engine import AnalysisEngine, metricas_disponiveis
from analysis.formatter import format_analysis_result
from analysis.planner import AnalysisPlanner, AnalysisIntent
from analysis.schemas import AnalysisSpec
from analysis.validator import AnalysisPlanValidator, _explicit_scope_change
from domains.sefaz.catalog import SEFAZ_CATALOG


HOSPITAL = DomainCatalog(
    id="hospital_demo",
    metrics={
        "atendimentos": MetricDefinition("atendimentos", ("consultas", "atendimentos"), unit="count"),
        "tempo_medio": MetricDefinition("tempo médio de espera", ("espera",), unit="number"),
    },
    dimensions=("hospital", "especialidade", "mes"),
    metric_priority=("tempo_medio", "atendimentos"),
    derived_numeric_fields=frozenset({"posicao", "dif"}),
    total_row_field="hospital",
    total_row_label="TOTAL",
    period_field="periodo_nome",
    long_comparison_reports=frozenset({"mensal_long"}),
    dimension_aliases={"hospital": ("unidade", "unidades"), "especialidade": ("tipo de atendimento",)},
    metric_question="Qual indicador hospitalar deseja analisar?",
    metric_prompt="A rede hospitalar reporta atendimentos e tempo de espera.",
)


def spec(operation="maximo", metric="atendimentos", group_by="hospital", analysis_type="aggregate",
         report_type="standard", **kwargs):
    return AnalysisSpec(operation=operation, metric=metric, group_by=group_by,
                        analysis_type=analysis_type, report_type=report_type, **kwargs)


def ctx(**kwargs):
    defaults = dict(group_by="hospital", analysis_type="aggregate", report_type="standard",
                    metric="atendimentos", period_1_label=None, period_2_label=None,
                    start_date="2026-09-01", end_date="2026-09-30", period_1_start=None,
                    period_1_end=None, period_2_start=None, period_2_end=None, top_n=None)
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def req(question, rows, previous_spec=None, history=None):
    return SimpleNamespace(question=question, previous_data=rows,
                           previous_spec=previous_spec or ctx(), history=history or [])


class FakeResponse:
    def __init__(self, returned):
        self.returned = returned
        self.calls = []

    def parse(self, **params):
        self.calls.append(params)
        return SimpleNamespace(output_parsed=self.returned)


def test_catalogue_is_immutable_by_dataclass_and_can_be_injected():
    from dataclasses import FrozenInstanceError
    import pytest
    with pytest.raises(TypeError):
        HOSPITAL.metrics["atendimentos"] = MetricDefinition("mudança proibida")
    with pytest.raises(FrozenInstanceError):
        HOSPITAL.currency_symbol = "$"
    assert SEFAZ_CATALOG.id == "sefaz_ce_arrecadacao"
    assert HOSPITAL.id != SEFAZ_CATALOG.id
    assert "hospital" not in SEFAZ_CATALOG.dimensions
    assert "segmento" not in HOSPITAL.dimensions
    assert HOSPITAL.label("tempo_medio") == "tempo médio de espera"
    assert HOSPITAL.unit("tempo_medio") == "number"


def test_metric_names_and_units_are_outside_formatter():
    lines = [{"hospital": "Unidade A", "atendimentos": 100},
             {"hospital": "Unidade B", "atendimentos": 240},
             {"hospital": "TOTAL", "atendimentos": 340}]
    result = AnalysisEngine(HOSPITAL).execute(spec(), lines)
    assert result.status == "ok" and result.category == "Unidade B"
    message = format_analysis_result(result, HOSPITAL)
    assert message == "Unidade B apresentou o maior valor de atendimentos: 240."
    assert "R$" not in message
    assert result.values["value"] == Decimal("240")


def test_non_monetary_decimal_measure_has_no_currency():
    lines = [{"hospital": "A", "tempo_medio": 23.75}, {"hospital": "B", "tempo_medio": 14.25}]
    result = AnalysisEngine(catalog=HOSPITAL).execute(spec(metric="tempo_medio", operation="minimo"), lines)
    assert format_analysis_result(result, HOSPITAL) == "B apresentou o menor valor de tempo médio de espera: 14,25."


def test_comparison_wide_and_zero_reference_are_shared():
    lines = [{"hospital": "A", "p1": 10, "p2": 15}, {"hospital": "B", "p1": 10, "p2": 20}]
    s = spec(operation="crescimento_max_percentual", analysis_type="compare_periods",
             period_1_label="p1", period_2_label="p2")
    result = AnalysisEngine(HOSPITAL).execute(s, lines)
    assert result.category == "B" and result.values["percent"] == Decimal("100")
    assert "100,00%" in format_analysis_result(result, HOSPITAL)
    lines[0]["p1"] = 0
    lines[1]["p1"] = 0
    result = AnalysisEngine(HOSPITAL).execute(s, lines)
    assert result.status == "all_percent_references_zero"


def test_long_comparison_uses_report_and_period_field_from_catalogue():
    lines = [
        {"hospital": "A", "periodo_nome": "P1", "atendimentos": 15},
        {"hospital": "A", "periodo_nome": "P2", "atendimentos": 25},
        {"hospital": "B", "periodo_nome": "P1", "atendimentos": 20},
        {"hospital": "B", "periodo_nome": "P2", "atendimentos": 25},
    ]
    s = spec(operation="crescimento_max", analysis_type="compare_periods", report_type="mensal_long",
             period_1_label="P1", period_2_label="P2")
    result = AnalysisEngine(HOSPITAL).execute(s, lines)
    assert result.category == "A" and result.values["difference"] == 10
    assert metricas_disponiveis(lines, ctx(analysis_type="compare_periods", report_type="mensal_long"), HOSPITAL) == {"atendimentos"}


def test_metric_detection_in_wide_comparison_and_exclusions():
    rows = [{"hospital": "A", "p1": 2, "p2": 3, "posicao": 8}]
    found = metricas_disponiveis(rows, ctx(analysis_type="compare_periods", metric="atendimentos", period_1_label="p1", period_2_label="p2"), HOSPITAL)
    assert found == {"atendimentos"}
    assert "posicao" not in found


def test_validator_is_domain_specific_and_reuses_math_spec():
    row = [{"hospital": "Unidade Norte", "atendimentos": 10}, {"hospital": "Unidade Sul", "atendimentos": 20}]
    i = AnalysisIntent(action="analyze", operation="valor", metric="atendimentos",
                       category="unidade sul", category_source="current")
    verdict = AnalysisPlanValidator(HOSPITAL).validate(req("Quantos atendimentos houve na Unidade Sul?", row), i,
                                                     {"atendimentos"}, ["Unidade Norte", "Unidade Sul"])
    assert verdict.action == "analyze" and verdict.spec.category == "Unidade Sul"
    assert AnalysisEngine(HOSPITAL).execute(verdict.spec, row).values["value"] == 20


def test_other_domain_dimension_alias_triggers_only_new_group():
    query = ctx()
    assert _explicit_scope_change("Mostre dados por especialidade", query, HOSPITAL)
    assert not _explicit_scope_change("Qual unidade liderou?", query, HOSPITAL)
    assert HOSPITAL.dimension_from_phrase("unidade") == "hospital"


def test_planner_uses_custom_catalogue_and_no_fiscal_description():
    rows = [{"hospital": "Unidade A", "atendimentos": 100}, {"hospital": "Unidade B", "atendimentos": 200}]
    response = FakeResponse(AnalysisIntent(action="analyze", operation="maximo", metric=None,
                                           category=None, category_source="none"))
    result = AnalysisPlanner(client_factory=lambda: SimpleNamespace(responses=response), catalog=HOSPITAL).plan(
        req("Qual hospital teve mais atendimentos?", rows))
    assert result.action == "analyze"
    assert result.spec.group_by == "hospital"
    assert result.spec.metric is None
    system = response.calls[0]["input"][0]["content"]
    assert "tempo médio de espera" in system
    assert "FECOP" not in system and "ICMS" not in system
    payload = json.loads(response.calls[0]["input"][1]["content"])
    assert payload["dominio"] == "hospital_demo"
    assert payload["metricas_disponiveis"] == ["atendimentos"]
    assert "atendimentos" not in str(payload["categorias_disponiveis"])
    assert "200" not in str(payload)


def test_two_catalogues_do_not_leak_configuration():
    sefaz = AnalysisEngine(SEFAZ_CATALOG)
    hospital = AnalysisEngine(HOSPITAL)
    data = [{"hospital": "A", "atendimentos": 5}, {"hospital": "B", "atendimentos": 10}]
    assert sefaz.execute(spec(), data).status == "invalid_data"
    assert hospital.execute(spec(), data).status == "ok"
    assert sefaz.execute(spec(), data).status == "invalid_data"


def test_sefaz_report_rules_retained_in_catalogue():
    assert SEFAZ_CATALOG.is_long_comparison("icms_fecop")
    assert not SEFAZ_CATALOG.is_long_comparison("standard")
    assert SEFAZ_CATALOG.remap_metric("icms_a", "standard") == "valor_arrecadado"
    assert SEFAZ_CATALOG.display_category("2 Decêndio") == "2º decêndio"
    assert SEFAZ_CATALOG.mentions_category("2 Decêndio", "segundo decêndio de setembro")
    assert SEFAZ_CATALOG.metric_question.startswith("Qual indicador")
