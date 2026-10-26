from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
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

# Imagem original do Faro, servida como recurso estatico pelo proprio FastAPI.
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


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
    """Serve o Playground do Faro sem misturar apresentação e endpoints."""
    html = (BASE_DIR / "templates" / "playground.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)
