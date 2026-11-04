"""Painel interno de uso do Faro, a partir dos eventos JSONL locais.

Endpoints: GET /faro/admin e GET /faro/admin/api/uso?dias=7|30|90.
Não modifica o pipeline conversacional e não expõe perguntas brutas, IPs ou IDs.
Acesso sem autenticação pela aplicação; restringir o acesso pela infraestrutura de rede.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import re
import unicodedata

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter(tags=["Faro - Administração"])
_TZ = ZoneInfo("America/Fortaleza")
_ALLOWED_DAYS = (7, 30, 90)
_MAX_LINE_LENGTH = 256 * 1024  # proteção contra linhas de log anormais


def _date(timestamp: object) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if d.tzinfo is None:
            return None
        return d.astimezone(_TZ)
    except (ValueError, TypeError, OverflowError):
        return None


def _normalizar(text: object) -> str:
    text = unicodedata.normalize("NFKD", str(text or "").casefold())
    text = "".join(x for x in text if not unicodedata.combining(x))
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.\w+\b", "[email]", text)
    text = re.sub(r"\b\d{2,}\b", "[n]", text)
    text = re.sub(r"[^a-z\[\] ]+", " ", text)
    return " ".join(text.split())[:170]


def _percentile(nums: list[float], p: float) -> float | None:
    if not nums:
        return None
    s = sorted(nums)
    i = (len(s) - 1) * p
    a = int(i)
    b = min(a + 1, len(s) - 1)
    return round(s[a] + (s[b] - s[a]) * (i - a), 1)


def _log_dir() -> Path:
    # Usa exatamente o mesmo diretório configurado no logger da aplicação.
    from interaction_logger import BASE
    return Path(BASE)


def _read_events(days: int, now: datetime) -> tuple[list[dict], int]:
    base = _log_dir()
    if not base.exists():
        return [], 0
    first_day = now.date() - timedelta(days=days - 1)
    events: list[dict] = []
    invalid = 0
    for n in range(days):
        day = first_day + timedelta(days=n)
        path = base / f"interacoes_{day.isoformat()}.jsonl"
        if not path.is_file():
            continue
        with path.open("r", encoding="utf-8", errors="replace") as file:
            for line in file:
                if len(line) > _MAX_LINE_LENGTH:
                    invalid += 1
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    invalid += 1
                    continue
                if not isinstance(event, dict):
                    invalid += 1
                    continue
                stamped = _date(event.get("timestamp"))
                if stamped is None or not (first_day <= stamped.date() <= now.date()):
                    continue
                if event.get("event_type") not in ("interaction", "stage", "feedback", "page_view"):
                    continue
                events.append(event)
    return events, invalid


def aggregate_usage(events: list[dict], days: int = 30, now: datetime | None = None, invalid: int = 0) -> dict:
    """Pure-ish aggregator for tests. Only authorized aggregate metrics leave API."""
    now = (now or datetime.now(_TZ)).astimezone(_TZ)
    days = int(days)
    start = now.date() - timedelta(days=days - 1)
    interactions: dict[str, dict] = {}
    stages: list[dict] = []
    feedback: dict[str, str] = {}
    stage_events = 0
    visits = []
    for item in events:
        type_ = item.get("event_type")
        ident = item.get("interaction_id")
        if type_ == "interaction" and ident:
            # Registros duplicados: mantém o último gravado.
            interactions[str(ident)] = item
        elif type_ == "page_view":
            visits.append(item)
        elif type_ == "stage":
            stage_events += 1
            stages.append(item)
        elif type_ == "feedback" and ident and item.get("vote") in ("positive", "negative"):
            feedback[str(ident)] = item["vote"]

    records = list(interactions.values())
    count = len(records)
    sessions = {str(r["session_id"]) for r in records if r.get("session_id")}
    identities = {str(r["client_id"]) for r in records if r.get("client_id")}
    identified_count = sum(bool(r.get("client_id")) for r in records)
    visitor_ids = {str(v["client_id"]) for v in visits if v.get("client_id")}
    visited_identified = sum(bool(v.get("client_id")) for v in visits)
    active_threshold = now - timedelta(minutes=15)
    recent_sessions = {str(r["session_id"]) for r in records
                       if r.get("session_id") and (_date(r.get("timestamp")) or now - timedelta(days=100)) >= active_threshold}
    errors = [r for r in records if r.get("status") == "error" or r.get("action") == "error"]
    error_ids = {str(r.get("interaction_id")) for r in errors}
    durations = [float(r["duration_ms"]) / 1000 for r in records
                 if isinstance(r.get("duration_ms"), (float, int)) and r["duration_ms"] >= 0]
    initial = sum(r.get("interaction_type") == "initial" for r in records)
    followups = sum(r.get("interaction_type") == "followup" for r in records)
    daily = Counter()
    daily_errors = Counter()
    category = Counter()
    frequent = Counter()
    origin = Counter()
    for r in records:
        dt = _date(r.get("timestamp"))
        if dt:
            key = dt.date().isoformat()
            daily[key] += 1
            if str(r.get("interaction_id")) in error_ids:
                daily_errors[key] += 1
        category[str(r.get("question_category") or "Não classificada")] += 1
        question = _normalizar(r.get("question_normalized") or r.get("question"))
        if question:
            frequent[question] += 1
        if r.get("answer_source"):
            origin[str(r["answer_source"])] += 1

    stage_failed = Counter()
    stage_duration = defaultdict(list)
    planner = Counter()
    for s in stages:
        stage = str(s.get("stage", ""))
        if s.get("status") == "error":
            stage_failed[stage] += 1
        if isinstance(s.get("duration_ms"), (int, float)) and s["duration_ms"] >= 0:
            # São tempos de execução medidos e potencialmente ANINHADOS.
            stage_duration[stage].append(s["duration_ms"])
        if stage == "planner_outcome":
            value = (s.get("details") or {}).get("planner_decision")
            if value:
                planner[str(value)] += 1

    votes = Counter(feedback.get(ident) for ident in interactions if feedback.get(ident))
    top_questions = [{"pergunta_normalizada": k, "quantidade": v}
                     for k, v in frequent.most_common(12)]
    dates = [start + timedelta(days=n) for n in range(days)]
    return {
        "periodo": {"dias": days, "inicio": start.isoformat(), "fim": now.date().isoformat(),
                    "atualizado_em": now.isoformat(timespec="seconds")},
        "resumo": {"perguntas": count, "visitas_pagina": len(visits),
                   "visitantes_pseudonimizados": len(visitor_ids) if visits and visited_identified == len(visits) else None,
                   "sessoes_recentes_15min": len(recent_sessions), "sessoes": len(sessions),
                   "identificadores_usuarios": len(identities) if identified_count == count and count else None,
                   "interacoes_com_identificador": identified_count,
                   "consultas_iniciais": initial, "continuacoes": followups,
                   "erros": len(errors),
                   "taxa_erro_pct": round(100 * len(errors) / count, 1) if count else None,
                   "tempo_mediano_s": _percentile(durations, .5),
                   "tempo_p95_s": _percentile(durations, .95),
                   "feedback_positivo": votes.get("positive", 0),
                   "feedback_negativo": votes.get("negative", 0),
                   "taxa_positiva_pct": round(100 * votes.get("positive", 0) / sum(votes.values()), 1) if votes else None},
        "diario": [{"data": day.isoformat(), "perguntas": daily[day.isoformat()],
                    "erros": daily_errors[day.isoformat()]} for day in dates],
        "perguntas_frequentes": top_questions,
        "categorias": [{"nome": k, "quantidade": n} for k, n in category.most_common(10)],
        "origens": [{"nome": k, "quantidade": n} for k, n in origin.most_common()],
        "erros_por_etapa": [{"nome": k, "quantidade": n} for k, n in stage_failed.most_common(10)],
        "etapas_lentas": [{"etapa": k, "p95_ms": _percentile(values, .95), "amostras": len(values)}
                          for k, values in sorted(stage_duration.items(),
                                                  key=lambda kv: _percentile(kv[1], .95) or 0, reverse=True)[:10]],
        "decisoes_planner": [{"nome": k, "quantidade": n} for k, n in planner.most_common()],
        "qualidade": {"eventos_etapa": stage_events, "linhas_invalidas": invalid,
                      "feedback_avaliado": sum(votes.values()),
                      "observacao_usuarios": ("Identificadores de usuários e visitantes são pseudônimos por HMAC; "
                          "não representam necessariamente pessoas distintas."
                          if identities else
                          "Sem identificadores HMAC: apenas sessões distintas podem ser estimadas, "
                          "não pessoas distintas."),
                      "observacao_status": "Esclarecimentos podem constar como sucesso técnico; "
                                           "consulte decisões do planejador separadamente.",
                      "observacao_tempo": "Durações das etapas podem ser aninhadas; não somar os valores."}
    }


@router.get("/faro/admin", response_class=HTMLResponse)
def admin_home():
    html = (Path(__file__).resolve().parent / "templates" / "faro_admin.html").read_text(encoding="utf-8")
    return HTMLResponse(html, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                      "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY"})


@router.get("/faro/admin/api/uso")
def admin_usage(dias: int = Query(default=30, description="Janela de 7, 30 ou 90 dias")):
    if dias not in _ALLOWED_DAYS:
        raise HTTPException(status_code=422, detail="Escolha 7, 30 ou 90 dias")
    now = datetime.now(_TZ)
    events, invalid = _read_events(dias, now)
    result = aggregate_usage(events, dias, now, invalid)
    return JSONResponse(result, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/faro/admin/api/sugestoes")
def admin_suggestions(dias: int = Query(default=30, description="7, 30 ou 90 dias")):
    if dias not in _ALLOWED_DAYS:
        raise HTTPException(status_code=422, detail="Escolha 7, 30 ou 90 dias")
    from suggestion_service import listar_sugestoes
    registros = listar_sugestoes(dias=dias)
    # Somente dashboard interno; restringir por firewall/proxy.
    return JSONResponse({"total": len(registros), "sugestoes": registros},
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
