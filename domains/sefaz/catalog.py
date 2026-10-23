"""Metadados da SEFAZ-CE, separados do núcleo matemático compartilhável."""
from dataclasses import dataclass

from analysis.domain import DomainCatalog, MetricDefinition, normalize


@dataclass(frozen=True)
class SefazCatalog(DomainCatalog):
    def mentioned_metrics(self, text: str, available: set[str]) -> list[str]:
        # Preserva exatamente a precedência das regras da Etapa 2, inclusive
        # aliases genéricos ambíguos (ICMS, FECOP, documentos).
        n = normalize(text)
        for patterns, key in (
            (("sem fecop", "indicador c", "coluna c"), "icms_sem_fecop_c"),
            (("liquido", "tesouro", "indicador d", "coluna d"), "icms_liquido_tesouro_d"),
            (("fecop", "indicador b", "coluna b"), "fecop_b"),
        ):
            if any(x in n for x in patterns):
                return [key] if key in available else []
        if any(x in n for x in ("icms", "indicador a", "coluna a")):
            if "icms_a" in available:
                return ["icms_a"]
            if "valor_arrecadado" in available:
                return ["valor_arrecadado"]
        for key in ("qtd_documentos", "valor_arrecadado"):
            metric = self.metrics[key]
            if key in available and any(x in n for x in metric.aliases):
                return [key]
        return []


SEFAZ_CATALOG = SefazCatalog(
    id="sefaz_ce_arrecadacao",
    metrics={
        "icms_a": MetricDefinition("ICMS bruto (A)", ("icms bruto", "icms total", "coluna a", "indicador a", "icms")),
        "fecop_b": MetricDefinition("FECOP (B)", ("fecop", "coluna b", "indicador b")),
        "icms_sem_fecop_c": MetricDefinition("ICMS sem FECOP (C)", ("icms sem fecop", "sem fecop", "coluna c", "indicador c")),
        "icms_liquido_tesouro_d": MetricDefinition("ICMS líquido Tesouro (D)", ("icms liquido tesouro", "icms liquido", "tesouro", "coluna d", "indicador d", "liquido")),
        "valor_arrecadado": MetricDefinition("arrecadação", ("valor arrecadado", "arrecadacao", "arrecadado", "icms")),
        "qtd_documentos": MetricDefinition("documentos pagos", ("quantidade de documentos", "documentos", "dae"), unit="count"),
    },
    dimensions=("decendio", "mes", "data_pagamento", "receita", "codigo_receita", "subgrupo", "segmento", "total"),
    metric_priority=("icms_liquido_tesouro_d", "icms_sem_fecop_c", "fecop_b", "icms_a", "qtd_documentos", "valor_arrecadado"),
    derived_numeric_fields=frozenset({"variacao_percentual", "diferenca", "qtd_registros", "codigo_receita", "periodo"}),
    long_comparison_reports=frozenset({"icms_fecop"}),
    total_row_field="decendio",
    total_row_label="Total geral",
    period_field="periodo",
    category_aliases={
        "1 Decêndio": ("1º decêndio", "primeiro decendio", "1o decendio", "1 decendio"),
        "2 Decêndio": ("2º decêndio", "segundo decendio", "2o decendio", "2 decendio"),
        "3 Decêndio": ("3º decêndio", "terceiro decendio", "3o decendio", "3 decendio"),
    },
    dimension_aliases={
        "segmento": ("segmentos", "setor", "setores"),
        "subgrupo": ("subgrupos",),
        "receita": ("receitas",),
        "codigo_receita": ("codigo de receita",),
        "decendio": ("decendios",),
        "mes": ("meses",),
        "data_pagamento": ("dia", "data"),
    },
    report_metric_aliases={"standard": {"icms_a": "valor_arrecadado"}},
    metric_question="Qual indicador você quer analisar (ICMS, FECOP, ICMS sem FECOP ou ICMS líquido Tesouro)?",
    metric_prompt=(
        "No domínio SEFAZ, segmento e setor são nomes de DIMENSÃO, não categorias individuais. "
        "A=ICMS bruto (inclui FECOP); B=FECOP; C=A-B; D=60% de C. "
        "Esses valores são calculados no SQL da consulta original, nunca na LLM. "
        "Para indicadores de composição, use os nomes de campo fiscais existentes. "
        "Decêndios oficiais são categorias '1 Decêndio', '2 Decêndio', '3 Decêndio', "
        "e não podem ser inferidos a partir de datas."
    ),
)
