from app.shared.contracts import QuerySpec


def summarize_spec(spec: QuerySpec) -> str:
    if spec.analysis_type == "compare_periods":
        return (
            f"Comparação de {spec.metric} por {spec.group_by}, "
            f"entre {spec.period_1_label} e {spec.period_2_label}."
        )

    if spec.analysis_type == "time_series":
        return f"Série temporal de {spec.metric} por mês nos últimos {spec.months_back} meses."

    period_part = ""
    if spec.start_date and spec.end_date:
        period_part = f" no período de {spec.start_date} a {spec.end_date}"

    return f"Consulta de {spec.metric} por {spec.group_by}{period_part}."
