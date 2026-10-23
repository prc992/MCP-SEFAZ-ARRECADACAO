"""Registro de domínios; apenas a aplicação escolhe seu domínio padrão."""

def default_catalog():
    from .sefaz.catalog import SEFAZ_CATALOG
    return SEFAZ_CATALOG
