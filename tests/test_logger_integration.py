"""Testes de integração do logger com main, observability e dashboard (sem Redshift/LLM)."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import interaction_logger as log
import faro_usage_dashboard as dash
from observability import medir, request_context


class LoggerIntegrationTest(unittest.TestCase):
    def test_contracts(self):
        for name in ('BASE', 'novo_id', 'validar_id', 'registrar_interacao',
                     'registrar_feedback', 'registrar_visita', 'registrar_etapa'):
            self.assertTrue(hasattr(log, name), name)

    def test_events_dashboard_and_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(log, 'BASE', Path(tmp)):
                sid, iid = log.novo_id(), log.novo_id()
                log.registrar_visita(pagina='faro', client_ip='10.1.2.3')
                with request_context(sid, iid):
                    with medir('request_parse'):
                        pass
                log.registrar_interacao(
                    session_id=sid, interaction_id=iid, parent_interaction_id=None,
                    tipo='initial', pergunta='Qual a arrecadação de ICMS?',
                    resposta={'summary': 'Resumo', 'dados_brutos': [{'valor_arrecadado': 123}]},
                    duracao_ms=25, origem='llm_query', client_ip='10.1.2.3',
                    planner_mode='active', model_name='gpt-4.1-mini', context_rows=1,
                    sql_executed=False)
                self.assertTrue(log.registrar_feedback(
                    session_id=sid, interaction_id=iid, voto='positive'))
                raw = [json.loads(line) for p in Path(tmp).glob('interacoes_*.jsonl')
                       for line in p.read_text(encoding='utf-8').splitlines()]
                kinds = {e['event_type'] for e in raw}
                self.assertEqual(kinds, {'interaction', 'stage', 'feedback', 'page_view'})
                with patch.object(dash, '_log_dir', return_value=Path(tmp)):
                    from datetime import datetime
                    data, invalid = dash._read_events(7, datetime.now(dash._TZ))
                    result = dash.aggregate_usage(data, 7)
                self.assertEqual(invalid, 0)
                self.assertEqual(result['resumo']['perguntas'], 1)
                self.assertEqual(result['resumo']['visitas_pagina'], 1)
                self.assertEqual(result['resumo']['feedback_positivo'], 1)
                self.assertEqual(result['qualidade']['eventos_etapa'], 1)
                self.assertTrue(all('client_ip' not in e for e in raw))


if __name__ == '__main__':
    unittest.main()
