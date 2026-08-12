# Arquitetura proposta (agente de chat + MCP)

## Organização por pastas

- `app/presentation/chat_interface.py`: interface Streamlit e componentes de apresentação.
- `app/execution/chat_agent/`: orquestração do agente, planejador LLM, regras de segurança, contratos e resumo textual.
- `app/execution/`: ferramentas de consulta e visualização.
- `app/infrastructure/`: acesso à base e catálogos auxiliares.
- `app/shared/`: contratos compartilhados e dados como `QuerySpec`.
- `app/config/`: políticas e configurações externas, como regras de segurança.
- `streamlit_app.py`: inicializador da interface na raiz, sem expor a estrutura interna.

## Fluxo

1. Usuário envia pergunta no chat Streamlit.
2. A interface chama diretamente o agente de chat.
3. O agente usa regras externas carregadas do arquivo de segurança e consulta o catálogo de ferramentas registradas no servidor.
4. O planejador LLM gera um plano estruturado de chamadas de ferramenta com base no catálogo registrado.
5. O agente usa o ajudante MCP local para chamar a ferramenta de consulta e a ferramenta de gráfico no servidor MCP.
6. O resumo textual é gerado a partir da estrutura derivada do plano.
7. A resposta estruturada retorna para a interface com:
   - mensagem final
   - estrutura da consulta
   - SQL
   - dados
   - grafico

## Guardrails

- Perguntas fora de domínio não são respondidas com texto livre.
- O agente somente responde quando consegue mapear para ferramentas registradas e a sequência planejada é suficiente para executar a resposta.
- As regras de escopo e orientação ficam em arquivo externo para facilitar manutenção.

## Independência da implementação atual

- Todo o código operacional da nova arquitetura foi criado em `REFATORACAO_MCP`.
- Não depende de `main.py` nem de endpoints FastAPI existentes no projeto antigo.
- Reaproveita apenas a lógica funcional, replicada e adaptada para o novo contexto.

## Observação de implementação

- A orquestração concreta hoje está centralizada no agente de chat.
- O servidor MCP publica apenas a ferramenta de consulta e a ferramenta de gráfico; o agente valida se o conjunto registrado é suficiente antes de responder.
