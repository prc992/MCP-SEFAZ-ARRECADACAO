import plotly.graph_objects as go
from schemas import QuerySpec
from math import isfinite


def _numero(valor):
    """Retorna um número finito sem modificar o valor usado no gráfico."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError, OverflowError):
        return None
    return numero if isfinite(numero) else None


def _rotulo_resumido(valor):
    """Texto compacto para leitura imediata; não altera os dados nem a escala."""
    numero = _numero(valor)
    if numero is None:
        return ""

    absoluto = abs(numero)
    for escala, sufixo in ((1_000_000_000_000, " tri"),
                           (1_000_000_000, " bi"),
                           (1_000_000, " mi"),
                           (1_000, " mil")):
        if absoluto >= escala:
            # Mais resolução para valores próximos de 1 unidade (ex.: 1,06 bi).
            casas = 2 if absoluto / escala < 10 else 1
            abreviado = f"{numero / escala:.{casas}f}".replace(".", ",")
            return abreviado.rstrip("0").rstrip(",") + sufixo

    if absoluto == 0:
        return "0"
    if absoluto < 10 and not numero.is_integer():
        return f"{numero:.2f}".replace(".", ",")
    return f"{numero:.0f}"


def _numero_br(valor, *, inteiro=False):
    """Formatação pt-BR completa para o tooltip (centavos quando monetário)."""
    numero = _numero(valor)
    if numero is None:
        return "—"
    texto = f"{numero:,.0f}" if inteiro else f"{numero:,.2f}"
    return texto.replace(",", "_").replace(".", ",").replace("_", ".")


def _valor_hover(valor, *, documentos=False):
    texto = _numero_br(valor, inteiro=documentos)
    return texto if documentos or texto == "—" else f"R$ {texto}"


def _valores_para_linha(valores):
    """Evita sobrepor dezenas de rótulos em séries temporais extensas."""
    total = len(valores)
    passo = max(1, (total + 9) // 10)
    return [_rotulo_resumido(v) if i % passo == 0 or i == total - 1 else ""
            for i, v in enumerate(valores)]


def _folga_escala(fig, valores):
    """Reserva espaço para números desenhados fora das barras/pontos."""
    numeros = [_numero(v) for v in valores]
    numeros = [v for v in numeros if v is not None]
    if not numeros:
        return
    minimo, maximo = min(numeros), max(numeros)
    inferior = min(0, minimo * 1.2)
    superior = max(0, maximo * 1.2)
    if inferior == superior:
        superior = 1
    fig.update_yaxes(range=[inferior, superior])


def gerar_plotly_figure(dados: list[dict], spec: QuerySpec):
    if spec.analysis_type == "compare_periods":
        return gerar_grafico_comparacao(dados, spec)

    x = [row[spec.group_by] for row in dados]
    y = [row[spec.metric] for row in dados]
    documentos = spec.metric == "qtd_documentos"
    hover = [_valor_hover(v, documentos=documentos) for v in y]
    tooltip = "%{x}<br>%{customdata}<extra></extra>"

    if spec.chart_type == "bar":
        fig = go.Figure(data=[go.Bar(
            x=x, y=y, text=[_rotulo_resumido(v) for v in y],
            textposition="outside", textfont=dict(size=11), cliponaxis=False,
            customdata=hover, hovertemplate=tooltip,
        )])
    else:
        fig = go.Figure(data=[go.Scatter(
            x=x, y=y, mode="lines+markers+text",
            text=_valores_para_linha(y), textposition="top center",
            textfont=dict(size=10), cliponaxis=False,
            customdata=hover, hovertemplate=tooltip,
        )])

    fig.update_layout(
        title=f"{spec.metric} por {spec.group_by}",
        xaxis_title=spec.group_by,
        yaxis_title=spec.metric,
        separators=",."
    )

    _folga_escala(fig, y)

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
        valores = [valor_1, valor_2]
        documentos = spec.metric == "qtd_documentos"

        fig.add_trace(go.Bar(
            x=[label_1, label_2],
            y=valores,
            text=[_rotulo_resumido(v) for v in valores],
            textposition="outside", textfont=dict(size=11), cliponaxis=False,
            customdata=[_valor_hover(v, documentos=documentos) for v in valores],
            hovertemplate="%{x}<br>%{customdata}<extra></extra>",
        ))

        fig.update_layout(
            title=f"Comparação de {spec.metric}: {label_1} vs {label_2}",
            xaxis_title="Período",
            yaxis_title=spec.metric,
            showlegend=False,
            separators=",."
        )

        _folga_escala(fig, valores)

        return fig


    x = [row[spec.group_by] for row in dados]
    y1 = [row[label_1] for row in dados]
    y2 = [row[label_2] for row in dados]
    documentos = spec.metric == "qtd_documentos"

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=x,
        y=y1,
        name=label_1,
        text=[_rotulo_resumido(v) for v in y1],
        textposition="outside", textfont=dict(size=10), cliponaxis=False,
        customdata=[_valor_hover(v, documentos=documentos) for v in y1],
        hovertemplate="%{x}<br>%{customdata}<extra>%{fullData.name}</extra>",
    ))

    fig.add_trace(go.Bar(
        x=x,
        y=y2,
        name=label_2,
        text=[_rotulo_resumido(v) for v in y2],
        textposition="outside", textfont=dict(size=10), cliponaxis=False,
        customdata=[_valor_hover(v, documentos=documentos) for v in y2],
        hovertemplate="%{x}<br>%{customdata}<extra>%{fullData.name}</extra>",
    ))

    fig.update_layout(
        title=f"Comparação de {spec.metric} por {spec.group_by}: {label_1} vs {label_2}",
        xaxis_title=spec.group_by,
        yaxis_title=spec.metric,
        barmode="group",
        separators=",."
    )

    _folga_escala(fig, y1 + y2)

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
                serie = [valores.get(c) for c in categorias]
                fig.add_trace(go.Bar(
                    x=categorias, y=serie,
                    text=[_rotulo_resumido(v) for v in serie],
                    textposition="outside", textfont=dict(size=10), cliponaxis=False,
                    name=periodo.replace("_", "/"),
                    customdata=[_valor_hover(v) for v in serie],
                    hovertemplate="%{x}<br>%{customdata}<extra>%{fullData.name}</extra>",
                ))
        else:
            valores = {r.get(categoria): r.get(chave) for r in dados}
            serie = [valores.get(c) for c in categorias]
            fig.add_trace(go.Bar(
                x=categorias, y=serie,
                text=[_rotulo_resumido(v) for v in serie],
                textposition="outside", textfont=dict(size=11), cliponaxis=False,
                name=titulo,
                customdata=[_valor_hover(v) for v in serie],
                hovertemplate="%{x}<br>%{customdata}<extra></extra>",
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
        _folga_escala(fig, [v for trace in fig.data for v in trace.y])
        figuras.append(fig)
    return figuras
