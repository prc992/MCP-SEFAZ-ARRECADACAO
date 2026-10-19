"""Auditoria append-only das interações do Playground (JSONL diário).

Não armazena automaticamente resultados fiscais brutos nem SQL literal.
A pasta local requer controles de acesso/retenção antes do uso em produção.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import UUID, uuid4
import hashlib
import json
import logging
import os

_LOG = logging.getLogger(__name__)
_LOCK = Lock()
BASE = Path(__file__).resolve().parent / 'logs_interacoes'


def novo_id() -> str:
    return str(uuid4())


def validar_id(valor: str | None) -> str | None:
    if not valor:
        return None
    try:
        return str(UUID(str(valor)))
    except (ValueError, TypeError, AttributeError):
        return None


def _append(registro: dict) -> None:
    BASE.mkdir(mode=0o700, parents=True, exist_ok=True)
    agora = datetime.now(timezone.utc).astimezone()
    caminho = BASE / f'interacoes_{agora:%Y-%m-%d}.jsonl'
    evento = {'timestamp': agora.isoformat(timespec='milliseconds'), **registro}
    linha = json.dumps(evento, ensure_ascii=False, default=str, separators=(',', ':')) + '\n'
    with _LOCK:
        # Uma escrita por evento, sem sobrescrever eventos anteriores.
        with caminho.open('a', encoding='utf-8') as arquivo:
            arquivo.write(linha)


def registrar_interacao(*, session_id: str, interaction_id: str,
                       parent_interaction_id: str | None, tipo: str, pergunta: str,
                       resposta: dict, duracao_ms: float, origem: str | None = None) -> None:
    try:
        spec = resposta.get('query_interpretada')
        sql = resposta.get('sql')
        mensagem = resposta.get('answer') or resposta.get('summary') or resposta.get('error') or ''
        registro = {
            'event_type': 'interaction', 'session_id': session_id,
            'interaction_id': interaction_id,
            'parent_interaction_id': parent_interaction_id,
            'interaction_type': tipo, 'question': pergunta,
            'answer': mensagem, 'action': resposta.get('action') or ('error' if resposta.get('error') else 'query'),
            'answer_source': origem,
            'query_spec': spec,
            'sql_sha256': hashlib.sha256(sql.encode('utf-8')).hexdigest() if isinstance(sql, str) else None,
            'sql_executed': bool(sql),
            'row_count': len(resposta.get('dados_brutos') or []),
            'chart_count': len(resposta.get('plotly_charts') or []) or (1 if resposta.get('plotly_json') else 0),
            'duration_ms': round(duracao_ms, 2),
            'status': 'error' if resposta.get('error') or resposta.get('action') == 'error' else 'success',
            'error_type': resposta.get('error_type'),
            'feedback': None,
        }
        if os.getenv('INTERACTION_LOG_INCLUDE_DATA') == '1':
            registro['data_snapshot'] = (resposta.get('dados_brutos') or [])[:100]
            registro['data_snapshot_truncated'] = len(resposta.get('dados_brutos') or []) > 100
        _append(registro)
    except Exception:
        _LOG.exception('Falha ao registrar interação')


def _interacao_existe(session_id: str, interaction_id: str) -> bool:
    # Limita busca a arquivos locais recentes. Evita aceitar votos para interações inexistentes.
    for caminho in sorted(BASE.glob('interacoes_*.jsonl'), reverse=True)[:90]:
        with caminho.open('r', encoding='utf-8') as arquivo:
            for linha in arquivo:
                try:
                    evento = json.loads(linha)
                except json.JSONDecodeError:
                    continue
                if (evento.get('event_type') == 'interaction'
                        and evento.get('session_id') == session_id
                        and evento.get('interaction_id') == interaction_id):
                    return True
    return False


def registrar_feedback(*, session_id: str, interaction_id: str, voto: str) -> bool:
    if voto not in ('positive', 'negative'):
        raise ValueError('Feedback inválido')
    if not validar_id(session_id) or not validar_id(interaction_id):
        raise ValueError('Identificador inválido')
    with _LOCK:
        if not _interacao_existe(session_id, interaction_id):
            return False
        _append_sem_lock_feedback(session_id, interaction_id, voto)
    return True


def _append_sem_lock_feedback(session_id, interaction_id, voto):
    # Evita lock recursivo durante a verificação e o append.
    BASE.mkdir(mode=0o700, parents=True, exist_ok=True)
    agora = datetime.now(timezone.utc).astimezone()
    caminho = BASE / f'interacoes_{agora:%Y-%m-%d}.jsonl'
    evento = {'timestamp': agora.isoformat(timespec='milliseconds'),
              'event_type': 'feedback', 'session_id': session_id,
              'interaction_id': interaction_id, 'vote': voto}
    with caminho.open('a', encoding='utf-8') as arquivo:
        arquivo.write(json.dumps(evento, ensure_ascii=False) + '\n')
