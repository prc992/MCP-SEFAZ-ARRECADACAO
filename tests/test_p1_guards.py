"""P1: ano corrente e rejeição de assuntos fora do domínio sem SQL de arrecadação."""
from datetime import date
from importlib import util
from pathlib import Path
import sys
from types import ModuleType

from schemas import QuerySpec

ROOT = Path(__file__).resolve().parents[1]


def test_ano_corrente_limita_intervalo_a_ultima_data(monkeypatch):
    # Importação isolada: não conecta ao Redshift.
    fake = ModuleType('redshift_client')
    fake.executar_sql = lambda sql: (_ for _ in ()).throw(AssertionError('SQL não esperado'))
    monkeypatch.setitem(sys.modules, 'redshift_client', fake)
    module_spec = util.spec_from_file_location('_p1_availability', ROOT / 'data_availability_service.py')
    module = util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    hoje = date.today()
    ultima = date(hoje.year, 9, 23)
    monkeypatch.setattr(module, 'cobertura_mensal', lambda: {
        f'{hoje.year}-01': date(hoje.year, 1, 31),
        f'{hoje.year}-09': ultima,
    })
    spec = QuerySpec(metric='valor_arrecadado', group_by='total',
                     start_date=f'{hoje.year}-01-01', end_date=f'{hoje.year}-12-31')
    adjusted, aviso = module.ajustar_ano_corrente(spec)
    assert adjusted.end_date == ultima.isoformat()
    assert spec.end_date == f'{hoje.year}-12-31'
    assert '23/09' in aviso


def test_periodo_historico_nao_e_alterado(monkeypatch):
    fake = ModuleType('redshift_client')
    fake.executar_sql = lambda sql: []
    monkeypatch.setitem(sys.modules, 'redshift_client', fake)
    module_spec = util.spec_from_file_location('_p1_availability_historical', ROOT / 'data_availability_service.py')
    module = util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'cobertura_mensal', lambda: {'2025-09': date(2025, 9, 30)})
    spec = QuerySpec(metric='valor_arrecadado', group_by='total',
                     start_date='2025-01-01', end_date='2025-12-31')
    adjusted, aviso = module.ajustar_ano_corrente(spec)
    assert adjusted == spec and aviso is None


def test_contrato_dominio_aceita_rejeicao():
    spec = QuerySpec(metric='valor_arrecadado', group_by='total', domain_valid=False)
    assert spec.domain_valid is False


def test_serie_de_dois_anos_limita_fim_ao_ultimo_dado(monkeypatch):
    fake = ModuleType('redshift_client')
    fake.executar_sql = lambda sql: (_ for _ in ()).throw(AssertionError('SQL não esperado'))
    monkeypatch.setitem(sys.modules, 'redshift_client', fake)
    module_spec = util.spec_from_file_location('_p1_availability_cross_year', ROOT / 'data_availability_service.py')
    module = util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    hoje = date.today()
    anterior = hoje.year - 1
    ultima = date(hoje.year, 11, 12) if hoje.month >= 11 else date(hoje.year, 1, 12)
    cobertura = {f'{ano}-{mes:02d}': date(ano, mes, 15)
                 for ano in (anterior, hoje.year)
                 for mes in range(1, 13)
                 if ano < hoje.year or mes < ultima.month}
    cobertura[f'{hoje.year}-{ultima.month:02d}'] = ultima
    monkeypatch.setattr(module, 'cobertura_mensal', lambda: cobertura)
    spec = QuerySpec(metric='valor_arrecadado', group_by='mes', analysis_type='time_series',
                     start_date=f'{anterior}-01-01', end_date=f'{hoje.year}-12-31')
    adjusted, disponibilidade = module.preparar_consulta_temporal(spec)
    assert adjusted.start_date == f'{anterior}-01-01'
    assert adjusted.end_date == ultima.isoformat()
    assert disponibilidade['disponivel'] is True
    assert ultima.strftime('%d/%m/%Y') in disponibilidade['aviso']
    assert spec.end_date == f'{hoje.year}-12-31'
