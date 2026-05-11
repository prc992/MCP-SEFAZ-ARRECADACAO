import plotly.graph_objects as go
from schemas import QuerySpec


def gerar_plotly_figure(dados: list[dict], spec: QuerySpec):
    if spec.analysis_type == "compare_periods":
        return gerar_grafico_comparacao(dados, spec)

    x = [row[spec.group_by] for row in dados]
    y = [row[spec.metric] for row in dados]

    if spec.chart_type == "bar":
        fig = go.Figure(data=[go.Bar(x=x, y=y)])
    else:
        fig = go.Figure(data=[go.Scatter(x=x, y=y, mode="lines+markers")])

    fig.update_layout(
        title=f"{spec.metric} por {spec.group_by}",
        xaxis_title=spec.group_by,
        yaxis_title=spec.metric
    )

    return fig


def gerar_grafico_comparacao(dados: list[dict], spec: QuerySpec):
    label_1 = spec.period_1_label or "periodo_1"
    label_2 = spec.period_2_label or "periodo_2"

    x = [row[spec.group_by] for row in dados]
    y1 = [row[label_1] for row in dados]
    y2 = [row[label_2] for row in dados]

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=x,
        y=y1,
        name=label_1
    ))

    fig.add_trace(go.Bar(
        x=x,
        y=y2,
        name=label_2
    ))

    fig.update_layout(
        title=f"Comparação de {spec.metric} por {spec.group_by}: {label_1} vs {label_2}",
        xaxis_title=spec.group_by,
        yaxis_title=spec.metric,
        barmode="group"
    )

    return fig