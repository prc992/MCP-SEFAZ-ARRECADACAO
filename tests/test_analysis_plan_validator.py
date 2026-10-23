"""Etapa 2.1 — cenários com decisões inconsistentes e histórico variável.

Todos os planejamentos da LLM são mocks: nenhuma chave de API, Redshift ou rede.
"""
from types import SimpleNamespace
import logging

import pytest

import chat_service
from analysis.planner import AnalysisIntent
from analysis.validator import AnalysisPlanValidator
from schemas import QuerySpec


def spec(group_by="segmento", analysis_type="aggregate"):
    kwargs = dict(metric="valor_arrecadado", group_by=group_by, analysis_type=analysis_type)
    if analysis_type == "aggregate":
        kwargs.update(start_date="2026-04-01", end_date="2026-04-30")
    else:
        kwargs.update(period_1_start="2026-08-01", period_1_end="2026-08-31",
                      period_2_start="2026-09-01", period_2_end="2026-09-30",
                      period_1_label="agosto_2026", period_2_label="setembro_2026")
    return QuerySpec(**kwargs)


DATA = [
    {"segmento": "COMERCIO ATACADISTA     ", "valor_arrecadado": 515690316.44},
    {"segmento": "INDUSTRIA", "valor_arrecadado": 12993333.01},
    {"segmento": "SERVICOS", "valor_arrecadado": 31020000.00},
]
COMPARE = [
    {"segmento": "Comércio", "agosto_2026": 100, "setembro_2026": 200},
    {"segmento": "Indústria", "agosto_2026": 50, "setembro_2026": 75},
]


def request(question, *, history=None, data=DATA, context=None):
    return chat_service.ChatRequest(question=question, previous_spec=context or spec(),
                                    previous_data=data, history=history or [])


def intent(action="analyze", op="maximo", metric=None, category=None, source="none"):
    if action != "analyze":
        return AnalysisIntent(action=action, operation=None, metric=None, category=None, category_source="none")
    return AnalysisIntent(action="analyze", operation=op, metric=metric,
                          category=category, category_source=source)


class Scripted:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs["text_format"] is AnalysisIntent, "Deve ficar na rota estruturada"
        return SimpleNamespace(output_parsed=self.responses.pop(0))


def route(monkeypatch, req, *answers):
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    fake = Scripted(*answers)
    monkeypatch.setattr(chat_service, "_client", lambda: SimpleNamespace(responses=fake))
    return chat_service.decidir_continuacao(req), fake


def test_ranking_global_ignora_categoria_alucinada_e_limpa_espacos(monkeypatch):
    result, fake = route(monkeypatch, request("Qual setor ficou na primeira posição?"),
                         intent(category="setor", source="current"))
    assert result.origin == "deterministic"
    assert result.answer == ("COMERCIO ATACADISTA apresentou o maior valor de arrecadação: "
                             "R$ 515.690.316,44.")
    assert len(fake.calls) == 1


@pytest.mark.parametrize("question", [
    "Qual segmento mais arrecadou?",
    "Qual segmento arrecadou mais?",
    "Quem liderou a arrecadação?",
    "Qual setor ficou na primeira posição?",
    "Qual segmento ficou na primeira posição?",
])
def test_mesmo_ranking_nao_dependente_do_historico(monkeypatch, question):
    histories = [[],
        [{"user": "E a indústria?", "assistant": "INDUSTRIA arrecadou R$ 12.993.333,01"}],
        [{"user": "Mostre outra coisa", "assistant": "Tentativa de alterar o contexto"}],
    ]
    for history in histories:
        # Deliberadamente variaremos o comportamento da LLM estruturada.
        # Tanto um plano correto quanto uma categoria espúria deverão produzir
        # a mesma resposta ao ranking global, sem conteúdo numérico da LLM.
        result, _ = route(monkeypatch, request(question, history=history),
                          intent(category="INDUSTRIA", source="previous"))
        assert result.origin == "deterministic"
        assert "COMERCIO ATACADISTA apresentou" in result.answer
        assert "R$ 515.690.316,44" in result.answer


def test_query_falso_positivo_apos_nova_classificacao_recupera_ranking(monkeypatch):
    result, fake = route(monkeypatch, request("Qual segmento ficou na primeira posição?"),
                         intent("query"), intent())
    assert result.origin == "deterministic"
    assert "COMERCIO ATACADISTA" in result.answer
    assert len(fake.calls) == 2
    assert "query_without_scope_evidence" in fake.calls[1]["input"][0]["content"]


def test_query_sem_evidencia_em_duas_tentativas_pede_esclarecimento(monkeypatch):
    result, fake = route(monkeypatch, request("Qual setor ficou na primeira posição?"),
                         intent("query"), intent("query"))
    assert result.origin == "deterministic" and result.action == "answer"
    assert "dados já exibidos ou fazer uma nova consulta" in result.answer
    assert "515.690.316" not in result.answer
    assert len(fake.calls) == 2


def test_defer_indevido_reclassificado_para_operacao(monkeypatch):
    result, fake = route(monkeypatch, request("Quem liderou a arrecadação?"),
                         intent("defer"), intent())
    assert "COMERCIO ATACADISTA" in result.answer
    assert len(fake.calls) == 2


def test_defer_indevido_persistente_pede_esclarecimento_sem_llm_livre(monkeypatch):
    result, fake = route(monkeypatch, request("Quem ficou em primeiro?"),
                         intent("defer"), intent("defer"))
    assert result.origin == "deterministic"
    assert "cálculo sobre a tabela" in result.answer
    assert "R$" not in result.answer
    assert len(fake.calls) == 2


def test_referencia_explicita_atual_prevalece_sobre_ultima_interacao(monkeypatch):
    req = request("Quanto foi arrecadado na Indústria?",
                  data=COMPARE, context=spec(analysis_type="compare_periods"),
                  history=[{"user": "Quanto teve o Comércio?", "assistant": "Comércio = 100"}])
    result, _ = route(monkeypatch, req, intent(op="valor", category="Comércio", source="previous"))
    assert "Indústria:" in result.answer
    assert "R$ 50,00" in result.answer and "R$ 75,00" in result.answer
    assert "Comércio:" not in result.answer


def test_referencia_da_ultima_troca_sem_citar_categoria_usa_ultima(monkeypatch):
    req = request("E percentual?", data=COMPARE,
                  context=spec(analysis_type="compare_periods"),
                  history=[{"user": "Qual a variação do Comércio?", "assistant": "Comércio = R$ 100,00"}])
    result, _ = route(monkeypatch, req, intent(op="variacao_percentual", category="Comércio", source="previous"))
    assert "Comércio," in result.answer and "100,00%" in result.answer


def test_uma_categoria_explicita_desambiguada_mesmo_se_planner_omitir(monkeypatch):
    req = request("Qual foi a variação percentual da Indústria?", data=COMPARE,
                  context=spec(analysis_type="compare_periods"))
    result, _ = route(monkeypatch, req, intent(op="variacao_percentual"))
    assert "Indústria," in result.answer and "50,00%" in result.answer


def test_duas_categorias_em_operacao_unitaria_gera_pergunta(monkeypatch):
    req = request("Quanto arrecadaram Comércio e Indústria?", data=COMPARE,
                  context=spec(analysis_type="compare_periods"))
    result, _ = route(monkeypatch, req, intent(op="valor", category="Comércio", source="current"))
    assert result.origin == "deterministic"
    assert "mais de uma categoria" in result.answer
    assert "R$" not in result.answer


def test_ranking_de_uma_categoria_explicita_nao_pode_ignorar_escopo(monkeypatch):
    result, _ = route(monkeypatch, request("Qual foi o maior valor da INDUSTRIA?"),
                      intent(op="maximo", category="INDUSTRIA", source="current"))
    assert "maior valor entre as categorias" in result.answer
    assert "R$" not in result.answer


def test_nova_consulta_claramente_externa_continua_rota_query(monkeypatch):
    req = request("Quanto arrecadamos em outubro de 2026?")
    verdict = AnalysisPlanValidator().validate(req, intent("query"),
                {"valor_arrecadado"}, [r["segmento"] for r in DATA])
    assert verdict.action == "query"


def test_categoria_com_acento_e_espacos_normalizada_sem_alterar_numero(monkeypatch):
    result, _ = route(monkeypatch, request("Quanto arrecadou o Comércio Atacadista?"),
                      intent(op="valor", category="Comércio Atacadista", source="current"))
    assert result.answer == "COMERCIO ATACADISTA: arrecadação = R$ 515.690.316,44."


def test_limiar_de_truncamento_continua_protegido(monkeypatch):
    data = [{"segmento": f"s{i}", "valor_arrecadado": i} for i in range(101)]
    result, fake = route(monkeypatch, request("Quem liderou?", data=data), intent())
    assert "muitas linhas" in result.answer
    assert len(fake.calls) == 1


def test_defer_explicativo_nunca_entrega_calculo_livre(monkeypatch):
    req = request("Por que houve uma queda?")
    from analysis.planner import AnalysisIntent as AI
    from chat_service import ChatDecision

    class FreeWriter:
        def __init__(self):
            self.calls = []
        def parse(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs["text_format"] is AI:
                return SimpleNamespace(output_parsed=intent("defer"))
            if kwargs["text_format"] is ChatDecision:
                return SimpleNamespace(output_parsed=ChatDecision(action="answer",
                            answer="O setor caiu R$ 50.000,00 e 10%."))
            raise AssertionError("unexpected")
    fake = FreeWriter()
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "active")
    monkeypatch.setattr(chat_service, "_client", lambda: SimpleNamespace(responses=fake))
    result = chat_service.decidir_continuacao(req)
    assert result.origin == "deterministic"
    assert "Qual operação ou categoria" in result.answer
    assert "50.000" not in result.answer
    assert len(fake.calls) == 2


def test_historico_de_outro_contexto_nao_forca_categoria_antiga(monkeypatch):
    req = request("E quanto foi arrecadado?", data=COMPARE,
                  context=spec(analysis_type="compare_periods"),
                  history=[{"user": "Mostre outra consulta", "assistant": "Consulta carregada"}])
    # Referente inventado como vindo do último turno exige reclassificar.
    result, fake = route(monkeypatch, req,
                         intent(op="valor", category="Comércio", source="previous"),
                         intent(op="valor", category="Comércio", source="previous"))
    assert "qual categoria" in result.answer.lower() or "categoria você" in result.answer.lower()
    assert "R$" not in result.answer
    assert len(fake.calls) == 2
