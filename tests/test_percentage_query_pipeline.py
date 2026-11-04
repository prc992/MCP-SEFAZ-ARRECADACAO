import unittest, sys, types
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from schemas import QuerySpec
from chart_engine import gerar_plotly_figure

redshift = sys.modules.setdefault('redshift_client', types.ModuleType('redshift_client'))
redshift.executar_sql = lambda sql: []
import query_engine

class TestQueryPipeline(unittest.TestCase):
    def setUp(self):
        self.rows=[{'mes':f'2026-{m:02d}','valor':v} for m,v in zip(range(3,10),[100,110,121,100,120,90,99])]
        self.kw=dict(metric='valor_arrecadado',group_by='mes',analysis_type='time_series',
                     chart_type='line',months_back=6,start_date='2026-04-01',end_date='2026-09-30')
    def test_query_six_display_months_seven_sql_months(self):
        s=QuerySpec(series_mode='percentage',**self.kw)
        with patch.object(query_engine,'executar_sql',return_value=self.rows) as sql:
            result=query_engine.executar_query(s)
        self.assertIn("a.dat_pagamento >= '2026-03-01'",sql.call_args.args[0])
        self.assertIn("a.dat_pagamento <= '2026-09-30'",sql.call_args.args[0])
        self.assertEqual(len(result['dados']),6)
        self.assertEqual(result['dados'][0]['variacao_percentual'],10)
        self.assertEqual(result['dados'][-1]['mes'],'2026-09')
    def test_absolute_regression(self):
        s=QuerySpec(series_mode='absolute',**self.kw)
        with patch.object(query_engine,'executar_sql',return_value=self.rows[1:]) as sql:
            r=query_engine.executar_query(s)
        self.assertIn("a.dat_pagamento >= '2026-04-01'",sql.call_args.args[0])
        self.assertNotIn('variacao_percentual',r['dados'][0])
        self.assertEqual(len(r['dados']),6)
        fig=gerar_plotly_figure(r['dados'],s)
        self.assertEqual(fig.layout.yaxis.title.text,'valor_arrecadado')
    def test_filter_preserved_in_percent(self):
        s=QuerySpec(series_mode='percentage',subgrupo='ICMS',**self.kw)
        with patch.object(query_engine,'executar_sql',return_value=self.rows) as sql:
            query_engine.executar_query(s)
        self.assertIn("LOWER(a.receita_class_subgrupo) LIKE LOWER('%ICMS%')",sql.call_args.args[0])

if __name__=='__main__':unittest.main()
