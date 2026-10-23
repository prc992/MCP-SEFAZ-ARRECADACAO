"""Contrato de domínio do motor analítico (sem conhecimento fiscal).

A aplicação chama o motor com um DomainCatalog explícito ou utiliza o domínio
padrão configurado na borda de integração. Não armazena estado por usuário.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping
from types import MappingProxyType
import re
import unicodedata


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value)).casefold()
    return " ".join("".join(c for c in text if unicodedata.category(c) != "Mn").strip().split())


@dataclass(frozen=True)
class MetricDefinition:
    label: str
    aliases: tuple[str, ...] = ()
    unit: str = "currency"  # currency, count, number ou percent


@dataclass(frozen=True)
class DomainCatalog:
    id: str
    metrics: Mapping[str, MetricDefinition]
    dimensions: tuple[str, ...]
    metric_priority: tuple[str, ...] = ()
    derived_numeric_fields: frozenset[str] = frozenset()
    long_comparison_reports: frozenset[str] = frozenset()
    total_row_field: str | None = None
    total_row_label: str | None = None
    period_field: str = "periodo"
    category_aliases: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    dimension_aliases: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    report_metric_aliases: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    currency_symbol: str = "R$"
    metric_prompt: str = ""
    metric_question: str = "Qual indicador você quer analisar?"
    default_context_metric_reports: frozenset[str] = frozenset({"standard"})

    def __post_init__(self):
        # Nenhum MCP pode alterar acidentalmente o catálogo de outro pedido.
        for attr in ("metrics", "category_aliases", "dimension_aliases"):
            object.__setattr__(self, attr, MappingProxyType(dict(getattr(self, attr))))
        object.__setattr__(self, "report_metric_aliases", MappingProxyType({
            name: MappingProxyType(dict(mapping)) for name, mapping in self.report_metric_aliases.items()
        }))

    def without_totals(self, rows: list[dict]) -> list[dict]:
        if self.total_row_field is None:
            return list(rows)
        return [r for r in rows if r.get(self.total_row_field) != self.total_row_label]

    def is_long_comparison(self, report_type: str) -> bool:
        return report_type in self.long_comparison_reports

    def label(self, metric: str | None) -> str | None:
        definition = self.metrics.get(metric) if metric is not None else None
        return definition.label if definition else metric

    def unit(self, metric: str | None) -> str:
        definition = self.metrics.get(metric) if metric is not None else None
        return definition.unit if definition else "currency"

    def display_category(self, value: object) -> str:
        raw = str(value).strip()
        for canonical, alternatives in self.category_aliases.items():
            if normalize(raw) == normalize(canonical):
                return alternatives[0] if alternatives else raw
        return raw.replace("_", "/")

    def mentions_category(self, value: str, question: str) -> bool:
        target, text = normalize(value), normalize(question)
        if target and re.search(r"(?<!\w)" + re.escape(target) + r"(?!\w)", text):
            return True
        aliases = self.category_aliases.get(value, ())
        return any(bool(re.search(r"(?<!\w)" + re.escape(normalize(a)) + r"(?!\w)", text))
                   for a in aliases)

    def explicit_category(self, text: str, categories) -> str | None:
        for cat in categories:
            if cat is None or str(cat) == "Total":
                continue
            if self.mentions_category(str(cat), text):
                return cat
        return None

    def mentioned_metrics(self, text: str, available: set[str]) -> list[str]:
        """Identifica o primeiro indicador permitido; precedência definida pelo domínio.

        As regras especiais sobre aliases ambíguos pertencem ao adaptador fiscal.
        """
        n = normalize(text)
        for key in self.metric_priority or tuple(self.metrics):
            metric = self.metrics.get(key)
            if metric and key in available and any(normalize(alias) in n for alias in metric.aliases):
                return [key]
        return []

    def context_metric(self, metric: str, report_type: str, available: set[str]) -> str | None:
        if report_type in self.default_context_metric_reports and metric in available:
            return metric
        return None

    def remap_metric(self, metric: str | None, report_type: str) -> str | None:
        return self.report_metric_aliases.get(report_type, {}).get(metric, metric)

    def dimension_from_phrase(self, phrase: str) -> str | None:
        n = normalize(phrase)
        for name in self.dimensions:
            if n == normalize(name) or any(n == normalize(a) for a in self.dimension_aliases.get(name, ())):
                return name
        return None

    def planner_context(self) -> str:
        return self.metric_prompt + "\nMétricas válidas: " + ", ".join(
            f"{key}={definition.label}" for key, definition in self.metrics.items()
        ) + "\nDimensões válidas: " + ", ".join(self.dimensions)


def resolve_catalog(catalog: DomainCatalog | None = None) -> DomainCatalog:
    if catalog is not None:
        return catalog
    # Apenas uma convenção de registro: o pacote analysis não menciona nem
    # importa implementações ou particularidades de um domínio fiscal.
    from domains import default_catalog
    return default_catalog()
