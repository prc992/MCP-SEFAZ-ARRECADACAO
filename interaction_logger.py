"""Faro: log de auditoria JSONL e telemetria de qualidade, versão 2.

Mantém as assinaturas públicas anteriores. Não instrumenta etapas do pipeline
automaticamente: use registrar_etapa(...) no ponto real de execução.
Dados financeiros, SQL literal, prompts de sistema e chaves não são registrados.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import unicodedata

_LOG = logging.getLogger(__name__)
_LOCK = RLock()
BASE = Path(os.getenv('INTERACTION_LOG_DIR', str(Path(__file__).resolve().parent / 'logs_interacoes')))
SCHEMA_VERSION = 2

_EMAIL = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
_CPF = re.compile(r'(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)')
_CNPJ = re.compile(r'(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)')
_PHONE = re.compile(r'(?<!\d)(?:\+?55\s*)?\(?\d{2}\)?[\s-]?9?\d{4}[\s-]?\d{4}(?!\d)')
_AUTH = re.compile(r'(?i)\b(bearer\s+)[A-Za-z0-9._~+/-]+')


def novo_id() -> str:
    return str(uuid4())


def validar_id(valor: str | None) -> str | None:
    if not valor:
        return None
    try:
        return str(UUID(str(valor)))
    except (ValueError, TypeError, AttributeError):
        return None


def _texto_seguro(valor: object, limite: int = 2000) -> str:
    texto = str(valor or '')
    texto = _EMAIL.sub('[EMAIL]', texto)
    texto = _CNPJ.sub('[CNPJ]', texto)
    texto = _CPF.sub('[CPF]', texto)
    texto = _PHONE.sub('[TELEFONE]', texto)
    texto = _AUTH.sub(r'\1[REDACTED]', texto)
    return texto[:limite]


def _normalizar_pergunta(texto: str) -> str:
    texto = unicodedata.normalize('NFKD', texto.casefold())
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r'\b\d{4}-\d{2}-\d{2}\b', '[data]', texto)
    texto = re.sub(r'\b\d+\b', '[n]', texto)
    return ' '.join(re.findall(r'[a-z]+|\[[a-z]+\]', texto))[:500]


def _identidade_cliente(ip: str | None) -> dict:
    """Jamais registra IP completo por padrão. HMAC requer segredo persistente."""
    if not ip:
        return {'client_id': None, 'client_network': None}
    try:
        obj = ipaddress.ip_address(ip)
    except ValueError:
        return {'client_id': None, 'client_network': None}
    prefix = 24 if obj.version == 4 else 48
    rede = str(ipaddress.ip_network(f'{obj}/{prefix}', strict=False))
    segredo = os.getenv('INTERACTION_LOG_HMAC_KEY', '')
    identificador = hmac.new(segredo.encode(), str(obj).encode(), hashlib.sha256).hexdigest()[:20] if segredo else None
    return {'client_id': identificador, 'client_network': rede}


def _spec_compacto(spec: object) -> dict | None:
    if hasattr(spec, 'model_dump'):
        spec = spec.model_dump()
    if not isinstance(spec, dict):
        return None
    campos = ('metric', 'group_by', 'chart_type', 'top_n', 'order_desc', 'analysis_type',
              'report_type', 'months_back', 'start_date', 'end_date', 'period_1_start',
              'period_1_end', 'period_1_label', 'period_2_start', 'period_2_end',
              'period_2_label', 'segmento', 'subgrupo', 'receita', 'decendio')
    # Limites por campo: evita que um payload arbitrário contamine os logs.
    return {k: (_texto_seguro(spec[k], 150) if isinstance(spec[k], str) else spec[k])
            for k in campos if k in spec and (spec[k] is None or isinstance(spec[k], (str, bool, int, float)))}


def _categoria(spec: dict | None, texto: str) -> str:
    if spec:
        if spec.get('report_type') == 'icms_fecop':
            return 'demonstrativo_icms_fecop'
        if spec.get('analysis_type') == 'compare_periods':
            return 'comparacao_periodos'
        if spec.get('analysis_type') == 'time_series':
            return 'serie_temporal'
        if spec.get('group_by') == 'decendio':
            return 'decendios'
        if spec.get('group_by') in ('segmento',):
            return 'segmentos'
        if spec.get('group_by') in ('receita', 'codigo_receita', 'subgrupo'):
            return 'receitas'
        return 'agregacao'
    base = _normalizar_pergunta(texto)
    if any(x in base for x in ('compare', 'comparacao', 'diferenca', 'variacao')):
        return 'possivel_comparacao'
    if any(x in base for x in ('mes a mes', 'evolucao', 'tendencia')):
        return 'possivel_serie_temporal'
    return 'nao_classificada'


def _append(registro: dict) -> None:
    BASE.mkdir(mode=0o700, parents=True, exist_ok=True)
    agora = datetime.now(timezone.utc).astimezone()
    caminho = BASE / f'interacoes_{agora:%Y-%m-%d}.jsonl'
    evento = {'timestamp': agora.isoformat(timespec='milliseconds'),
              'schema_version': SCHEMA_VERSION, **registro}
    linha = json.dumps(evento, ensure_ascii=False, default=str, separators=(',', ':')) + '\n'
    with _LOCK:
        with caminho.open('a', encoding='utf-8') as arq:
            arq.write(linha)


def registrar_interacao(*, session_id: str, interaction_id: str,
                       parent_interaction_id: str | None, tipo: str, pergunta: str,
                       resposta: dict, duracao_ms: float, origem: str | None = None,
                       client_ip: str | None = None, **extras) -> None:
    """Compatível com a função antiga. `extras` não pode conter payloads arbitrários.

    Extras suportados: planner_mode, model_name, prompt_version,
    error_stage, http_status, context_rows, data_source, request_kind.
    """
    try:
        spec = _spec_compacto(resposta.get('query_interpretada'))
        sql = resposta.get('sql')
        acao = resposta.get('action') or ('error' if resposta.get('error') else 'query')
        erro = bool(resposta.get('error')) or acao == 'error'
        dados = resposta.get('dados_brutos') or []
        graf = resposta.get('plotly_charts') or []
        duracao = max(0.0, float(duracao_ms))
        texto = _texto_seguro(pergunta, 2000)
        normalizada = _normalizar_pergunta(texto)
        # Resposta detalhada completa é opt-in por conter informações derivadas dos dados.
        resposta_texto = resposta.get('answer') or resposta.get('summary') or resposta.get('error') or ''
        registro = {
            'event_type': 'interaction', 'session_id': validar_id(session_id) or session_id,
            **_identidade_cliente(client_ip),
            'interaction_id': validar_id(interaction_id) or interaction_id,
            'parent_interaction_id': validar_id(parent_interaction_id),
            'interaction_type': tipo, 'question': texto,
            'question_length': len(str(pergunta or '')),
            'question_normalized': normalizada,
            'question_signature': hashlib.sha256(normalizada.encode()).hexdigest()[:16],
            'question_category': _categoria(spec, texto),
            'answer': _texto_seguro(resposta_texto, 2000) if os.getenv('INTERACTION_LOG_INCLUDE_ANSWER') == '1' else None,
            'answer_length': len(str(resposta_texto)),
            'action': acao, 'answer_source': origem,
            'query_spec': spec,
            'sql_sha256': hashlib.sha256(sql.encode()).hexdigest() if isinstance(sql, str) else None,
            # SQL existente na resposta não comprova execução no banco; campo é tri-state.
            'sql_executed': extras.get('sql_executed') if isinstance(extras.get('sql_executed'), bool) else None,
            'sql_returned': isinstance(sql, str) and bool(sql.strip()),
            'row_count': len(dados) if isinstance(dados, list) else None,
            'chart_count': len(graf) if isinstance(graf, list) and graf else (1 if resposta.get('plotly_json') else 0),
            'duration_ms': round(duracao, 2),
            'performance_class': 'very_slow' if duracao >= 30000 else ('slow' if duracao >= 10000 else 'normal'),
            'status': 'error' if erro else 'success',
            'error_type': _texto_seguro(resposta.get('error_type'), 120) if resposta.get('error_type') else None,
            'availability_warning': bool(resposta.get('aviso_disponibilidade')),
            'missing_months_count': len(resposta.get('meses_ausentes') or []),
            'has_data': bool(dados),
            'feedback': None,  # votos são eventos posteriores; analisar por join de IDs
        }
        campos_extras = ('planner_mode', 'model_name', 'prompt_version', 'error_stage',
                         'http_status', 'context_rows', 'data_source', 'request_kind')
        for chave in campos_extras:
            valor = extras.get(chave)
            if isinstance(valor, (str, int, bool)) or valor is None:
                if valor is not None:
                    registro[chave] = _texto_seguro(valor, 120) if isinstance(valor, str) else valor
        if os.getenv('INTERACTION_LOG_INCLUDE_DATA') == '1':
            registro['data_snapshot'] = dados[:100] if isinstance(dados, list) else []
            registro['data_snapshot_truncated'] = isinstance(dados, list) and len(dados) > 100
        _append(registro)
    except Exception:
        _LOG.exception('Falha ao registrar interação')


def registrar_etapa(*, session_id: str, interaction_id: str, stage: str,
                    duration_ms: float, status: str = 'success',
                    error_type: str | None = None, details: dict | None = None) -> None:
    """Logar somente quando a etapa for REALMENTE medida pelo chamador.

    Exemplo: stage='llm_parse', 'availability', 'redshift_query',
             'chart_render', 'analysis_planner', 'analysis_engine'.
    """
    permitidos = {'llm_parse', 'availability', 'redshift_query', 'chart_render',
                  'analysis_planner', 'analysis_validator', 'analysis_engine',
                  'request_parse', 'redshift_connect', 'redshift_fetch', 'redshift_catalogs',
                  'query_engine', 'chat_routing', 'llm_chat', 'planner_llm',
                  'planner_mode', 'planner_outcome', 'planner_verdict',
                  'response_format', 'pdf_export', 'other'}
    if stage not in permitidos:
        raise ValueError('Etapa desconhecida')
    if status not in ('success', 'error', 'skipped'):
        raise ValueError('Status desconhecido')
    registro = {'event_type': 'stage', 'session_id': session_id,
                'interaction_id': interaction_id, 'stage': stage,
                'duration_ms': round(max(0.0, float(duration_ms)), 2),
                'status': status, 'error_type': _texto_seguro(error_type, 120) if error_type else None}
    # Informações seguras: pequenos contadores/flags, nunca SQL ou prompt.
    if isinstance(details, dict):
        whitelisted = {'row_count', 'cache_hit', 'retry_count', 'token_input',
                       'token_output', 'model', 'planner_decision', 'operation', 'reason_code'}
        registro['details'] = {k: (_texto_seguro(v, 100) if isinstance(v, str) else v)
                               for k, v in details.items() if k in whitelisted
                               and isinstance(v, (str, int, bool, float))}
    try:
        _append(registro)
    except Exception:
        _LOG.exception('Falha ao registrar etapa')


def _interacao_existe(session_id: str, interaction_id: str) -> bool:
    if not BASE.exists():
        return False
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


def registrar_feedback(*, session_id: str, interaction_id: str, voto: str,
                       client_ip: str | None = None) -> bool:
    if voto not in ('positive', 'negative'):
        raise ValueError('Feedback inválido')
    sid, iid = validar_id(session_id), validar_id(interaction_id)
    if not sid or not iid:
        raise ValueError('Identificador inválido')
    with _LOCK:
        if not _interacao_existe(sid, iid):
            return False
        _append({'event_type': 'feedback', 'session_id': sid,
                 'interaction_id': iid, 'vote': voto,
                 **_identidade_cliente(client_ip)})
    return True


def registrar_evento_ui(*, session_id: str, action: str,
                         interaction_id: str | None = None) -> None:
    """API opcional para registrar ações; requer endpoint autorizado para ser usada."""
    allowed = {'select_chat', 'select_new_analysis', 'view_details',
               'pdf_download_start', 'pdf_download_success', 'pdf_download_error',
               'example_selected'}
    if action not in allowed:
        raise ValueError('Evento de UI inválido')
    try:
        _append({'event_type': 'ui_action', 'session_id': validar_id(session_id),
                 'interaction_id': validar_id(interaction_id), 'ui_action': action})
    except Exception:
        _LOG.exception('Falha ao registrar ação de UI')
