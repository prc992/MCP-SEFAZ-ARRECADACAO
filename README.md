# Faro — Agente de Dados da SEFAZ

O **Faro** permite consultar dados de arrecadação da SEFAZ-CE em linguagem natural e gerar **tabelas, gráficos e relatórios**. A aplicação combina FastAPI, OpenAI, Amazon Redshift e Plotly, com suporte a perguntas de continuação sobre os resultados.

## Funcionalidades

- Consultas por período, receita, subgrupo, segmento e decêndio, com filtros e comparações.
- Séries mensais, inclusive evolução percentual mês a mês, e demonstrativo ICMS/FECOP.
- Gráficos interativos, tabelas e exportação de relatórios em PDF.
- Conversa contextual com motor de análise determinístico e regras fiscais em `DomainCatalog`.
- Avaliação das respostas e envio de sugestões vinculadas à interação original.
- Painel administrativo com métricas de uso, desempenho, erros, feedback e sugestões.

## Executar localmente

Requer **Python 3.11+** (ambiente atual: Python 3.13), acesso ao Redshift e chave da API OpenAI.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Configure um arquivo `.env` na raiz do projeto (não o envie ao Git):

```dotenv
OPENAI_API_KEY=sua_chave
OPENAI_MODEL=gpt-4.1-mini
REDSHIFT_HOST=host
REDSHIFT_PORT=5439
REDSHIFT_DATABASE=banco
REDSHIFT_USER=usuario
REDSHIFT_PASSWORD=senha
REDSHIFT_SSL=true
ANALYSIS_PLANNER_MODE=active
```

Inicie a aplicação:

```powershell
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

| Endereço | Finalidade |
|---|---|
| [`/faro`] | Interface de consultas (também disponível em `/playground`) |
| [`/faro/admin`] | Dashboard de uso e sugestões |

## Estrutura principal

| Componente | Responsabilidade |
|---|---|
| `main.py` | API FastAPI e endpoints de consultas, chat, feedback e sugestões |
| `llm_service.py`, `schemas.py` | Interpretação de perguntas e contrato `QuerySpec` |
| `query_engine.py`, `redshift_client.py` | Consultas ao Redshift |
| `chat_service.py`, `analysis/`, `domains/sefaz/` | Continuação contextual e análise determinística por domínio |
| `chart_engine.py`, `pdf_report.py` | Visualizações e PDF |
| `interaction_logger.py`, `observability.py`, `suggestion_service.py` | Logs, métricas e sugestões |
| `faro_usage_dashboard.py` | Dados do painel administrativo |
| `templates/`, `static/` | Interfaces web do Faro e do painel |

## Configuração e testes

`ANALYSIS_PLANNER_MODE` aceita `legacy` (padrão), `shadow` e `active`. O modo `active` habilita o planejador semântico para as continuações.

```powershell
python -m pytest -q tests
```

Os eventos de interação são gravados em `logs_interacoes/interacoes_YYYY-MM-DD.jsonl` e as sugestões em `logs_interacoes/sugestoes_YYYY-MM-DD.jsonl`. O diretório pode ser alterado por `INTERACTION_LOG_DIR`.

> **Atenção:** `/faro/admin` está sem autenticação na aplicação e mostra perguntas e sugestões. Restrinja seu acesso pela rede ou proxy. Proteja o `.env` e os logs; não exponha o Uvicorn de desenvolvimento diretamente à internet.
