"""Interpretação alternativa de perguntas em QuerySpec usando uma LLM."""
import os
from datetime import date
from functools import lru_cache
import httpx

from dotenv import load_dotenv
from schemas import QuerySpec
from catalog_service import listar_segmentos, listar_subgrupos_receita

load_dotenv()

SYSTEM_PROMPT = """Você interpreta perguntas em português sobre arrecadação tributária do Ceará.
Sua ÚNICA tarefa é preencher o contrato QuerySpec fornecido; não gere SQL nem responda com dados.

Regras de interpretação:
- metric: valor_arrecadado para valores; qtd_documentos somente para contagem de documentos/DAEs.

- group_by determina a dimensão de agrupamento dos dados.

- Valores permitidos:
  total: arrecadação ou quantidade total, sem agrupamento.
  segmento: agrupamento por setor ou segmento econômico.
  subgrupo: agrupamento por grupo ou classificação da receita.
  receita: agrupamento pela descrição da receita.
  codigo_receita: agrupamento pelo código da receita.
  data_pagamento: agrupamento por dia ou data de pagamento.
  mes: agrupamento por mês, principalmente em séries temporais.

- Use group_by="total" quando o usuário solicitar um valor
  consolidado, sem separação por nenhuma dimensão.

- Exemplos que devem utilizar group_by="total":
  "Quanto o estado arrecadou em maio de 2026?"
  "Qual foi a arrecadação total de ICMS em abril?"
  "Quanto recebemos de ICMS em maio comparado a abril?"
  "Quanto foi arrecadado no mês passado?"
  "Qual a diferença de arrecadação entre abril e maio?"

- Não utilize group_by="mes" apenas porque a pergunta
  menciona meses. Comparar dois totais mensais não significa
  agrupar os resultados por mês.

- Utilize group_by="mes" quando o usuário pedir uma
  evolução mensal, série histórica ou detalhamento mês a mês.

- Se o usuário solicitar agrupamento por segmento, receita,
  subgrupo ou outra dimensão disponível, preserve esse
  agrupamento, mesmo em comparações entre períodos.

- Não invente um agrupamento quando a pergunta pedir apenas
  um valor total.

- analysis_type: compare_periods para comparação entre dois meses; time_series para
  'últimos N meses'; aggregate nos demais casos.
- Datas devem ser YYYY-MM-DD. Para um mês, use primeiro e último dia do mês.

- compare_periods: preencher period_1_start/end/label
  e period_2_start/end/label.

- Os labels devem seguir o padrão nome_mes_ano,
  sem acentos ou espaços.

- Para comparações cronológicas de arrecadação:
  period_1 representa o período anterior (referência).
  period_2 representa o período posterior (avaliado).

- A diferença será calculada como:
  valor_periodo_2 - valor_periodo_1.

- A variação percentual será calculada em relação
  ao valor do period_1.

- Exemplo:
  Pergunta: "Quanto arrecadamos em maio de 2026
  em relação ao mês anterior?"

  period_1_start = "2026-04-01"
  period_1_end = "2026-04-30"
  period_1_label = "abril_2026"

  period_2_start = "2026-05-01"
  period_2_end = "2026-05-31"
  period_2_label = "maio_2026"

- Interprete expressões relativas como "mês anterior",
  "mesmo mês do ano passado" e "mês seguinte" usando
  o período explicitamente mencionado na pergunta.

- Não altere anos ou meses explicitamente informados.

- time_series: use group_by=mes, chart_type=line, top_n=null e months_back=N.
- Agrupamento por data_pagamento: chart_type=line, top_n=null. Demais: chart_type=bar,
  top_n=10, salvo pedido explícito do usuário.
- order_desc=true, salvo pedido de menores valores ou ordem crescente.
- segmento, subgrupo e receita são FILTROS e não devem ser confundidos com group_by.
  Somente preencha um filtro quando o usuário pedir para restringir àquele valor.
- Para segmento e subgrupo, use apenas nomes exatos dos catálogos fornecidos abaixo;
  se não houver correspondência confiável, deixe null. Não invente nomes de filtros.
- Não invente datas, valores ou opções ausentes na pergunta. Se não houver período,
  deixe os campos correspondentes null.
"""


@lru_cache(maxsize=1)
def _client():
    from openai import OpenAI
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"], http_client=httpx.Client(trust_env=False),timeout=25.0, max_retries=1)


def interpretar_pergunta_llm(question: str) -> QuerySpec:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY não configurada no ambiente")

    # Catálogos reais restringem as opções de filtros conhecidas pela LLM.
    segmentos = listar_segmentos()
    subgrupos = listar_subgrupos_receita()
    contexto = (
        f"Data atual: {date.today().isoformat()}\n"
        f"Segmentos disponíveis: {segmentos}\n"
        f"Subgrupos disponíveis: {subgrupos}"
    )
    resposta = _client().responses.parse(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        input=[
            {"role": "system", "content": SYSTEM_PROMPT + "\n" + contexto},
            {"role": "user", "content": question},
        ],
        text_format=QuerySpec,
        store=False,
    )

    if resposta.output_parsed is None:
        raise ValueError("LLM não retornou um QuerySpec válido")

    spec = resposta.output_parsed

    if (
        spec.analysis_type == "compare_periods"
        and spec.period_1_start
        and spec.period_2_start
        and spec.period_1_start > spec.period_2_start
    ):
        spec = spec.model_copy(update={
            "period_1_start": spec.period_2_start,
            "period_1_end": spec.period_2_end,
            "period_1_label": spec.period_2_label,
            "period_2_start": spec.period_1_start,
            "period_2_end": spec.period_1_end,
            "period_2_label": spec.period_1_label,
        })

    return spec

