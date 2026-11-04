"""Primitivas matemáticas puras; compartilháveis por futuros motores e MCPs."""
from decimal import Decimal
from datetime import date, timedelta
import re


def rank_values(values: dict[str, Decimal | None], *, greatest: bool = True) -> str:
    """Chave do extremo; empate preserva a primeira ocorrência."""
    extreme = max if greatest else min
    return extreme(values, key=values.get)


def amplitude_values(values: dict[str, Decimal]):
    """Retorna categoria maior/menor e diferença absoluta entre extremos."""
    greatest = rank_values(values, greatest=True)
    smallest = rank_values(values, greatest=False)
    return greatest, smallest, values[greatest] - values[smallest]


def sum_others(values: dict[str, Decimal], category: str):
    """Soma as categorias distintas da selecionada (presume partição válida)."""
    others = sum((value for key, value in values.items() if key != category), Decimal(0))
    return values[category], others, values[category] - others


def period_changes(matrix: dict[str, tuple[Decimal, Decimal]]):
    """Calcula variações absolutas e percentuais com zero de referência indefinido."""
    deltas = {category: second - first for category, (first, second) in matrix.items()}
    percentages = {
        category: (second - first) * Decimal(100) / first if first != 0 else None
        for category, (first, second) in matrix.items()
    }
    return deltas, percentages


def extreme_period(first: Decimal, second: Decimal, first_label: str,
                   second_label: str, *, greatest: bool):
    """Empates: segundo período para máximo, primeiro para mínimo."""
    if greatest:
        return (second_label, second) if second >= first else (first_label, first)
    return (first_label, first) if first <= second else (second_label, second)


# Ordenação/adjacência comprovável, sem deduzir períodos a partir da posição da linha.
def temporal_key(label: str, dimension: str):
    text = str(label).strip()
    try:
        if dimension == "mes" and re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", text):
            ano, mes = map(int, text.split("-"))
            return ano * 12 + mes - 1
        if dimension == "data_pagamento" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return date.fromisoformat(text).toordinal()
    except ValueError:
        return None
    return None


def consecutive_changes(values: dict[str, Decimal], dimension: str):
    """Retorna [(anterior, atual, primeiro, segundo, delta, percentual)].

    Levanta ValueError se a série é ambígua, desordenável ou possui lacunas.
    """
    keyed = [(temporal_key(cat, dimension), cat, val) for cat, val in values.items()]
    if any(key is None for key, _, _ in keyed) or len({k for k, _, _ in keyed}) != len(keyed):
        raise ValueError("invalid_series")
    keyed.sort(key=lambda entry: entry[0])
    if len(keyed) < 2:
        raise ValueError("insufficient_periods")
    if any(b[0] != a[0] + 1 for a, b in zip(keyed, keyed[1:])):
        raise ValueError("nonconsecutive_periods")
    result = []
    for a, b in zip(keyed, keyed[1:]):
        delta = b[2] - a[2]
        percent = delta * Decimal(100) / a[2] if a[2] != 0 else None
        result.append((a[1], b[1], a[2], b[2], delta, percent))
    return result
