"""Sugestões associadas a interações reais; log JSONL separado, sem dados financeiros/SQL."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4
import json
import logging

import interaction_logger as logger

_LOCK = RLock()
_LOG = logging.getLogger(__name__)
_MAX_LINE = 256 * 1024


def _eventos_interacao(dias: int = 180):
    """Leitura limitada aos arquivos recentes de interações, inclusive anteriores ao envio."""
    base = Path(logger.BASE)
    if not base.exists():
        return []
    arquivos = sorted(base.glob('interacoes_????-??-??.jsonl'), reverse=True)[:dias]
    eventos = []
    for caminho in arquivos:
        with caminho.open(encoding='utf-8', errors='replace') as arq:
            for linha in arq:
                if len(linha) > _MAX_LINE:
                    continue
                try:
                    item = json.loads(linha)
                except (ValueError, TypeError):
                    continue
                if isinstance(item, dict) and item.get('event_type') == 'interaction':
                    eventos.append(item)
    return eventos


def _contexto_interacao(session_id: str, interaction_id: str) -> dict | None:
    """Valida vínculo por sessão e encadeia até 12 interações para reprodução."""
    registros = {e.get('interaction_id'): e for e in _eventos_interacao()
                 if e.get('session_id') == session_id and e.get('interaction_id')}
    if interaction_id not in registros:
        return None
    chain, current, vistos = [], interaction_id, set()
    while current and current not in vistos and len(chain) < 12:
        vistos.add(current)
        item = registros.get(current)
        if not item:
            break
        chain.append({
            'interaction_id': item.get('interaction_id'),
            'parent_interaction_id': item.get('parent_interaction_id'),
            'timestamp': item.get('timestamp'),
            'interaction_type': item.get('interaction_type'),
            'question': item.get('question'),
            'query_spec': item.get('query_spec'),
            'action': item.get('action'),
            'status': item.get('status'),
            'error_type': item.get('error_type'),
            'answer_source': item.get('answer_source'),
            'sql_sha256': item.get('sql_sha256'),
            'sql_executed': item.get('sql_executed'),
        })
        current = item.get('parent_interaction_id')
    chain.reverse()
    return {'interacao': chain[-1], 'historico': chain,
            'historico_incompleto': bool(current),
            'observacao': 'Reprodução: utilizar perguntas e QuerySpecs. SQL literal, dados e respostas integrais não são armazenados por padrão.'}


def registrar_sugestao(*, session_id: str, interaction_id: str, texto: str) -> dict | None:
    sid, iid = logger.validar_id(session_id), logger.validar_id(interaction_id)
    if not sid or not iid:
        return None
    conteudo = (texto or '').strip()
    if not 5 <= len(conteudo) <= 2000:
        raise ValueError('A sugestão deve ter entre 5 e 2000 caracteres.')
    with _LOCK:
        contexto = _contexto_interacao(sid, iid)
        if contexto is None:
            return None
        agora = datetime.now(timezone.utc).astimezone()
        evento = {
            'schema_version': 1,
            'event_type': 'suggestion',
            'suggestion_id': str(uuid4()),
            'timestamp': agora.isoformat(timespec='milliseconds'),
            'session_id': sid,
            'interaction_id': iid,
            'suggestion_text': logger._texto_seguro(conteudo, 2000),
            'contexto': contexto,
        }
        base = Path(logger.BASE)
        base.mkdir(mode=0o700, parents=True, exist_ok=True)
        arquivo = base / f'sugestoes_{agora:%Y-%m-%d}.jsonl'
        with arquivo.open('a', encoding='utf-8') as arq:
            arq.write(json.dumps(evento, ensure_ascii=False, separators=(',', ':')) + '\n')
    return {'suggestion_id': evento['suggestion_id'], 'timestamp': evento['timestamp']}


def listar_sugestoes(dias: int = 30, agora: datetime | None = None) -> list[dict]:
    agora = agora or datetime.now(timezone.utc).astimezone()
    inicio = agora.date() - timedelta(days=dias - 1)
    resultado = []
    for offset in range(dias):
        caminho = Path(logger.BASE) / f'sugestoes_{inicio + timedelta(days=offset)}.jsonl'
        if not caminho.is_file():
            continue
        with caminho.open(encoding='utf-8', errors='replace') as arq:
            for linha in arq:
                if len(linha) > _MAX_LINE:
                    continue
                try:
                    evento = json.loads(linha)
                except (ValueError, TypeError):
                    continue
                if isinstance(evento, dict) and evento.get('event_type') == 'suggestion':
                    resultado.append(evento)
    return sorted(resultado, key=lambda item: item.get('timestamp', ''), reverse=True)
