import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

import faro_usage_dashboard as dashboard

NOW = datetime(2026, 11, 4, 16, 0, tzinfo=ZoneInfo('America/Fortaleza'))

def entry(type_, **fields):
    return {"timestamp": "2026-11-04T15:00:00-03:00", "event_type": type_, **fields}


def test_aggregates_mixed_events_and_deduplicates():
    events = [
        entry('page_view', page='faro', client_id='abc'),
        entry('interaction', interaction_id='1', session_id='sess', interaction_type='initial', status='success',
              duration_ms=2000, question='Qual a arrecadação de ICMS em 2026?', question_category='agregacao', answer_source='llm_query', client_id='abc'),
        entry('interaction', interaction_id='1', session_id='sess', interaction_type='initial', status='success',
              duration_ms=2000, question='Qual a arrecadação de ICMS em 2026?', question_category='agregacao', answer_source='llm_query', client_id='abc'),
        entry('interaction', interaction_id='2', session_id='sess', interaction_type='followup', status='error',
              duration_ms=10000, question_normalized='qual mes teve maior queda?', question_category='serie_temporal', client_id='abc'),
        entry('stage', interaction_id='2', stage='planner_llm', duration_ms=3000, status='error'),
        entry('stage', interaction_id='2', stage='planner_outcome', duration_ms=0, status='success', details={'planner_decision':'clarify'}),
        entry('feedback', interaction_id='1', vote='negative'),
        entry('feedback', interaction_id='1', vote='positive'),
        entry('feedback', interaction_id='2', vote='negative'),
    ]
    r = dashboard.aggregate_usage(events, 7, NOW)
    s = r['resumo']
    assert s['visitas_pagina'] == 1
    assert s['visitantes_pseudonimizados'] == 1
    assert s['perguntas'] == 2
    assert s['sessoes'] == 1
    assert s['sessoes_recentes_15min'] == 0
    assert s['identificadores_usuarios'] == 1
    assert s['consultas_iniciais'] == 1
    assert s['continuacoes'] == 1
    assert s['erros'] == 1
    assert s['taxa_erro_pct'] == 50
    assert s['feedback_positivo'] == 1 and s['feedback_negativo'] == 1
    assert r['decisoes_planner'] == [{'nome':'clarify','quantidade':1}]
    assert r['erros_por_etapa'] == [{'nome':'planner_llm','quantidade':1}]
    assert all('2026' not in x['pergunta_normalizada'] for x in r['perguntas_frequentes'])


def test_missing_ids_do_not_count_users():
    r = dashboard.aggregate_usage([entry('interaction', interaction_id='i', session_id='s', status='success')], 30, NOW)
    assert r['resumo']['identificadores_usuarios'] is None
    assert r['resumo']['sessoes'] == 1
    assert r['resumo']['visitas_pagina'] == 0
    assert r['resumo']['tempo_p95_s'] is None


def test_read_events_filters_dates_and_invalid(tmp_path):
    file = tmp_path / 'interacoes_2026-11-04.jsonl'
    with file.open('w', encoding='utf8') as f:
        f.write(json.dumps(entry('interaction', interaction_id='one'))+'\n')
        f.write('{invalid json\n')
        f.write(json.dumps({'timestamp':'2026-11-01T10:00:00-03:00','event_type':'interaction','interaction_id':'old'})+'\n')
    with patch.object(dashboard, '_log_dir', return_value=tmp_path):
        a, n = dashboard._read_events(2, NOW)
    assert len(a) == 1 and a[0]['interaction_id'] == 'one' and n == 1


def test_dashboard_fail_closed_and_auth():
    app = FastAPI()
    app.include_router(dashboard.router)
    client = TestClient(app)
    with patch.dict(os.environ, {'FARO_ADMIN_USER':'gestor','FARO_ADMIN_PASSWORD':'senha-teste'}, clear=False):
        assert client.get('/faro/admin').status_code == 401
        assert client.get('/faro/admin', auth=('gestor','incorreta')).status_code == 401
        r = client.get('/faro/admin', auth=('gestor','senha-teste'))
        assert r.status_code == 200 and 'Painel de uso' in r.text
        assert r.headers['cache-control'] == 'no-store'
        assert client.get('/faro/admin/api/uso?dias=2', auth=('gestor','senha-teste')).status_code == 422
        with patch.object(dashboard, '_read_events', return_value=([],0)):
            j = client.get('/faro/admin/api/uso?dias=7', auth=('gestor','senha-teste'))
        assert j.status_code == 200 and j.json()['resumo']['perguntas'] == 0
    with patch.dict(os.environ, {'FARO_ADMIN_USER':'','FARO_ADMIN_PASSWORD':''}, clear=False):
        assert client.get('/faro/admin').status_code == 503


def test_page_view_logger_records_no_raw_ip(tmp_path):
    import interaction_logger
    with patch.object(interaction_logger, 'BASE', tmp_path), patch.dict(os.environ, {'INTERACTION_LOG_HMAC_KEY':'test-secret'}, clear=False):
        interaction_logger.registrar_visita(pagina='faro', client_ip='172.30.199.69')
    logs = list(tmp_path.glob('interacoes_*.jsonl'))
    assert len(logs) == 1
    record = json.loads(logs[0].read_text(encoding='utf8').splitlines()[0])
    assert record['event_type'] == 'page_view'
    assert record['page'] == 'faro'
    assert record['client_id']
    assert record['client_network'] == '172.30.199.0/24'
    assert '172.30.199.69' not in json.dumps(record)
