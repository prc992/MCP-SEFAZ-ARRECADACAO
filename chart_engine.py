import plotly.graph_objects as go
from schemas import QuerySpec


def gerar_plotly_figure(dados: list[dict], spec: QuerySpec):
    x = [row[spec.group_by] for row in dados]
    y = [row[spec.metric] for row in dados]

    if spec.chart_type == "bar":
        fig = go.Figure(
            data=[go.Bar(x=x, y=y)]
        )
    else:
        fig = go.Figure(
            data=[go.Scatter(x=x, y=y, mode="lines+markers")]
        )

    fig.update_layout(
        title=f"{spec.metric} por {spec.group_by}",
        xaxis_title=spec.group_by,
        yaxis_title=spec.metric
    )

    return fig