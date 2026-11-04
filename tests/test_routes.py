"""Regression checks for /ask and /chat using stubbed external services.
No OpenAI, Redshift or HTTP requests are performed.
"""
import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from pydantic import BaseModel, ConfigDict

import interaction_logger

class Module(types.ModuleType):
    pass

def stub(name, **members):
    m=Module(name)
    m.__dict__.update(members)
    return m

class Model(BaseModel):
    model_config = ConfigDict(extra="allow")

class Request(BaseModel):
    question: str

class Client:
    host='127.0.0.1'

class FastRequest:
    client=Client()

class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Imported main.py stays intact; fake dependencies isolate the route contracts.
        cls.old={k:sys.modules.get(k) for k in (
            'schemas','query_engine','chart_engine','metadata_service','ask_service',
            'llm_service','data_availability_service','chat_service','pdf_report','main')}
        cls.spec=Model(metric='valor_arrecadado',group_by='mes',chart_type='line',analysis_type='time_series',report_type='standard')
        fake={
            'schemas':stub('schemas',QuerySpec=Model,AskRequest=Request),
            'query_engine':stub('query_engine',executar_query=lambda spec:{'dados':[{'mes':'2026-10','valor_arrecadado':12.4}], 'sql':'SELECT ...'}),
            'chart_engine':stub('chart_engine',gerar_plotly_figure=lambda *a:None,gerar_graficos_icms_fecop=lambda *a:[]),
            'metadata_service':stub('metadata_service',get_metadata=lambda:{}),
            'ask_service':stub('ask_service',gerar_summary=lambda spec:'summary'),
            'llm_service':stub('llm_service',interpretar_pergunta_llm=lambda q:cls.spec),
            'data_availability_service':stub('data_availability_service',preparar_consulta_temporal=lambda spec:(spec,{'disponivel':True,'aviso':None})),
            'chat_service':stub('chat_service',ChatRequest=Model,decidir_continuacao=lambda req:Model(action='answer',answer='Resposta',origin='deterministic'),_op=lambda req:'maximo'),
            'pdf_report':stub('pdf_report',PdfReportRequest=Model,gerar_pdf_relatorio=lambda req:b'pdf')
        }
        sys.modules.update(fake)
        cls.mod=importlib.import_module('main')
        # Plotly is irrelevant to route contracts in this test.
        cls.mod.preparar_graficos=lambda dados,spec:({'data':[], 'layout':{}},None)
    @classmethod
    def tearDownClass(cls):
        for k,old in cls.old.items():
            if old is None: sys.modules.pop(k,None)
            else: sys.modules[k]=old

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.pb=patch.object(interaction_logger,'BASE',Path(self.tmp.name));self.pb.start()
        self.addCleanup(self.pb.stop);self.addCleanup(self.tmp.cleanup)

    def events(self):
        return [json.loads(x) for f in Path(self.tmp.name).glob('*.jsonl') for x in f.read_text().splitlines()]

    def test_ask_success_preserves_response_and_tracks(self):
        out=self.mod.ask(Request(question='evolução'),FastRequest())
        self.assertEqual(out['dados_brutos'][0]['valor_arrecadado'],12.4)
        self.assertEqual(out['summary'],'summary')
        stages=[x['stage'] for x in self.events() if x['event_type']=='stage']
        self.assertEqual(stages,['request_parse','availability','query_engine','chart_render'])
        self.assertEqual(len([x for x in self.events() if x['event_type']=='interaction']),1)

    def test_ask_error_stage_and_no_query(self):
        with patch.object(self.mod,'interpretar_pergunta_llm',side_effect=ValueError('do not log')):
            out=self.mod.ask(Request(question='erro'),FastRequest())
        self.assertEqual(out['error_type'],'llm_failed')
        rec=next(x for x in self.events() if x['event_type']=='interaction')
        self.assertEqual(rec['error_stage'],'request_parse')
        self.assertNotIn('do not log',str(self.events()))

    def test_chat_answer_unchanged_and_parent(self):
        req=Model(question='e o maior?',previous_spec=self.spec,previous_data=[],history=[])
        out=self.mod.chat(req,FastRequest())
        self.assertEqual(out['action'],'answer')
        self.assertEqual(out['answer'],'Resposta')
        self.assertIn('chat_routing',[x.get('stage') for x in self.events()])

    def test_chat_query_records_query_engine(self):
        decision=Model(action='query',query_spec=self.spec)
        req=Model(question='outra consulta',previous_spec=self.spec,previous_data=[],history=[])
        with patch.object(self.mod,'decidir_continuacao',return_value=decision):
            out=self.mod.chat(req,FastRequest())
        self.assertEqual(out['action'],'query')
        self.assertIn('chart_render',[x.get('stage') for x in self.events()])

if __name__=='__main__':unittest.main()
