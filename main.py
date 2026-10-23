from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import HTMLResponse
from schemas import QuerySpec, AskRequest
from query_engine import executar_query
from chart_engine import gerar_plotly_figure, gerar_graficos_icms_fecop
from metadata_service import get_metadata
from ask_service import gerar_summary
from llm_service import interpretar_pergunta_llm
from data_availability_service import validar_disponibilidade
from chat_service import ChatRequest, decidir_continuacao
from interaction_logger import novo_id, validar_id, registrar_interacao, registrar_feedback
from pydantic import BaseModel
from typing import Literal
import time

app = FastAPI()


def preparar_dados_tabela(dados: list[dict], spec: QuerySpec) -> list[dict]:
    """Acrescenta Total geral somente à tabela agrupada por decêndio.

    Não modifica os dados de origem utilizados no gráfico.
    """
    if spec.report_type == "icms_fecop":
        linhas = [dict(row) for row in dados]
        if spec.group_by != "decendio" or not linhas:
            return linhas
        indicadores = ("icms_a", "fecop_b", "icms_sem_fecop_c", "icms_liquido_tesouro_d")
        if spec.analysis_type == "compare_periods":
            # Um subtotal por período, sem confundir valores de anos diferentes.
            resultado = []
            for periodo in (spec.period_1_label or "periodo_1", spec.period_2_label or "periodo_2"):
                grupo = [row for row in linhas if row.get("periodo") == periodo]
                resultado.extend(grupo)
                if grupo:
                    resultado.append({"decendio": "Total geral", "periodo": periodo,
                        **{chave: sum(float(row.get(chave) or 0) for row in grupo)
                           for chave in indicadores}})
            return resultado
        return linhas + [{"decendio": "Total geral",
            **{chave: sum(float(row.get(chave) or 0) for row in linhas)
               for chave in indicadores}}]

    linhas = [dict(row) for row in dados]
    if spec.group_by != "decendio" or not linhas:
        return linhas

    if spec.analysis_type == "compare_periods":
        label_1 = spec.period_1_label or "periodo_1"
        label_2 = spec.period_2_label or "periodo_2"
        total_1 = sum(float(row.get(label_1) or 0) for row in linhas)
        total_2 = sum(float(row.get(label_2) or 0) for row in linhas)
        diferenca = total_2 - total_1
        total = {
            "decendio": "Total geral",
            label_1: total_1,
            label_2: total_2,
            "diferenca": diferenca,
            "variacao_percentual": (diferenca / total_1 * 100) if total_1 else None,
            "tendencia": "subiu" if diferenca > 0 else ("caiu" if diferenca < 0 else "estável"),
        }
    else:
        total = {
            "decendio": "Total geral",
            spec.metric: sum(float(row.get(spec.metric) or 0) for row in linhas),
        }

    linhas.append(total)
    return linhas


def preparar_graficos(dados: list[dict], spec: QuerySpec):
    """Mantém plotly_json legado e acrescenta plotly_charts no relatório fiscal."""
    if spec.report_type == "icms_fecop":
        graficos = [fig.to_dict() for fig in gerar_graficos_icms_fecop(dados, spec)]
        return graficos[0], graficos
    fig = gerar_plotly_figure(dados, spec)
    return fig.to_dict(), None


def resumo_relatorio(spec: QuerySpec):
    if spec.report_type != "icms_fecop":
        return gerar_summary(spec)
    if spec.analysis_type == "compare_periods":
        periodo = f"comparação entre {spec.period_1_label or 'período 1'} e {spec.period_2_label or 'período 2'}"
    else:
        periodo = f"período de {spec.start_date} a {spec.end_date}"
    dimensao = "por decêndio" if spec.group_by == "decendio" else "consolidado"
    return (f"Composição do ICMS/FECOP {dimensao}, {periodo}: "
            "A = ICMS bruto; B = FECOP; C = A − B; D = 60% de C.")


@app.get("/")
def home():
    return {"mensagem": "API funcionando"}


@app.get("/metadata")
def metadata():
    return get_metadata()


@app.post("/grafico")
def gerar_grafico(spec: QuerySpec):
    try:
        disponibilidade = validar_disponibilidade(spec)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Não foi possível verificar a disponibilidade dos dados no Redshift.") from exc
    if not disponibilidade["disponivel"]:
        raise HTTPException(status_code=422, detail=disponibilidade["mensagem"])
    query_result = executar_query(spec)
    dados = query_result["dados"]
    sql = query_result["sql"]

    plotly_json, plotly_charts = preparar_graficos(dados, spec)

    return {
        "title": f"{spec.metric} por {spec.group_by}",
        "chart_type": spec.chart_type,
        "dados_brutos": dados,
        "dados_tabela": preparar_dados_tabela(dados, spec),
        "plotly_json": plotly_json,
        "plotly_charts": plotly_charts
    }


@app.post("/grafico-html", response_class=HTMLResponse)
def gerar_grafico_html(spec: QuerySpec):
    try:
        disponibilidade = validar_disponibilidade(spec)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Não foi possível verificar a disponibilidade dos dados no Redshift.") from exc
    if not disponibilidade["disponivel"]:
        raise HTTPException(status_code=422, detail=disponibilidade["mensagem"])
    query_result = executar_query(spec)
    dados = query_result["dados"]
    sql = query_result["sql"]

    if spec.report_type == "icms_fecop":
        from plotly.offline import plot
        figuras = gerar_graficos_icms_fecop(dados, spec)
        blocos = [plot(fig, include_plotlyjs="cdn" if i == 0 else False, output_type="div")
                  for i, fig in enumerate(figuras)]
        return HTMLResponse(content="<html><body>" + "".join(blocos) + "</body></html>")
    fig = gerar_plotly_figure(dados, spec)
    return HTMLResponse(content=fig.to_html(full_html=True))


class FeedbackRequest(BaseModel):
    session_id: str
    interaction_id: str
    vote: Literal["positive", "negative"]


@app.post("/feedback")
def feedback(req: FeedbackRequest, request: Request):
    if not registrar_feedback(session_id=req.session_id,
                              interaction_id=req.interaction_id, voto=req.vote,
                              client_ip=request.client.host if request.client else None):
        raise HTTPException(status_code=404, detail="Interação não encontrada para esta sessão.")
    return {"ok": True, "vote": req.vote}


def _finalizar_interacao(*, resposta, pergunta, sessao, interacao, parent, tipo, inicio, client_ip=None, origem=None):
    resposta["session_id"] = sessao
    resposta["interaction_id"] = interacao
    registrar_interacao(session_id=sessao, interaction_id=interacao,
                        parent_interaction_id=parent, tipo=tipo, pergunta=pergunta,
                        resposta=resposta, duracao_ms=(time.perf_counter()-inicio)*1000,
                        origem=origem, client_ip=client_ip)
    return resposta


@app.post("/ask")
def ask(req: AskRequest, request: Request, x_session_id: str | None = Header(default=None)):
    inicio = time.perf_counter()
    sessao = validar_id(x_session_id) or novo_id()
    interacao = novo_id()
    def finalizar(resposta):
        return _finalizar_interacao(resposta=resposta, pergunta=req.question,
            sessao=sessao, interacao=interacao, parent=None, tipo="initial", inicio=inicio,
            origem="llm_query", client_ip=request.client.host if request.client else None)
    try:
        spec = interpretar_pergunta_llm(req.question)
    except Exception as exc:
        return finalizar({"question": req.question,
            "error": f"Falha na interpretação por LLM ({type(exc).__name__}).",
            "error_type": "llm_failed"})
    try:
        disponibilidade = validar_disponibilidade(spec)
    except Exception:
        return finalizar({"question": req.question,
            "query_interpretada": spec.model_dump(),
            "error": "Não foi possível verificar a disponibilidade dos dados no Redshift.",
            "error_type": "availability_check_failed"})
    if not disponibilidade["disponivel"]:
        return finalizar({"question": req.question,
            "query_interpretada": spec.model_dump(),
            "error": disponibilidade["mensagem"], "error_type": "period_unavailable",
            "meses_ausentes": disponibilidade.get("meses_ausentes", [])})
    try:
        query_result = executar_query(spec)
        dados = query_result["dados"]
        plotly_json, plotly_charts = preparar_graficos(dados, spec)
        return finalizar({
            "question": req.question,
            "query_interpretada": spec.model_dump(),
            "summary": resumo_relatorio(spec),
            "aviso_disponibilidade": disponibilidade.get("aviso"),
            "sql": query_result["sql"], "title": f"{spec.metric} por {spec.group_by}",
            "chart_type": spec.chart_type, "dados_brutos": dados,
            "dados_tabela": preparar_dados_tabela(dados, spec),
            "plotly_json": plotly_json, "plotly_charts": plotly_charts
        })
    except Exception as exc:
        return finalizar({"question": req.question, "query_interpretada": spec.model_dump(),
                         "error": "Falha durante a execução da consulta.",
                         "error_type": type(exc).__name__})


@app.post("/chat")
def chat(req: ChatRequest, request: Request, x_session_id: str | None = Header(default=None),
         x_parent_interaction_id: str | None = Header(default=None)):
    inicio = time.perf_counter()
    sessao = validar_id(x_session_id) or novo_id()
    interacao = novo_id()
    parent = validar_id(x_parent_interaction_id)
    origem = None
    def finalizar(resposta):
        return _finalizar_interacao(resposta=resposta, pergunta=req.question,
            sessao=sessao, interacao=interacao, parent=parent, tipo="followup", inicio=inicio,
            origem=origem, client_ip=request.client.host if request.client else None)
    try:
        decisao = decidir_continuacao(req)
    except Exception as exc:
        return finalizar({"action": "error", "error":
                 f"Não foi possível interpretar a continuação ({type(exc).__name__})."})
    if decisao.action == "answer":
        # Respostas determinísticas e respostas livres não devem ser confundidas no log.
        from chat_service import _op
        origem = decisao.origin or ("deterministic" if _op(req) is not None else "llm")
        return finalizar({"action": "answer", "answer": decisao.answer,
                         "query_interpretada": req.previous_spec.model_dump()})
    spec = decisao.query_spec
    origem = "llm_query"
    try:
        disponibilidade = validar_disponibilidade(spec)
    except Exception:
        return finalizar({"action": "error", "error":
                "Não foi possível consultar a disponibilidade dos dados no Redshift."})
    if not disponibilidade["disponivel"]:
        return finalizar({"action": "error", "error": disponibilidade["mensagem"],
                 "query_interpretada": spec.model_dump(), "error_type": "period_unavailable"})
    try:
        resultado = executar_query(spec)
        dados = resultado["dados"]
        plotly_json, plotly_charts = preparar_graficos(dados, spec)
    except Exception as exc:
        return finalizar({"action": "error", "error":
                 f"Falha ao executar a nova consulta ({type(exc).__name__})."})
    return finalizar({
        "action": "query", "answer": "Atualizei a consulta, a tabela e os gráficos conforme solicitado.",
        "query_interpretada": spec.model_dump(), "summary": resumo_relatorio(spec),
        "aviso_disponibilidade": disponibilidade.get("aviso"), "sql": resultado["sql"],
        "dados_brutos": dados, "dados_tabela": preparar_dados_tabela(dados, spec),
        "plotly_json": plotly_json, "plotly_charts": plotly_charts,
    })


@app.get("/playground", response_class=HTMLResponse)
def playground():
    html = """
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>Playground de Perguntas</title>
        <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 20px;
                background: #f7f7f8;
                color: #222;
            }
            .container {
                max-width: 1400px;
                width: calc(100% - 40px);
                box-sizing: border-box;
                margin: 0 auto;
                background: white;
                padding: 24px;
                border-radius: 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            }
            h1 {
                margin-top: 0;
            }
            textarea {
                width: 100%;
                min-height: 100px;
                padding: 12px;
                font-size: 16px;
                border-radius: 8px;
                border: 1px solid #ccc;
                resize: vertical;
                box-sizing: border-box;
            }
            button {
                margin-top: 12px;
                padding: 10px 18px;
                border: none;
                border-radius: 8px;
                background: #111827;
                color: white;
                font-size: 15px;
                cursor: pointer;
            }
            button:hover {
                background: #1f2937;
            }
            .section {
                margin-top: 24px;
                padding: 16px;
                background: #fafafa;
                border: 1px solid #e5e7eb;
                border-radius: 10px;
            }
            .label {
                font-weight: bold;
                margin-bottom: 8px;
            }
            pre {
                white-space: pre-wrap;
                word-break: break-word;
                background: #f3f4f6;
                padding: 12px;
                border-radius: 8px;
                overflow-x: auto;
            }
            #chart { margin-top: 20px; }
            .charts-grid {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 16px;
                width: 100%;
                min-width: 0;
            }
            .chart-panel {
                width: 100%;
                min-width: 0;
                box-sizing: border-box;
                background: white;
                border-radius: 8px;
            }
            @media (max-width: 1050px) {
                .charts-grid { grid-template-columns: minmax(0, 1fr); }
            }


            .chat-input-row { display:flex; gap:10px; align-items:center; }
            .chat-input-row input { flex:1; min-width:0; box-sizing:border-box;
                border:1px solid #d1d5db; border-radius:8px; padding:11px; font-size:15px; }
            .chat-input-row button { margin-top:0; }
            #chatMessages { display:flex; flex-direction:column; gap:10px; margin:12px 0; }
            .chat-message { padding:11px 14px; border-radius:9px; white-space:pre-wrap;
                overflow-wrap:anywhere; max-width:90%; }
            .chat-user { background:#e8edf5; align-self:flex-end; }
            .chat-assistant { background:#f3f4f6; align-self:flex-start; }
            .chat-error { background:#fef2f2; color:#991b1b; align-self:flex-start; }
            .feedback-row { display:flex; gap:8px; align-items:center; margin-top:6px; }
            .feedback-button { margin:0; padding:5px 9px; background:transparent;
                color:#4b5563; border:1px solid #d1d5db; border-radius:7px; font-size:16px; }
            .feedback-button:hover { background:#e5e7eb; }
            .feedback-button.selected { background:#dbeafe; color:#1e40af; border-color:#93c5fd; }
            .feedback-button:disabled { opacity:.6; cursor:wait; }
            .feedback-note { color:#6b7280; font-size:12px; }
            .chat-assistant-wrapper { align-self:flex-start; max-width:90%; }
            .chat-assistant-wrapper .chat-message { max-width:100%; }
            #initialFeedback.feedback-inicial {
                margin-top:22px; padding:15px 18px; gap:12px; flex-wrap:wrap;
                border:1px solid #cbd5e1; border-radius:10px; background:#f1f5f9;
            }
            #initialFeedback.feedback-inicial:empty { display:none; }
            #initialFeedback.feedback-inicial .feedback-note {
                font-size:15px; font-weight:600; color:#1f2937;
            }
            #initialFeedback.feedback-inicial .feedback-button {
                padding:9px 14px; font-size:20px; background:#fff;
            }
            #initialFeedback.feedback-inicial .feedback-button.selected {
                background:#dbeafe; color:#1e40af;
            }
            .muted {
                color: #666;
                font-size: 14px;
            }
            .examples {
                margin-top: 12px;
            }
            .example-chip {
                display: inline-block;
                margin: 6px 8px 0 0;
                padding: 8px 12px;
                border-radius: 999px;
                background: #f3f4f6;
                border: 1px solid #d1d5db;
                cursor: pointer;
                font-size: 14px;
            }
            .example-chip:hover {
                background: #e5e7eb;
            }
            #loading {
                margin-top: 16px;
                color: #374151;
                font-size: 14px;
                display: none;
            }
            #errorBox {
                margin-top: 24px;
                padding: 16px;
                background: #fef2f2;
                border: 1px solid #fecaca;
                color: #991b1b;
                border-radius: 10px;
                display: none;
            }

            .table-scroll {
                width: 100%;
                overflow-x: auto;
                margin-top: 8px;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
            }
            .data-table {
                width: 100%;
                border-collapse: collapse;
                font-size: 14px;
            }
            .data-table.comparacao {
                min-width: 900px;
            }
            .data-table th, .data-table td {
                border-bottom: 1px solid #e5e7eb;
                padding: 11px 14px;
                text-align: left;
                vertical-align: middle;
            }
            .data-table th {
                background: #f3f4f6;
                font-weight: 600;
                white-space: nowrap;
            }
            .data-table .numero {
                text-align: right;
                white-space: nowrap;
                font-variant-numeric: tabular-nums;
            }
            .data-table .categoria {
                white-space: nowrap;
            }
            .data-table tbody tr:nth-child(even):not(.total-geral) {
                background: #f9fafb;
            }
            .data-table tr.total-geral td {
                font-weight: 700;
                background: #e9eef5;
                border-top: 2px solid #94a3b8;
            }
            @media (max-width: 700px) {
                body { margin: 8px; }
                .container { width: 100%; padding: 12px; }
                .data-table th, .data-table td { padding: 9px 10px; }
            }

        </style>
    </head>
    <body>
        <div class="container">
            <h1>Pergunta → Interpretação → Gráfico</h1>
            <p class="muted">
                Digite uma pergunta em linguagem natural. A LLM interpreta a consulta e apresenta os resultados.
            </p>

            <textarea id="questionInput" placeholder="Ex.: compare ICMS e FECOP por decêndio entre setembro de 2025 e setembro de 2026"></textarea>
            <br />
            <button onclick="enviarPergunta()">Gerar resposta</button>

            <div class="examples">
                <div class="muted">Experimente consultas com a LLM:</div>
                <span class="example-chip" onclick="usarExemplo('Mostre a composição de ICMS e FECOP por decêndio em dezembro de 2025.')">ICMS/FECOP · dez/2025</span>
                <span class="example-chip" onclick="usarExemplo('Compare a composição de ICMS e FECOP por decêndio entre setembro de 2025 e setembro de 2026.')">ICMS/FECOP · set/25 × set/26</span>
                <span class="example-chip" onclick="usarExemplo('Quanto arrecadamos de FECOP no segundo decêndio de dezembro de 2025?')">FECOP · 2º decêndio</span>


                <span class="example-chip" onclick="usarExemplo('Mostre a arrecadação de ICMS por decêndio em setembro de 2026.')">
                    Decêndios · ICMS set/2026
                </span>

                <span class="example-chip" onclick="usarExemplo('Quanto arrecadamos de ICMS no segundo decêndio de setembro de 2026?')">
                    2º decêndio · ICMS
                </span>

                <span class="example-chip" onclick="usarExemplo('Compare a arrecadação de ICMS por decêndio entre agosto e setembro de 2026.')">
                    Decêndios · ago × set/2026
                </span>

                <span class="example-chip" onclick="usarExemplo('Compare o terceiro decêndio de agosto com o terceiro decêndio de setembro de 2026.')">
                    3º decêndio · ago × set
                </span>

                <span class="example-chip" onclick="usarExemplo('Qual foi o total arrecadado de ICMS em setembro de 2026?')">
                    Total de ICMS · set/2026
                </span>

                <span class="example-chip" onclick="usarExemplo('Quanto arrecadamos em cada decêndio de setembro de 2026?')">
                    Decêndios · todas as receitas
                </span>

                <span class="example-chip" onclick="usarExemplo('Quais segmentos arrecadaram mais com ICMS em abril de 2026?')">
                    Segmentos · ICMS abr/2026
                </span>

                <span class="example-chip" onclick="usarExemplo('Quais receitas do subgrupo ICMS arrecadaram mais em maio de 2026?')">
                    Receitas do ICMS · mai/2026
                </span>

                <span class="example-chip" onclick="usarExemplo('Quais subgrupos de receita tiveram maior arrecadação em junho de 2026?')">
                    Subgrupos · jun/2026
                </span>

                <span class="example-chip" onclick="usarExemplo('Mostre como a arrecadação de ICMS evoluiu mês a mês nos últimos seis meses.')">
                    Evolução mensal · ICMS
                </span>

            </div>

            <div id="loading">Gerando resposta...</div>

            <div id="errorBox"></div>

            <div id="resultado" style="display:none;">
                <div class="section">
                    <div class="label">Pergunta</div>
                    <div id="questionText"></div>
                </div>

                <div class="section">
                    <div class="label">Interpretação da pergunta (LLM)</div>
                    <p class="muted">QuerySpec executado:</p>
                    <pre id="interpretedQuery"></pre>
                </div>

                <div class="section">
                    <div class="label">SQL gerado</div>
                    <pre id="sqlText"></pre>
                </div>                

                <div class="section">
                    <div class="label">Resumo textual</div>
                    <div id="summaryText"></div>
                </div>

                <div class="section">
                    <div class="label">Dados brutos</div>
                    <pre id="rawData"></pre>
                </div>

                <div class="section">
                    <div class="label">Tabela</div>
                    <div id="tableContainer"></div>
                </div>                

                <div class="section">
                    <div class="label">Gráficos</div>
                    <div id="chartsContainer" class="charts-grid" style="display:none;"></div>
                    <div id="chart"></div>
                    <div id="initialFeedback" class="feedback-row feedback-inicial" role="group" aria-label="Avaliação do relatório"></div>
                </div>
                <div class="section">
                    <div class="label">Continue conversando com os dados</div>
                    <p class="muted">Pergunte sobre o resultado ou solicite outra comparação, filtro ou gráfico.</p>
                    <div id="chatMessages" aria-live="polite"></div>
                    <div class="chat-input-row">
                        <input id="chatQuestion" type="text"
                            placeholder="Ex.: qual decêndio cresceu mais? Ou compare com o mês anterior"
                            onkeydown="if(event.key==='Enter') enviarContinuacao();" />
                        <button id="chatSend" onclick="enviarContinuacao()">Enviar</button>
                    </div>
                </div>
            </div>
        </div>

        <script>
            function usarExemplo(texto) {
                document.getElementById("questionInput").value = texto;
            }

            function mostrarErro(msg) {
                const errorBox = document.getElementById("errorBox");
                errorBox.style.display = "block";
                errorBox.textContent = msg;
            }

            function esconderErro() {
                const errorBox = document.getElementById("errorBox");
                errorBox.style.display = "none";
                errorBox.textContent = "";
            }

            function mostrarLoading() {
                document.getElementById("loading").style.display = "block";
            }

            function esconderLoading() {
                document.getElementById("loading").style.display = "none";
            }

            const rotulosTabela = {
                decendio: "Decêndio",
                total: "Total",
                valor_arrecadado: "Valor arrecadado (R$)",
                qtd_documentos: "Documentos pagos",
                diferenca: "Diferença (R$)",
                variacao_percentual: "Variação (%)",
                tendencia: "Tendência",
                segmento: "Segmento econômico",
                subgrupo: "Subgrupo de receita",
                receita: "Receita",
                codigo_receita: "Código da receita",
                data_pagamento: "Data de pagamento",
                mes: "Mês",
                periodo: "Período",
                icms_a: "ICMS (A) — R$",
                fecop_b: "FECOP (B) — R$",
                icms_sem_fecop_c: "ICMS sem FECOP (C) — R$",
                icms_liquido_tesouro_d: "ICMS líquido Tesouro (D) — R$"
            };

            function escaparHtml(valor) {
                return String(valor).replace(/[&<>"']/g, caractere => ({
                    "&": "&amp;", "<": "&lt;", ">": "&gt;",
                    '"': "&quot;", "'": "&#39;"
                })[caractere]);
            }

            function rotuloColuna(coluna) {
                if (rotulosTabela[coluna]) return rotulosTabela[coluna];
                const periodo = coluna.match(/^(janeiro|fevereiro|marco|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)_([0-9]{4})$/i);
                if (periodo) {
                    const mes = periodo[1].charAt(0).toUpperCase() + periodo[1].slice(1);
                    return mes + "/" + periodo[2];
                }
                return coluna.replace(/_/g, " ");
            }

            function formatarValor(coluna, valor) {
                if (valor === null || valor === undefined) return "—";
                if (typeof valor !== "number") return String(valor);

                if (coluna === "variacao_percentual") {
                    return valor.toLocaleString("pt-BR", {
                        minimumFractionDigits: 2, maximumFractionDigits: 2
                    }) + "%";
                }
                if (coluna === "qtd_documentos" || coluna === "codigo_receita") {
                    return valor.toLocaleString("pt-BR", {maximumFractionDigits: 0});
                }
                return valor.toLocaleString("pt-BR", {
                    minimumFractionDigits: 2, maximumFractionDigits: 2
                });
            }

            function renderizarTabela(dados) {
                const container = document.getElementById("tableContainer");
                if (!dados || dados.length === 0) {
                    container.innerHTML = "<p>Nenhum dado encontrado.</p>";
                    return;
                }
                const colunas = Object.keys(dados[0]);
                const comparacao = colunas.includes("variacao_percentual");
                let html = `<div class="table-scroll"><table class="data-table${comparacao ? " comparacao" : ""}">`;
                html += "<thead><tr>";
                colunas.forEach(coluna => {
                    const numerica = dados.some(row => typeof row[coluna] === "number");
                    html += `<th class="${numerica ? "numero" : ""}">${escaparHtml(rotuloColuna(coluna))}</th>`;
                });
                html += "</tr></thead><tbody>";
                dados.forEach(row => {
                    const totalGeral = row.decendio === "Total geral";
                    html += `<tr${totalGeral ? ' class="total-geral"' : ""}>`;
                    colunas.forEach(coluna => {
                        const valor = row[coluna];
                        const numerica = typeof valor === "number" ||
                            dados.some(item => typeof item[coluna] === "number");
                        const classe = numerica ? "numero" : "categoria";
                        html += `<td class="${classe}">${escaparHtml(formatarValor(coluna, valor))}</td>`;
                    });
                    html += "</tr>";
                });
                html += "</tbody></table></div>";
                container.innerHTML = html;
            }

            let conversaAtual = null;
            let historicoChat = [];
            let sessaoId = (typeof crypto !== "undefined" && crypto.randomUUID)
                ? crypto.randomUUID() : null;
            let ultimaInteracaoId = null;
            const votosLocais = {};

            function criarFeedback(interactionId, container) {
                container.replaceChildren();
                if (!interactionId || !sessaoId) return;
                const texto = document.createElement("span");
                texto.className = "feedback-note";
                texto.textContent = "Esta resposta foi útil?";
                container.appendChild(texto);
                const botoes = [];
                for (const [voto, simbolo, rotulo] of [
                    ["positive", "👍", "Útil"], ["negative", "👎", "Não útil"]]) {
                    const botao = document.createElement("button");
                    botao.type = "button";
                    botao.className = "feedback-button";
                    botao.textContent = simbolo;
                    botao.title = rotulo;
                    botao.setAttribute("aria-label", rotulo);
                    botao.setAttribute("aria-pressed", votosLocais[interactionId] === voto ? "true" : "false");
                    if (votosLocais[interactionId] === voto) botao.classList.add("selected");
                    botao.onclick = async () => {
                        botoes.forEach(b => b.disabled = true);
                        try {
                            const resposta = await fetch("/feedback", {
                                method:"POST", headers:{"Content-Type":"application/json"},
                                body:JSON.stringify({session_id:sessaoId,
                                    interaction_id:interactionId, vote:voto})
                            });
                            if (!resposta.ok) throw new Error("HTTP " + resposta.status);
                            votosLocais[interactionId] = voto;
                            botoes.forEach(b => {
                                const ativo = b.dataset.voto === voto;
                                b.classList.toggle("selected", ativo);
                                b.setAttribute("aria-pressed", ativo ? "true" : "false");
                            });
                            texto.textContent = "Feedback registrado. Obrigado.";
                        } catch (erro) {
                            texto.textContent = "Não foi possível registrar o feedback.";
                        } finally { botoes.forEach(b => b.disabled = false); }
                    };
                    botao.dataset.voto = voto;
                    botoes.push(botao);
                    container.appendChild(botao);
                }
            }

            function adicionarMensagem(texto, classe, interactionId=null) {
                const painel = document.getElementById("chatMessages");
                const mensagem = document.createElement("div");
                mensagem.className = "chat-message " + classe;
                mensagem.textContent = texto;
                if (interactionId && (classe === "chat-assistant" || classe === "chat-error")) {
                    const envelope = document.createElement("div");
                    envelope.className = "chat-assistant-wrapper";
                    envelope.appendChild(mensagem);
                    const feedback = document.createElement("div");
                    feedback.className = "feedback-row";
                    criarFeedback(interactionId, feedback);
                    envelope.appendChild(feedback);
                    painel.appendChild(envelope);
                } else {
                    painel.appendChild(mensagem);
                }
                mensagem.scrollIntoView({behavior:"smooth", block:"nearest"});
            }

            async function atualizarRelatorio(data) {
                    document.getElementById("resultado").style.display = "block";
                    document.getElementById("questionText").textContent = data.question || document.getElementById("questionText").textContent;
                    document.getElementById("interpretedQuery").textContent = JSON.stringify(data.query_interpretada, null, 2);
                    document.getElementById("sqlText").textContent = data.sql || "SQL não disponível.";
                    document.getElementById("summaryText").textContent = (data.summary || "Sem resumo disponível.")
                        + (data.aviso_disponibilidade ? " " + data.aviso_disponibilidade : "");
                    document.getElementById("rawData").textContent = JSON.stringify(data.dados_brutos || [], null, 2);

                    renderizarTabela(data.dados_tabela || data.dados_brutos || []);
                    
                    const grade = document.getElementById("chartsContainer");
                    grade.replaceChildren();
                    const multiplo = Array.isArray(data.plotly_charts) && data.plotly_charts.length > 0;
                    grade.style.display = multiplo ? "grid" : "none";
                    document.getElementById("chart").style.display = multiplo ? "none" : "block";
                    if (multiplo) {
                        Plotly.purge("chart");
                        for (const grafico of data.plotly_charts) {
                            const painel = document.createElement("div");
                            painel.className = "chart-panel";
                            grade.appendChild(painel);
                            // Cada figura deve ocupar somente a largura de sua célula.
                            // Evita que um gráfico Plotly invada/recorte o gráfico vizinho.
                            const larguraPainel = Math.floor(painel.getBoundingClientRect().width);
                            const layoutPainel = {
                                ...(grafico.layout || {}),
                                autosize: false,
                                width: larguraPainel
                            };
                            await Plotly.newPlot(
                                painel,
                                grafico.data || [],
                                layoutPainel,
                                {responsive: true, displaylogo: false}
                            );
                        }
                    } else {
                        await Plotly.newPlot("chart", data.plotly_json.data || [],
                            data.plotly_json.layout || {}, {responsive: true});
                    }

            }

            async function enviarContinuacao() {
                const caixa = document.getElementById("chatQuestion");
                const pergunta = caixa.value.trim();
                if (!pergunta || !conversaAtual) return;
                caixa.value = "";
                adicionarMensagem(pergunta, "chat-user");
                const botao = document.getElementById("chatSend");
                botao.disabled = true;
                botao.textContent = "Analisando...";
                try {
                    const resposta = await fetch("/chat", {
                        method:"POST", headers:{"Content-Type":"application/json",
                            "X-Session-ID": sessaoId || "",
                            "X-Parent-Interaction-ID": ultimaInteracaoId || ""},
                        body:JSON.stringify({
                            question:pergunta,
                            previous_spec:conversaAtual.query_interpretada,
                            previous_data:(conversaAtual.dados_brutos || []).slice(0, 101),
                            history:historicoChat.slice(-8)
                        })
                    });
                    if (!resposta.ok) throw new Error("Falha HTTP " + resposta.status);
                    const dados = await resposta.json();
                    if (dados.session_id) sessaoId = dados.session_id;
                    if (dados.interaction_id) ultimaInteracaoId = dados.interaction_id;
                    if (dados.action === "error") {
                        adicionarMensagem(dados.error || "Não foi possível continuar.", "chat-error", dados.interaction_id);
                        return;
                    }
                    if (dados.action === "query") {
                        if (!dados.plotly_json) throw new Error("Nova consulta não retornou gráfico.");
                        dados.question = pergunta;
                        await atualizarRelatorio(dados);
                        conversaAtual = dados;
                        adicionarMensagem(dados.answer || "Consulta atualizada.", "chat-assistant", dados.interaction_id);
                    } else if (dados.action === "answer") {
                        adicionarMensagem(dados.answer, "chat-assistant", dados.interaction_id);
                    } else {
                        throw new Error("Resposta inesperada.");
                    }
                    historicoChat.push({user:pergunta, assistant:dados.answer || "Nova análise gerada."});
                    historicoChat = historicoChat.slice(-8);
                } catch (erro) {
                    adicionarMensagem("Erro ao continuar: " + erro.message, "chat-error");
                } finally {
                    botao.disabled = false;
                    botao.textContent = "Enviar";
                }
            }

            async function enviarPergunta() {
                const question = document.getElementById("questionInput").value.trim();

                if (!question) {
                    mostrarErro("Digite uma pergunta primeiro.");
                    return;
                }

                esconderErro();
                conversaAtual = null;
                ultimaInteracaoId = null;
                document.getElementById("initialFeedback").replaceChildren();
                mostrarLoading();
                document.getElementById("resultado").style.display = "none";

                try {
                    const response = await fetch("/ask", {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json",
                            "X-Session-ID": sessaoId || ""
                        },
                        body: JSON.stringify({ question })
                    });

                    if (!response.ok) {
                        const errorText = await response.text();
                        throw new Error("Falha na API: " + errorText);
                    }

                    const data = await response.json();
                    if (data.session_id) sessaoId = data.session_id;
                    if (data.interaction_id) ultimaInteracaoId = data.interaction_id;

                    if (data.error) {
                        document.getElementById("resultado").style.display = "block";
                        document.getElementById("questionText").textContent = data.question || "";
                        document.getElementById("interpretedQuery").textContent = data.query_interpretada
                            ? JSON.stringify(data.query_interpretada, null, 2)
                            : "Nenhuma consulta executada.";
                        document.getElementById("sqlText").textContent = "SQL não executado.";
                        document.getElementById("summaryText").textContent = data.error_type === "period_unavailable"
                            ? "Consulta não executada: período sem dados disponíveis."
                            : "Não foi possível executar a consulta.";
                        document.getElementById("rawData").textContent = "[]";
                        document.getElementById("tableContainer").textContent = "";
                        Plotly.purge("chart");
                        document.getElementById("chartsContainer").replaceChildren();
                        mostrarErro(data.error);
                        // Sem gráficos, reposiciona a avaliação após o resumo do erro.
                        document.getElementById("summaryText").after(document.getElementById("initialFeedback"));
                        criarFeedback(data.interaction_id, document.getElementById("initialFeedback"));
                        return;
                    }
                    if (!data.query_interpretada || !data.plotly_json) {
                        throw new Error("Não foi possível interpretar a pergunta com os dados esperados.");
                    }

                    conversaAtual = data;
                    historicoChat = [];
                    document.getElementById("chatMessages").replaceChildren();
                    await atualizarRelatorio(data);
                    document.getElementById("chart").after(document.getElementById("initialFeedback"));
                    criarFeedback(data.interaction_id, document.getElementById("initialFeedback"));
                    adicionarMensagem("Resultado carregado. Você pode fazer perguntas ou pedir outra análise.", "chat-assistant");

                } catch (error) {
                    mostrarErro(
                        "Não consegui interpretar ou processar sua pergunta. " +
                        "Verifique a pergunta e tente novamente. " +
                        "Detalhe técnico: " + error.message
                    );
                } finally {
                    esconderLoading();
                }
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)