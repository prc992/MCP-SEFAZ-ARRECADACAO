import unittest
from unittest.mock import patch
from datetime import date
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from schemas import QuerySpec
from time_series_percentage import calcular_serie_percentual, PercentageSeriesError
from chart_engine import gerar_plotly_figure
from analysis.operations import consecutive_changes


def spec(**kw):
    return QuerySpec(metric='valor_arrecadado', group_by='mes', chart_type='line',
                     analysis_type='time_series', series_mode='percentage',
                     months_back=6, start_date='2026-04-01', end_date='2026-09-30', **kw)


def rows(nums, base='2026-03'):
    year, month = map(int, base.split('-'))
    return [{'mes': f'{year + (month - 1 + i)//12:04d}-{(month - 1 + i)%12 + 1:02d}',
             'valor_arrecadado': v} for i, v in enumerate(nums)]


class TestPercentageSeries(unittest.TestCase):
    def test_6_months_with_lookback_and_chart(self):
        data, note = calcular_serie_percentual(rows([100,110,121,100,120,90,99]),spec())
        self.assertEqual(len(data),6)
        self.assertEqual(data[0]['mes'],'2026-04')
        self.assertEqual(data[0]['variacao_percentual'],10)
        self.assertEqual(data[1]['variacao_percentual'],10)
        self.assertAlmostEqual(data[2]['variacao_percentual'],-17.355371900826448)
        self.assertIsNone(note)
        f=gerar_plotly_figure(data,spec())
        self.assertEqual(f.layout.yaxis.title.text,'Variação mensal (%)')
        self.assertEqual(list(f.data[0].y), [r['variacao_percentual'] for r in data])
        self.assertIn('Arrecadação', f.data[0].customdata[0])
    def test_missing_lookback(self):
        data,note=calcular_serie_percentual(rows([110,121,100,120,90,99],base='2026-04'),spec())
        self.assertIsNone(data[0]['variacao_percentual'])
        self.assertIn('mês anterior',note)
        self.assertAlmostEqual(data[1]['variacao_percentual'],10)
    def test_zero_reference(self):
        data,note=calcular_serie_percentual(rows([0,110,121,100,120,90,99]),spec())
        self.assertIsNone(data[0]['variacao_percentual'])
        self.assertIn('zero',note)
    def test_missing_filtered_month_is_not_zero(self):
        with self.assertRaises(PercentageSeriesError):
            calcular_serie_percentual(rows([100,110,121,100,120,90,99])[:-2] + rows([99],base='2026-09'),spec())
    def test_current_month_not_compared(self):
        now=date.today()
        idx=now.year*12 + now.month - 1
        begin=idx-2
        s=spec().model_copy(update={'start_date':f'{begin//12:04d}-{begin%12+1:02d}-01',
             'end_date':now.isoformat(),'months_back':3})
        m=begin-1
        v=[{'mes':f'{(m+i)//12:04d}-{(m+i)%12+1:02d}', 'valor_arrecadado':100*(i+1)} for i in range(4)]
        data,note=calcular_serie_percentual(v,s)
        self.assertIsNone(data[-1]['variacao_percentual'])
        self.assertIn('parcial',note)
    def test_legacy_queryspec_default(self):
        s=QuerySpec(metric='valor_arrecadado',group_by='mes',analysis_type='time_series')
        self.assertEqual(s.series_mode,'absolute')
        self.assertNotIn('percentage',consecutive_changes({'2026-03':100,'2026-04':110},'mes')[0][1])

if __name__=='__main__':unittest.main()
