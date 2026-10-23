"""Validação semântica determinística entre AnalysisPlanner e AnalysisEngine.

Nunca altera valores, períodos, dimensões ou métricas. Corrige apenas referências
não fundamentadas em rankings globais, normaliza nomes de categorias já exibidas
e exige nova classificação quando query/defer não traz evidência de seu escopo.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Literal

from .schemas import AnalysisSpec


@dataclass(frozen=True)
class ValidationDecision:
    action: Literal["analyze", "query", "defer", "clarify", "retry"]
    spec: AnalysisSpec | None = None
    reason: str | None = None
    question: str | None = None


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value)).casefold()
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.strip().split())


def _mentioned(value: str, message: str) -> bool:
    target, text = _norm(value), _norm(message)
    if not target:
        return False
    if re.search(r"(?<!\w)" + re.escape(target) + r"(?!\w)", text):
        return True
    ordinal = re.fullmatch(r"([123]) decendio", target)
    if ordinal:
        aliases = {"1": ("primeiro", "1º", "1o"),
                   "2": ("segundo", "2º", "2o"),
                   "3": ("terceiro", "3º", "3o")}[ordinal.group(1)]
        return any(re.search(r"(?<!\w)" + re.escape(f"{x} decendio") + r"(?!\w)", text)
                   for x in aliases)
    return False


def _last_turn(req) -> str:
    if not req.history:
        return ""
    last = req.history[-1]
    return str(last.get("user", "")) + " " + str(last.get("assistant", ""))


def _explicit_scope_change(question: str, query_spec) -> bool:
    """Evidência conservadora de solicitação de NOVOS dados; não classifica operação.

    Quando não há evidência, outra classificação é exigida. Não converte
    automaticamente um plano query em analyze.
    """
    n = _norm(question)
    if re.search(r"\b(mostre|gere|refaca|atualize|mude|troque|filtre|agrup[ea]|grafico|nova consulta|outro grafico|ultimos? \d+ meses)\b", n):
        return True
    if re.search(r"\b(compare (com|entre)|comparar (com|entre)|no lugar de|em vez de)\b", n):
        return True
    # Uma data ou mês explicitamente diferente do contexto indica novo recorte.
    known = [query_spec.start_date, query_spec.end_date, query_spec.period_1_start,
             query_spec.period_1_end, query_spec.period_2_start, query_spec.period_2_end]
    periods = {d[:7] for d in known if d and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)}
    for year, month in re.findall(r"(?<!\d)(20\d{2})-(0[1-9]|1[0-2])(?!\d)", n):
        if f"{year}-{month}" not in periods:
            return True
    months = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4,
              "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
              "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
    for name, number in months.items():
        if re.search(r"\b" + name + r"\b", n):
            if not any(p.endswith(f"-{number:02d}") for p in periods):
                return True
    for year in re.findall(r"(?<!\d)(20\d{2})(?!\d)", n):
        if not any(p.startswith(year) for p in periods):
            return True
    # Expressa outra dimensão não presente na consulta atual.
    groups = ("segmento", "subgrupo", "receita", "codigo_receita", "decendio", "mes", "data_pagamento")
    if re.search(r"\bpor\s+(segmento|subgrupo|receita|codigo de receita|decendio|mes|dia)\b", n):
        for word in groups:
            if word != query_spec.group_by and re.search(r"\bpor\s+" + word + r"\b", n):
                return True
    return False


def _clearly_explanatory(question: str) -> bool:
    n = _norm(question)
    return bool(re.match(r"^(por que|porque|qual a causa|quais as causas|o que significa|o que e |explique o conceito|defina )\b", n))


class AnalysisPlanValidator:
    def validate(self, req, intent, available: set[str], categories: list[str], *, retry: bool = False) -> ValidationDecision:
        if intent.action == "query":
            if _explicit_scope_change(req.question, req.previous_spec):
                return ValidationDecision("query")
            if not retry:
                return ValidationDecision("retry", reason="query_without_scope_evidence")
            return ValidationDecision("clarify", reason="query_scope_ambiguous",
                question="Você quer analisar os dados já exibidos ou fazer uma nova consulta com outro recorte?")

        if intent.action == "defer":
            if _clearly_explanatory(req.question):
                return ValidationDecision("defer")
            if not retry:
                return ValidationDecision("retry", reason="unconfirmed_defer")
            return ValidationDecision("clarify", reason="intent_ambiguous",
                question="Você deseja um cálculo sobre a tabela exibida, uma nova consulta ou uma explicação conceitual?")

        if intent.metric is not None and intent.metric not in available:
            return ValidationDecision("clarify", reason="metric_not_available",
                question="A operação solicitada não foi validada: indicador indisponível nos dados exibidos. Qual indicador deseja analisar?")

        if not categories:
            return ValidationDecision("clarify", reason="no_analytical_data",
                question="Não há categorias com dados disponíveis. Solicite uma consulta mais específica.")

        # Normalizar para UMA única categoria existente; não criar sinônimos de negócio.
        candidates = [c for c in categories if intent.category is not None and _norm(c) == _norm(intent.category)]
        category = candidates[0] if len(candidates) == 1 else None
        op = intent.operation
        global_rank = req.previous_spec.analysis_type != "compare_periods" and op in ("maximo", "minimo", "amplitude")
        mentioned_categories = [c for c in categories if _mentioned(c, req.question)]
        mentions_known_category = bool(mentioned_categories)
        target_operation = op in ("valor", "variacao", "variacao_percentual", "diferenca", "outros") or (
            req.previous_spec.analysis_type == "compare_periods" and op in ("maximo", "minimo"))
        if target_operation and len(mentioned_categories) > 1:
            return ValidationDecision("clarify", reason="multiple_categories",
                question="Você mencionou mais de uma categoria. Qual delas deseja analisar?")
        if target_operation and len(mentioned_categories) == 1:
            # A categoria explicitamente citada pelo usuário prevalece sobre
            # a referência da última troca e sobre o alvo sugerido pela LLM.
            category = mentioned_categories[0]
            category_source = "current"
        else:
            category_source = intent.category_source

        if intent.category is not None and category is None and not (target_operation and mentioned_categories):
            # Em rankings GLOBAIS, um alvo inventado pela LLM não pode influenciar
            # a operação. Só se descarta se o usuário NÃO citou nenhuma categoria
            # real e a pergunta não tenta obter um valor específico.
            if global_rank and not mentions_known_category:
                category = None
            elif not retry and intent.category_source != "current":
                return ValidationDecision("retry", reason="unmatched_context_category")
            else:
                return ValidationDecision("clarify", reason="category_not_available",
                    question="A operação solicitada não foi validada: categoria ausente nos dados exibidos. Qual categoria deseja analisar?")

        if category is not None and category_source == "current" and not _mentioned(category, req.question):
            if global_rank and not mentions_known_category:
                category = None
            elif not retry:
                return ValidationDecision("retry", reason="category_not_grounded_in_question")
            else:
                return ValidationDecision("clarify", reason="category_not_grounded_in_question",
                    question="A operação solicitada não foi validada para essa referência. Qual categoria deseja analisar?")

        # Uma classificação anterior não pode usar categoria não comprovada na
        # última interação. Não buscar referentes em todo o histórico.
        if category is not None and category_source == "previous" and not _mentioned(category, _last_turn(req)):
            if global_rank and not mentions_known_category:
                category = None
            elif not retry:
                return ValidationDecision("retry", reason="category_not_grounded_in_last_turn")
            else:
                return ValidationDecision("clarify", reason="category_ambiguous",
                    question="A operação solicitada não foi validada para essa referência. A qual categoria você está se referindo?")

        # Não aceitar uma categoria "explícita" inventada pela LLM; ranking
        # global não seleciona alvo individual, ainda que uma categoria tenha
        # aparecido na última resposta como vencedora de um ranking anterior.
        if global_rank and not mentions_known_category:
            category = None
        if global_rank and mentions_known_category:
            return ValidationDecision("clarify", reason="rank_scope_ambiguous",
                question="Você quer o maior valor entre as categorias exibidas ou o valor de uma categoria específica?")

        if op == "outros" and (category is None or category_source != "current" or
                                req.previous_spec.analysis_type == "compare_periods" or
                                not _mentioned(category, req.question)):
            return ValidationDecision("clarify", reason="others_requires_explicit_category",
                question="A operação solicitada não foi validada. Qual categoria você deseja comparar com a soma das demais?")

        if req.previous_spec.analysis_type == "compare_periods" and op in ("amplitude", "outros"):
            return ValidationDecision("clarify", reason="incompatible_operation",
                question="Essa operação não é suportada em comparações entre períodos. Qual comparação deseja fazer?")
        if req.previous_spec.analysis_type != "compare_periods" and op.startswith("crescimento_"):
            return ValidationDecision("clarify", reason="comparison_required",
                question="Para calcular crescimento, indique os dois períodos que deseja comparar.")
        if req.previous_spec.analysis_type == "compare_periods" and op in ("maximo", "minimo") and category is None:
            return ValidationDecision("clarify", reason="category_required",
                question="De qual categoria você deseja identificar o período com maior ou menor valor?")
        if req.previous_spec.analysis_type == "compare_periods" and op in ("diferenca", "variacao", "variacao_percentual") and category is None:
            return ValidationDecision("clarify", reason="category_required",
                question="De qual categoria deseja calcular a variação entre os períodos?")

        previous = req.previous_spec
        spec = AnalysisSpec(
            operation=op, metric=intent.metric, category=category,
            explicit_category=category if category_source == "current" and _mentioned(category, req.question) else None,
            group_by=previous.group_by, analysis_type=previous.analysis_type,
            report_type=previous.report_type, period_1_label=previous.period_1_label,
            period_2_label=previous.period_2_label, others_named=op == "outros",
        )
        return ValidationDecision("analyze", spec=spec)
