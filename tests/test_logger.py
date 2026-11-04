import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('faro_logger_test', ROOT / 'interaction_logger.py')
logger = importlib.util.module_from_spec(spec)
spec.loader.exec_module(logger)

class LoggerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.oldbase = logger.BASE
        logger.BASE = Path(self.temp.name)
        self.sid = str(uuid4()); self.iid = str(uuid4())

    def tearDown(self):
        logger.BASE = self.oldbase
        self.temp.cleanup()

    def events(self):
        return [json.loads(x) for f in logger.BASE.glob('*.jsonl') for x in f.read_text(encoding='utf8').splitlines()]

    def test_compatibilidade_e_privacidade(self):
        with patch.dict(os.environ, {'INTERACTION_LOG_HMAC_KEY':'segredo-para-testes'}, clear=False):
            logger.registrar_interacao(session_id=self.sid, interaction_id=self.iid,
                parent_interaction_id=None, tipo='initial',
                pergunta='Mostre ICMS para abc@sefaz.gov.br CPF 123.456.789-00',
                resposta={'query_interpretada': {'analysis_type':'time_series','group_by':'mes', 'metric':'valor_arrecadado'},
                         'dados_brutos':[{'valor_arrecadado':100}], 'plotly_json':{'data':[]},
                         'sql':'SELECT * FROM segredo', 'summary':'total R$ 100'},
                duracao_ms=31424, origem='llm_query', client_ip='172.30.199.69')
        event, = self.events()
        self.assertEqual(event['schema_version'], 2)
        self.assertEqual(event['performance_class'], 'very_slow')
        self.assertEqual(event['question_category'], 'serie_temporal')
        self.assertEqual(event['row_count'], 1)
        self.assertEqual(event['client_network'], '172.30.199.0/24')
        self.assertNotIn('172.30.199.69', json.dumps(event))
        self.assertNotIn('abc@sefaz.gov.br', json.dumps(event))
        self.assertNotIn('123.456.789-00', json.dumps(event))
        self.assertNotIn('SELECT *', json.dumps(event))
        self.assertIsNone(event['sql_executed'])
        self.assertIsNone(event['answer'])

    def test_feedback_e_etapa(self):
        logger.registrar_interacao(session_id=self.sid, interaction_id=self.iid,
            parent_interaction_id=None, tipo='initial', pergunta='Total por segmento',
            resposta={'dados_brutos':[]}, duracao_ms=10)
        self.assertTrue(logger.registrar_feedback(session_id=self.sid, interaction_id=self.iid, voto='negative'))
        logger.registrar_etapa(session_id=self.sid, interaction_id=self.iid, stage='llm_parse',
                              duration_ms=1500, details={'token_input':123, 'secret_key':'not-saved'})
        self.assertEqual(len(self.events()), 3)
        self.assertNotIn('not-saved', json.dumps(self.events()))

    def test_sem_ip_invalido(self):
        self.assertIsNone(logger._identidade_cliente('abc')['client_id'])

if __name__ == '__main__':
    unittest.main()
