"""Regressões reais do Playground (Baterias 2 e 3, outubro de 2026).

Todas as respostas da LLM são simuladas. Só o AnalysisEngine processa valores.
"""
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import chat_service
from schemas import QuerySpec
from analysis.planner import AnalysisIntent, AnalysisPlanner
from analysis.validator import AnalysisPlanValidator
from domains.sefaz.catalog import SEFAZ_CATALOG


SINGLE = [
    {"decendio": "1 Decêndio", "valor_arrecadado": 669426239.32},
    {"decendio": "2 Decêndio", "valor_arrecadado": 1073295618.89},
    {"decendio": "3 Decêndio", "valor_arrecadado": 369788046.14},
    {"decendio": "Total geral", "valor_arrecadado": 2112509904.35},
]
COMPARE = [
    {"decendio": "1 Decêndio", "agosto_2026": 720562041.10, "setembro_2026": 669426239.32},
    {"decendio": "2 Decêndio", "agosto_2026": 1051682595.60, "setembro_2026": 1073295618.89},
    {"decendio": "3 Decêndio", "agosto_2026": 2527509083.92, "setembro_2026": 369788046.14},
]


def req(question, *, compare=False, history=None, rows=None):
    if compare:
        query_spec = QuerySpec(
            metric="valor_arrecadado", group_by="decendio", subgrupo="ICMS",
            analysis_type="compare_periods", period_1_label="agosto_2026",
            period_2_label="setembro_2026", period_1_start="2026-08-01",
            period_1_end="2026-08-31", period_2_start="2026-09-01",
            period_2_end="2026-09-30", top_n=None,
        )
    else:
        query_spec = QuerySpec(
            metric="valor_arrecadado", group_by="decendio", subgrupo="ICMS",
            start_date="2026-09-01", end_date="2026-09-30", top_n=None,
        )
    return chat_service.ChatRequest(
        question=question, previous_spec=query_spec,
        previous_data=rows if rows is not None else (COMPARE if compare else SINGLE),
        history=history or [],
    )


def ai(action="analyze", operation="valor", category=None, source="none"):
    if action != "analyze":
        return AnalysisIntent(action=action, operation=None, metric=None, category=None, category_source="none")
    return AnalysisIntent(action="analyze", operation=operation, metric=None,
                          category=category, category_source=source)


def bad_schema():
    return lambda: AnalysisIntent(
        action="query", operation="valor", metric=None,
        category=None, category_source="none",
    )


class MockResponses:
    def __init__(self, *intent_results):
        self.script = list(intent_results)
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs["text_format"] is AnalysisIntent
        item = self.script.pop(0)
        if callable(item):
            item = item()
        return SimpleNamespace(output_parsed=item)


def respond(monkeypatch, request, *planned):
    fake = MockResponses(*planned)
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    monkeypatch.setattr(chat_service, "_client", lambda: SimpleNamespace(responses=fake))
    result = chat_service.decidir_continuacao(request)
    return result, fake


def test_bateria2_valor_decendio_nao_exige_nova_consulta(monkeypatch):
    result, fake = respond(monkeypatch, req("Quanto foi arrecadado no segundo decêndio?"),
                           ai("query"), ai("query"))
    assert result.action == "answer" and result.origin == "deterministic"
    assert result.answer == "2º decêndio: arrecadação = R$ 1.073.295.618,89."
    assert len(fake.calls) == 2


def test_bateria2_valor_decendio_atual_prevalece_contexto_errado(monkeypatch):
    history = [{"user": "Qual teve o menor valor?", "assistant": "3º decêndio apresentou o menor."}]
    result, _ = respond(monkeypatch, req("Quanto foi arrecadado no segundo decêndio?", history=history),
                        ai(category="3 Decêndio", source="previous"))
    assert "2º decêndio: arrecadação = R$ 1.073.295.618,89." == result.answer


def test_bateria2_amplitude_recuperada_apos_erro_estruturado(monkeypatch):
    result, fake = respond(monkeypatch, req("Qual a diferença entre o maior e o menor decêndio?"),
                           bad_schema(), bad_schema())
    assert result.origin == "deterministic"
    assert "R$ 703.507.572,75" in result.answer
    assert "2º decêndio" in result.answer
    assert "3º decêndio" in result.answer
    assert len(fake.calls) == 2


def test_bateria2_amplitude_com_prefixo_numerado(monkeypatch):
    result, _ = respond(monkeypatch, req("1. Qual a diferença entre o maior e o menor decêndio?"),
                        bad_schema(), bad_schema())
    assert "R$ 703.507.572,75" in result.answer


@pytest.mark.parametrize("question,category,expected", [
    ("E em termos percentuais?", "2 Decêndio", "2,06%"),
    ("E em porcentagem?", "3 Decêndio", "-85,37%"),
])
def test_bateria3_elipse_resolve_ultima_categoria_mesmo_se_planner_errar_source(
        monkeypatch, question, category, expected):
    ordinal = "2º" if category.startswith("2") else "3º"
    desc = "segundo" if category.startswith("2") else "terceiro"
    history = [{"user": f"Qual foi a diferença de arrecadação do {desc} decêndio?",
                "assistant": f"{ordinal} decêndio, arrecadação, agosto_2026 → setembro_2026"}]
    result, fake = respond(monkeypatch, req(question, compare=True, history=history),
                           ai(operation="variacao_percentual", category=category, source="current"))
    assert result.origin == "deterministic"
    assert f"{ordinal} decêndio" in result.answer
    assert expected in result.answer
    assert len(fake.calls) == 1


def test_bateria3_elipse_recuperada_de_duas_classificacoes_query(monkeypatch):
    history = [{"user": "Qual foi a diferença de arrecadação do segundo decêndio?",
                "assistant": "2º decêndio, arrecadação: diferença R$ 21.613.023,29."}]
    result, fake = respond(monkeypatch, req("E em termos percentuais?", compare=True, history=history),
                           ai("query"), ai("query"))
    assert "2º decêndio" in result.answer and "2,06%" in result.answer
    assert len(fake.calls) == 2


def test_bateria3_sem_referente_unico_permanece_ambigua(monkeypatch):
    history = [{"user": "Compare o primeiro e o segundo decêndio",
                "assistant": "1º decêndio e 2º decêndio"}]
    result, fake = respond(monkeypatch, req("E em termos percentuais?", compare=True, history=history),
                           ai(operation="variacao_percentual", category="2 Decêndio", source="previous"))
    assert "mais de uma categoria" in result.answer
    assert "R$" not in result.answer
    assert len(fake.calls) == 1


def test_novo_mes_continua_query_sem_recuperacao_de_valor():
    request = req("Quanto foi arrecadado no segundo decêndio de outubro de 2026?")
    verdict = AnalysisPlanValidator(SEFAZ_CATALOG).recover_unambiguous(
        request, {"valor_arrecadado"}, ["1 Decêndio", "2 Decêndio", "3 Decêndio"])
    assert verdict is None


def test_categoria_ausente_nao_e_inventada():
    request = req("Quanto foi arrecadado no quarto decêndio?")
    verdict = AnalysisPlanValidator(SEFAZ_CATALOG).recover_unambiguous(
        request, {"valor_arrecadado"}, ["1 Decêndio", "2 Decêndio", "3 Decêndio"])
    assert verdict is None


def test_core_math_still_untouched():
    import hashlib
    from pathlib import Path
    baseline = Path(__file__).resolve().parents[2] / "etapa3_domain_work" / "analysis" / "operations.py"
    local = Path(__file__).resolve().parents[1] / "analysis" / "operations.py"
    # A comparação fica opcional para os testes instalados fora deste workspace.
    if baseline.exists():
        assert hashlib.sha256(baseline.read_bytes()).digest() == hashlib.sha256(local.read_bytes()).digest()


def test_bateria2_amplitude_corrige_operacao_proxima_sem_mudar_calculo(monkeypatch):
    result, fake = respond(monkeypatch, req("Qual a diferença entre o maior e o menor decêndio?"),
                           ai(operation="diferenca"))
    assert "R$ 703.507.572,75" in result.answer
    assert len(fake.calls) == 1


def test_bateria2_resposta_a_esclarecimento_recupera_pedido_antecedente(monkeypatch):
    history = [{"user": "Quanto foi arrecadado no segundo decêndio?",
                "assistant": "Você quer analisar os dados já exibidos ou fazer uma nova consulta com outro recorte?"}]
    result, fake = respond(monkeypatch, req("nos dados já exibidos", history=history),
                           ai("query"), ai("query"))
    assert result.answer == "2º decêndio: arrecadação = R$ 1.073.295.618,89."
    assert len(fake.calls) == 2


def test_confirmacao_de_escopo_sem_pedido_antecedente_nao_recupera_valor():
    history = [{"user": "Mostre os dados de novembro",
                "assistant": "Você quer analisar os dados já exibidos ou fazer uma nova consulta com outro recorte?"}]
    verdict = AnalysisPlanValidator(SEFAZ_CATALOG).recover_unambiguous(
        req("nos dados já exibidos", history=history), {"valor_arrecadado"},
        ["1 Decêndio", "2 Decêndio", "3 Decêndio"])
    assert verdict is None
