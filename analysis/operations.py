"""Primitivas matemáticas puras; compartilháveis por futuros motores e MCPs."""
from decimal import Decimal


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
