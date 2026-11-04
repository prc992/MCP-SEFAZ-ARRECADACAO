import plotly.graph_objects as go

from app.shared.contracts import QuerySpec


def _resolve_period_keys(data: list[dict], spec: QuerySpec) -> tuple[str, str]:
    if not data:
        return spec.period_1_label or "periodo_1", spec.period_2_label or "periodo_2"

    first_row = data[0]
    label_1 = spec.period_1_label or "periodo_1"
    label_2 = spec.period_2_label or "periodo_2"

    if label_1 in first_row and label_2 in first_row:
        return label_1, label_2

    reserved_keys = {
        spec.group_by,
        "diferenca",
        "variacao_percentual",
        "tendencia",
        "periodo_1",
        "periodo_2",
    }
    value_keys = [key for key in first_row.keys() if key not in reserved_keys]
    if len(value_keys) >= 2:
        return value_keys[0], value_keys[1]

    return label_1, label_2


def _comparison_chart(data: list[dict], spec: QuerySpec):
    label_1, label_2 = _resolve_period_keys(data, spec)

    x = [row[spec.group_by] for row in data]
    y1 = [row[label_1] for row in data]
    y2 = [row[label_2] for row in data]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=x, y=y1, name=label_1))
    fig.add_trace(go.Bar(x=x, y=y2, name=label_2))
    fig.update_layout(
        title=f"Comparação de {spec.metric} por {spec.group_by}: {label_1} vs {label_2}",
        xaxis_title=spec.group_by,
        yaxis_title=spec.metric,
        barmode="group",
    )
    return fig


def _time_series_x_axis(data: list[dict], spec: QuerySpec) -> list:
    if not data:
        return []

    first_row = data[0]
    if spec.group_by in first_row:
        return [row[spec.group_by] for row in data]

    if "mes" in first_row:
        return [row["mes"] for row in data]

    fallback_key = next(iter(first_row.keys()))
    return [row[fallback_key] for row in data]


def build_chart(data: list[dict], spec: QuerySpec) -> dict:
    if spec.analysis_type == "compare_periods":
        fig = _comparison_chart(data, spec)
        return fig.to_dict()

    x_axis = _time_series_x_axis(data, spec)
    y_axis = [row[spec.metric] for row in data]

    if spec.chart_type == "bar":
        fig = go.Figure(data=[go.Bar(x=x_axis, y=y_axis)])
    else:
        fig = go.Figure(data=[go.Scatter(x=x_axis, y=y_axis, mode="lines+markers")])

    fig.update_layout(
        title=f"{spec.metric} por {spec.group_by}",
        xaxis_title=spec.group_by,
        yaxis_title=spec.metric,
    )

    return fig.to_dict()