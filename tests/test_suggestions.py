import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import interaction_logger as logger
import suggestion_service as suggestions
import faro_usage_dashboard as dashboard


class SuggestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.patch = patch.object(logger, 'BASE', self.base)
        self.patch.start()
        self.sid = str(uuid4())
        self.id1 = str(uuid4())
        self.id2 = str(uuid4())
        logger.registrar_interacao(session_id=self.sid, interaction_id=self.id1,
            parent_interaction_id=None, tipo='initial', pergunta='Arrecadação em junho de 2026?',
            resposta={'query_interpretada':{'metric':'valor_arrecadado','group_by':'mes',
                'analysis_type':'time_series','start_date':'2026-06-01'},
                'sql':'SELECT sensitive FROM redshift', 'dados_brutos':[{'valor_arrecadado':10}],
                'summary':'Resumo financeiro'}, duracao_ms=50)
        logger.registrar_interacao(session_id=self.sid, interaction_id=self.id2,
            parent_interaction_id=self.id1, tipo='followup', pergunta='E no mês anterior?',
            resposta={'action':'answer','answer':'Informação da comparação'}, duracao_ms=5)

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_salva_separado_com_contexto_e_historico(self):
        saved = suggestions.registrar_sugestao(session_id=self.sid, interaction_id=self.id2,
                                               texto='Gostaria de comparar também com 2025.')
        self.assertTrue(saved['suggestion_id'])
        listed = suggestions.listar_sugestoes()
        self.assertEqual(len(listed),1)
        ctx=listed[0]['contexto']
        self.assertEqual([x['interaction_id'] for x in ctx['historico']],[self.id1,self.id2])
        self.assertEqual(ctx['historico'][0]['query_spec']['group_by'],'mes')
        self.assertFalse(ctx['historico_incompleto'])
        self.assertFalse(any('SELECT sensitive' in p.read_text(encoding='utf-8') for p in self.base.glob('sugestoes_*.jsonl')))
        self.assertFalse(any('Resumo financeiro' in p.read_text(encoding='utf-8') for p in self.base.glob('sugestoes_*.jsonl')))
        self.assertEqual(len(list(self.base.glob('sugestoes_*.jsonl'))),1)
        self.assertEqual(len(list(self.base.glob('interacoes_*.jsonl'))),1)

    def test_nao_vincula_a_outra_sessao(self):
        self.assertIsNone(suggestions.registrar_sugestao(
            session_id=str(uuid4()),interaction_id=self.id1,texto='Outra sugestão'))
        self.assertEqual(suggestions.listar_sugestoes(),[])

    def test_limites_e_redacao(self):
        with self.assertRaises(ValueError):
            suggestions.registrar_sugestao(session_id=self.sid, interaction_id=self.id1,texto='abc')
        with self.assertRaises(ValueError):
            suggestions.registrar_sugestao(session_id=self.sid, interaction_id=self.id1,texto='z'*2001)
        suggestions.registrar_sugestao(session_id=self.sid, interaction_id=self.id1,
                                       texto='Contato teste@exemplo.com, por favor.')
        self.assertIn('[EMAIL]',suggestions.listar_sugestoes()[0]['suggestion_text'])
        self.assertNotIn('teste@exemplo.com',suggestions.listar_sugestoes()[0]['suggestion_text'])

    def test_api_admin_lista_e_janela_valida(self):
        app=FastAPI()
        app.include_router(dashboard.router)
        c=TestClient(app)
        suggestions.registrar_sugestao(session_id=self.sid,interaction_id=self.id1,texto='Adicionar filtro de receita')
        resp=c.get('/faro/admin/api/sugestoes?dias=30')
        self.assertEqual(resp.status_code,200)
        self.assertEqual(resp.json()['total'],1)
        self.assertEqual(resp.json()['sugestoes'][0]['interaction_id'],self.id1)
        self.assertEqual(c.get('/faro/admin/api/sugestoes?dias=5').status_code,422)

    def test_logger_existente_e_dashboard_uso_inalterados(self):
        now=datetime.now(timezone.utc).astimezone()
        eventos, invalid=dashboard._read_events(7,now)
        self.assertEqual(invalid,0)
        self.assertEqual(dashboard.aggregate_usage(eventos,7,now)['resumo']['perguntas'],2)
        suggestions.registrar_sugestao(session_id=self.sid,interaction_id=self.id1,texto='Melhorar legenda')
        eventos2,_=dashboard._read_events(7,now)
        self.assertEqual(len(eventos),len(eventos2))


if __name__=='__main__': unittest.main()
