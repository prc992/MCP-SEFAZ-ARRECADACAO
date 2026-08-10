# Arquitetura proposta (Agent + MCP)

## Organização por pastas

- `app/presentation/`: interface Streamlit e componentes de apresentação.
- `app/execution/tools/agent_tool/`: orquestração do agente, planner LLM, guardrails, catálogo de tools e resumo textual.
- `app/execution/tools/agent_tool/dtos.py`: DTOs internos da orquestração, como `AgentPlan`, `AgentResponse` e `ToolCall`.
- `app/execution/`: ferramentas de consulta e visualização.
- `app/infrastructure/`: acesso à base e catálogos auxiliares.
- `app/shared/`: contracts compartilhados e contratos de dados como `QuerySpec`.
- `app/config/`: políticas e configurações externas, como guardrails.
- `streamlit_app.py`: launcher raiz para iniciar a interface sem expor a estrutura interna.

## Fluxo

1. Usuario envia pergunta no chat Streamlit.
2. Cliente MCP local chama a tool `agent_tool` no servidor MCP.
3. `agent_tool` usa guardrails externos carregados de `app/config/guardrails_policy.json` e consulta o catálogo de tools registradas no servidor.
4. LLM Planner gera um plano estruturado de `tool_calls` com base no catálogo registrado.
5. Orquestrador executa as tools em sequência, resolvendo dependências simples como o `chart_tool` consumir os dados retornados pela `query_tool`.
6. `summary_builder` gera o resumo textual a partir do `QuerySpec` derivado do plano.
8. Resposta estruturada retorna para a UI com:
   - mensagem final
   - QuerySpec
   - SQL
   - dados
   - grafico

## Guardrails

- Perguntas fora de dominio nao sao respondidas com texto livre.
- O agente somente responde quando consegue mapear para ferramentas registradas e a sequência planejada é suficiente para executar a resposta.
- Politica de escopo e orientacao ficam em arquivo externo para facilitar manutencao.

## Independencia da implementacao atual

- Todo codigo operacional da nova arquitetura foi criado em `REFATORACAO_MCP`.
- Nao depende de `main.py` nem de endpoints FastAPI existentes no projeto antigo.
- Reaproveita apenas a logica funcional, replicada e adaptada para o novo contexto.

## Observacao de implementacao

- A orquestracao concreta hoje esta centralizada em `app/execution/tools/agent_tool/agent_tool.py`.
- A tool publica exposta pelo servidor MCP e `agent_tool`; `query_tool` e `chart_tool` seguem como ferramentas de execucao e o agente valida se o conjunto registrado é suficiente antes de responder.
