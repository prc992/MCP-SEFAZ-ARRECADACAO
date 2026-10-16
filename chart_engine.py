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

    if spec.group_by == "decendio":
        fig.update_xaxes(
            type="category",
            categoryorder="array",
            categoryarray=["1 Decêndio", "2 Decêndio", "3 Decêndio"],
            title_text="Decêndio",
        )

    return fig


def gerar_grafico_comparacao(dados: list[dict], spec: QuerySpec):
    label_1 = spec.period_1_label or "periodo_1"
    label_2 = spec.period_2_label or "periodo_2"

    if spec.group_by == "total":
        valor_1 = dados[0][label_1] if dados else 0
        valor_2 = dados[0][label_2] if dados else 0

        fig = go.Figure()

        fig.add_trace(go.Bar(
            x=[label_1, label_2],
            y=[valor_1, valor_2],
            text=[valor_1, valor_2],
            textposition="auto"
        ))

        fig.update_layout(
            title=f"Comparação de {spec.metric}: {label_1} vs {label_2}",
            xaxis_title="Período",
            yaxis_title=spec.metric,
            showlegend=False
        )

        return fig


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

    if spec.group_by == "decendio":
        fig.update_xaxes(
            type="category",
            categoryorder="array",
            categoryarray=["1 Decêndio", "2 Decêndio", "3 Decêndio"],
            title_text="Decêndio",
        )

    return fig

# Quatro gráficos independentes para o demonstrativo fiscal ICMS/FECOP.
INDICADORES_FECOP = {
    "icms_a": "A — ICMS bruto",
    "fecop_b": "B — FECOP",
    "icms_sem_fecop_c": "C — ICMS sem FECOP",
    "icms_liquido_tesouro_d": "D — ICMS líquido Tesouro (60% de C)",
}


def gerar_graficos_icms_fecop(dados: list[dict], spec: QuerySpec) -> list[go.Figure]:
    categoria = spec.group_by
    comparacao = spec.analysis_type == "compare_periods"
    periodos = [spec.period_1_label or "periodo_1", spec.period_2_label or "periodo_2"]
    categorias = (["1 Decêndio", "2 Decêndio", "3 Decêndio"]
                  if categoria == "decendio" else ["Total"])
    # Exibir apenas as categorias efetivamente presentes na consulta.
    presentes = {r.get(categoria) for r in dados}
    categorias = [c for c in categorias if c in presentes]
    if not categorias:
        categorias = list(dict.fromkeys(r.get(categoria) for r in dados))

    figuras = []
    for chave, titulo in INDICADORES_FECOP.items():
        fig = go.Figure()
        if comparacao:
            for periodo in periodos:
                valores = {r.get(categoria): r.get(chave)
                           for r in dados if r.get("periodo") == periodo}
                fig.add_trace(go.Bar(
                    x=categorias, y=[valores.get(c) for c in categorias],
                    name=periodo.replace("_", "/"),
                    hovertemplate="%{x}<br>R$ %{y:,.2f}<extra>%{fullData.name}</extra>",
                ))
        else:
            valores = {r.get(categoria): r.get(chave) for r in dados}
            fig.add_trace(go.Bar(
                x=categorias, y=[valores.get(c) for c in categorias],
                name=titulo,
                hovertemplate="%{x}<br>R$ %{y:,.2f}<extra></extra>",
            ))
        fig.update_layout(
            title=titulo, xaxis_title="Decêndio" if categoria == "decendio" else "Total",
            yaxis_title="Arrecadação (R$)",
            barmode="group", template="plotly_white", height=370,
            margin=dict(t=65, l=65, r=18, b=55),
            showlegend=comparacao,
            separators=",.",
        )
        fig.update_xaxes(type="category", categoryorder="array", categoryarray=categorias)
        fig.update_yaxes(tickformat=",.2s")
        figuras.append(fig)
    return figuras
