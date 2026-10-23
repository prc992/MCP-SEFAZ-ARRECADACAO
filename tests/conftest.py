"""Stubs apenas se dependências não distribuídas no pacote de teste estiverem ausentes."""
import importlib.util
import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from types import ModuleType

if importlib.util.find_spec("catalog_service") is None:
    stub = ModuleType("catalog_service")
    stub.listar_segmentos = lambda: []
    stub.listar_subgrupos_receita = lambda: []
    sys.modules["catalog_service"] = stub


import pytest


@pytest.fixture(autouse=True)
def default_legacy_for_unit_tests(monkeypatch):
    """Independe do .env do projeto; cada teste opta por shadow/active quando preciso."""
    monkeypatch.setenv("ANALYSIS_PLANNER_MODE", "legacy")
