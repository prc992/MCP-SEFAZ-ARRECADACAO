from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from schemas import QuerySpec, AskRequest
from query_engine import executar_query
from chart_engine import gerar_plotly_figure
from metadata_service import get_metadata
from ask_service import interpretar_pergunta, gerar_summary
from llm_service import interpretar_pergunta_llm

app = FastAPI()


def preparar_dados_tabela(dados: list[dict], spec: QuerySpec) -> list[dict]:
    """Acrescenta Total geral somente à tabela agrupada por decêndio.

    Não modifica os dados de origem utilizados no gráfico.
    """
    linhas = [dict(row) for row in dados]
    if spec.group_by != "decendio" or not linhas:
        return linhas

    if spec.analysis_type == "compare_periods":
        label_1 = spec.period_1_label or "periodo_1"
        label_2 = spec.period_2_label or "periodo_2"
        total_1 = sum(float(row.get(label_1) or 0) for row in linhas)
        total_2 = sum(float(row.get(label_2) or 0) for row in linhas)
        diferenca = total_2 - total_1
        total = {
            "decendio": "Total geral",
            label_1: total_1,
            label_2: total_2,
            "diferenca": diferenca,
            "variacao_percentual": (diferenca / total_1 * 100) if total_1 else None,
            "tendencia": "subiu" if diferenca > 0 else ("caiu" if diferenca < 0 else "estável"),
        }
    else:
        total = {
            "decendio": "Total geral",
            spec.metric: sum(float(row.get(spec.metric) or 0) for row in linhas),
        }

    linhas.append(total)
    return linhas


@app.get("/")
def home():
    return {"mensagem": "API funcionando"}


@app.get("/metadata")
def metadata():
    return get_metadata()


@app.post("/grafico")
def gerar_grafico(spec: QuerySpec):
    query_result = executar_query(spec)
    dados = query_result["dados"]
    sql = query_result["sql"]

    fig = gerar_plotly_figure(dados, spec)

    return {
        "title": f"{spec.metric} por {spec.group_by}",
        "chart_type": spec.chart_type,
        "dados_brutos": dados,
        "dados_tabela": preparar_dados_tabela(dados, spec),
        "plotly_json": fig.to_dict()
    }


@app.post("/grafico-html", response_class=HTMLResponse)
def gerar_grafico_html(spec: QuerySpec):
    query_result = executar_query(spec)
    dados = query_result["dados"]
    sql = query_result["sql"]

    fig = gerar_plotly_figure(dados, spec)
    return HTMLResponse(content=fig.to_html(full_html=True))


@app.post("/ask")
def ask(req: AskRequest):
    # Os parsers são independentes: falha na LLM não impede o uso das regras.
    interpretacoes = {}
    erros = {}
    for nome, funcao in (("regras", interpretar_pergunta), ("llm", interpretar_pergunta_llm)):
        try:
            interpretacoes[nome] = funcao(req.question)
        except Exception as exc:
            erros[nome] = (f"{type(exc).__name__}: {exc}" if nome == "regras"
                           else f"Falha no parser LLM ({type(exc).__name__}). Verifique chave, modelo, conectividade e logs.")

    # Modo selecionado controla apenas qual QuerySpec será EXECUTADO.
    # Compatibilidade: sem parser, o comportamento anterior (regras) permanece.
    parser = req.parser
    if parser not in interpretacoes:
        if parser == "llm":
            return {"question": req.question, "error": erros.get("llm", "Parser LLM indisponível"),
                    "interpretacoes": {k: v.model_dump() for k, v in interpretacoes.items()},
                    "erros_interpretacao": erros}
        if "regras" not in interpretacoes:
            return {"question": req.question, "error": erros.get("regras", "Parser indisponível"),
                    "interpretacoes": {k: v.model_dump() for k, v in interpretacoes.items()},
                    "erros_interpretacao": erros}

    spec = interpretacoes[parser]
    query_result = executar_query(spec)
    dados = query_result["dados"]
    sql = query_result["sql"]
    fig = gerar_plotly_figure(dados, spec)

    return {
        "question": req.question,
        "parser_executado": parser,
        "interpretacoes": {k: v.model_dump() for k, v in interpretacoes.items()},
        "erros_interpretacao": erros,
        "query_interpretada": spec.model_dump(),
        "summary": gerar_summary(spec),
        "sql": sql,
        "title": f"{spec.metric} por {spec.group_by}",
        "chart_type": spec.chart_type,
        "dados_brutos": dados,
        "dados_tabela": preparar_dados_tabela(dados, spec),
        "plotly_json": fig.to_dict()
    }


@app.get("/playground", response_class=HTMLResponse)
def playground():
    html = """
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>Playground de Perguntas</title>
        <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 20px;
                background: #f7f7f8;
                color: #222;
            }
            .container {
                max-width: 1400px;
                width: calc(100% - 40px);
                box-sizing: border-box;
                margin: 0 auto;
                background: white;
                padding: 24px;
                border-radius: 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            }
            h1 {
                margin-top: 0;
            }
            textarea {
                width: 100%;
                min-height: 100px;
                padding: 12px;
                font-size: 16px;
                border-radius: 8px;
                border: 1px solid #ccc;
                resize: vertical;
                box-sizing: border-box;
            }
            button {
                margin-top: 12px;
                padding: 10px 18px;
                border: none;
                border-radius: 8px;
                background: #111827;
                color: white;
                font-size: 15px;
                cursor: pointer;
            }
            button:hover {
                background: #1f2937;
            }
            .section {
                margin-top: 24px;
                padding: 16px;
                background: #fafafa;
                border: 1px solid #e5e7eb;
                border-radius: 10px;
            }
            .label {
                font-weight: bold;
                margin-bottom: 8px;
            }
            pre {
                white-space: pre-wrap;
                word-break: break-word;
                background: #f3f4f6;
                padding: 12px;
                border-radius: 8px;
                overflow-x: auto;
            }
            #chart {
                margin-top: 20px;
            }
            .muted {
                color: #666;
                font-size: 14px;
            }
            .examples {
                margin-top: 12px;
            }
            .example-chip {
                display: inline-block;
                margin: 6px 8px 0 0;
                padding: 8px 12px;
                border-radius: 999px;
                background: #f3f4f6;
                border: 1px solid #d1d5db;
                cursor: pointer;
                font-size: 14px;
            }
            .example-chip:hover {
                background: #e5e7eb;
            }
            #loading {
                margin-top: 16px;
                color: #374151;
                font-size: 14px;
                display: none;
            }
            #errorBox {
                margin-top: 24px;
                padding: 16px;
                background: #fef2f2;
                border: 1px solid #fecaca;
                color: #991b1b;
                border-radius: 10px;
                display: none;
            }

            .table-scroll {
                width: 100%;
                overflow-x: auto;
                margin-top: 8px;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
            }
            .data-table {
                width: 100%;
                border-collapse: collapse;
                font-size: 14px;
            }
            .data-table.comparacao {
                min-width: 900px;
            }
            .data-table th, .data-table td {
                border-bottom: 1px solid #e5e7eb;
                padding: 11px 14px;
                text-align: left;
                vertical-align: middle;
            }
            .data-table th {
                background: #f3f4f6;
                font-weight: 600;
                white-space: nowrap;
            }
            .data-table .numero {
                text-align: right;
                white-space: nowrap;
                font-variant-numeric: tabular-nums;
            }
            .data-table .categoria {
                white-space: nowrap;
            }
            .data-table tbody tr:nth-child(even):not(.total-geral) {
                background: #f9fafb;
            }
            .data-table tr.total-geral td {
                font-weight: 700;
                background: #e9eef5;
                border-top: 2px solid #94a3b8;
            }
            @media (max-width: 700px) {
                body { margin: 8px; }
                .container { width: 100%; padding: 12px; }
                .data-table th, .data-table td { padding: 9px 10px; }
            }

        </style>
    </head>
    <body>
        <div class="container">
            <h1>Pergunta → Interpretação → Gráfico</h1>
            <p class="muted">
                Digite uma pergunta em linguagem natural. O engine vai interpretar a consulta e gerar um gráfico.
            </p>

            <textarea id="questionInput" placeholder="Ex.: quero um gráfico de barra de valor arrecadado por município top 1"></textarea>
            <br />
            <label for="parserSelect">Executar consulta usando:</label>
            <select id="parserSelect">
                <option value="regras">Parser por regras (original)</option>
                <option value="llm">Parser por LLM</option>
            </select>
            <button onclick="enviarPergunta()">Gerar resposta e comparar interpretações</button>

            <div class="examples">
                <div class="muted">Experimente consultas com a LLM:</div>

                <span class="example-chip" onclick="usarExemplo('Mostre a arrecadação de ICMS por decêndio em setembro de 2026.')">
                    Decêndios · ICMS set/2026
                </span>

                <span class="example-chip" onclick="usarExemplo('Quanto arrecadamos de ICMS no segundo decêndio de setembro de 2026?')">
                    2º decêndio · ICMS
                </span>

                <span class="example-chip" onclick="usarExemplo('Compare a arrecadação de ICMS por decêndio entre agosto e setembro de 2026.')">
                    Decêndios · ago × set/2026
                </span>

                <span class="example-chip" onclick="usarExemplo('Compare o terceiro decêndio de agosto com o terceiro decêndio de setembro de 2026.')">
                    3º decêndio · ago × set
                </span>

                <span class="example-chip" onclick="usarExemplo('Qual foi o total arrecadado de ICMS em setembro de 2026?')">
                    Total de ICMS · set/2026
                </span>

                <span class="example-chip" onclick="usarExemplo('Quanto arrecadamos em cada decêndio de setembro de 2026?')">
                    Decêndios · todas as receitas
                </span>

                <span class="example-chip" onclick="usarExemplo('Quais segmentos arrecadaram mais com ICMS em abril de 2026?')">
                    Segmentos · ICMS abr/2026
                </span>

                <span class="example-chip" onclick="usarExemplo('Quais receitas do subgrupo ICMS arrecadaram mais em maio de 2026?')">
                    Receitas do ICMS · mai/2026
                </span>

                <span class="example-chip" onclick="usarExemplo('Quais subgrupos de receita tiveram maior arrecadação em junho de 2026?')">
                    Subgrupos · jun/2026
                </span>

                <span class="example-chip" onclick="usarExemplo('Mostre como a arrecadação de ICMS evoluiu mês a mês nos últimos seis meses.')">
                    Evolução mensal · ICMS
                </span>

            </div>

            <div id="loading">Gerando resposta...</div>

            <div id="errorBox"></div>

            <div id="resultado" style="display:none;">
                <div class="section">
                    <div class="label">Pergunta</div>
                    <div id="questionText"></div>
                </div>

                <div class="section">
                    <div class="label">Interpretação do engine</div>
                    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;">
                        <div><strong>Regras</strong><pre id="rulesQuery"></pre></div>
                        <div><strong>LLM</strong><pre id="llmQuery"></pre></div>
                    </div>
                    <div class="muted" id="comparisonText"></div>
                    <p class="muted">QuerySpec efetivamente executado:</p>
                    <pre id="interpretedQuery"></pre>
                </div>

                <div class="section">
                    <div class="label">SQL gerado</div>
                    <pre id="sqlText"></pre>
                </div>                

                <div class="section">
                    <div class="label">Resumo textual</div>
                    <div id="summaryText"></div>
                </div>

                <div class="section">
                    <div class="label">Dados brutos</div>
                    <pre id="rawData"></pre>
                </div>

                <div class="section">
                    <div class="label">Tabela</div>
                    <div id="tableContainer"></div>
                </div>                

                <div class="section">
                    <div class="label">Gráfico</div>
                    <div id="chart"></div>
                </div>
            </div>
        </div>

        <script>
            function usarExemplo(texto) {
                document.getElementById("questionInput").value = texto;
            }

            function mostrarErro(msg) {
                const errorBox = document.getElementById("errorBox");
                errorBox.style.display = "block";
                errorBox.textContent = msg;
            }

            function esconderErro() {
                const errorBox = document.getElementById("errorBox");
                errorBox.style.display = "none";
                errorBox.textContent = "";
            }

            function mostrarLoading() {
                document.getElementById("loading").style.display = "block";
            }

            function esconderLoading() {
                document.getElementById("loading").style.display = "none";
            }

            const rotulosTabela = {
                decendio: "Decêndio",
                total: "Total",
                valor_arrecadado: "Valor arrecadado (R$)",
                qtd_documentos: "Documentos pagos",
                diferenca: "Diferença (R$)",
                variacao_percentual: "Variação (%)",
                tendencia: "Tendência",
                segmento: "Segmento econômico",
                subgrupo: "Subgrupo de receita",
                receita: "Receita",
                codigo_receita: "Código da receita",
                data_pagamento: "Data de pagamento",
                mes: "Mês"
            };

            function escaparHtml(valor) {
                return String(valor).replace(/[&<>"']/g, caractere => ({
                    "&": "&amp;", "<": "&lt;", ">": "&gt;",
                    '"': "&quot;", "'": "&#39;"
                })[caractere]);
            }

            function rotuloColuna(coluna) {
                if (rotulosTabela[coluna]) return rotulosTabela[coluna];
                const periodo = coluna.match(/^(janeiro|fevereiro|marco|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)_([0-9]{4})$/i);
                if (periodo) {
                    const mes = periodo[1].charAt(0).toUpperCase() + periodo[1].slice(1);
                    return mes + "/" + periodo[2];
                }
                return coluna.replace(/_/g, " ");
            }

            function formatarValor(coluna, valor) {
                if (valor === null || valor === undefined) return "—";
                if (typeof valor !== "number") return String(valor);

                if (coluna === "variacao_percentual") {
                    return valor.toLocaleString("pt-BR", {
                        minimumFractionDigits: 2, maximumFractionDigits: 2
                    }) + "%";
                }
                if (coluna === "qtd_documentos" || coluna === "codigo_receita") {
                    return valor.toLocaleString("pt-BR", {maximumFractionDigits: 0});
                }
                return valor.toLocaleString("pt-BR", {
                    minimumFractionDigits: 2, maximumFractionDigits: 2
                });
            }

            function renderizarTabela(dados) {
                const container = document.getElementById("tableContainer");
                if (!dados || dados.length === 0) {
                    container.innerHTML = "<p>Nenhum dado encontrado.</p>";
                    return;
                }
                const colunas = Object.keys(dados[0]);
                const comparacao = colunas.includes("variacao_percentual");
                let html = `<div class="table-scroll"><table class="data-table${comparacao ? " comparacao" : ""}">`;
                html += "<thead><tr>";
                colunas.forEach(coluna => {
                    const numerica = dados.some(row => typeof row[coluna] === "number");
                    html += `<th class="${numerica ? "numero" : ""}">${escaparHtml(rotuloColuna(coluna))}</th>`;
                });
                html += "</tr></thead><tbody>";
                dados.forEach(row => {
                    const totalGeral = row.decendio === "Total geral";
                    html += `<tr${totalGeral ? ' class="total-geral"' : ""}>`;
                    colunas.forEach(coluna => {
                        const valor = row[coluna];
                        const numerica = typeof valor === "number" ||
                            dados.some(item => typeof item[coluna] === "number");
                        const classe = numerica ? "numero" : "categoria";
                        html += `<td class="${classe}">${escaparHtml(formatarValor(coluna, valor))}</td>`;
                    });
                    html += "</tr>";
                });
                html += "</tbody></table></div>";
                container.innerHTML = html;
            }

            async function enviarPergunta() {
                const question = document.getElementById("questionInput").value.trim();

                if (!question) {
                    mostrarErro("Digite uma pergunta primeiro.");
                    return;
                }

                esconderErro();
                mostrarLoading();
                document.getElementById("resultado").style.display = "none";

                try {
                    const parser = document.getElementById("parserSelect").value;
                    const response = await fetch("/ask", {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json"
                        },
                        body: JSON.stringify({ question, parser })
                    });

                    if (!response.ok) {
                        const errorText = await response.text();
                        throw new Error("Falha na API: " + errorText);
                    }

                    const data = await response.json();

                    const specs = data.interpretacoes || {};
                    const erros = data.erros_interpretacao || {};
                    document.getElementById("rulesQuery").textContent = specs.regras
                        ? JSON.stringify(specs.regras, null, 2) : (erros.regras || "Indisponível");
                    document.getElementById("llmQuery").textContent = specs.llm
                        ? JSON.stringify(specs.llm, null, 2) : (erros.llm || "Indisponível");
                    if (specs.regras && specs.llm) {
                        const diferentes = Object.keys(specs.regras).filter(
                            k => JSON.stringify(specs.regras[k]) !== JSON.stringify(specs.llm[k])
                        );
                        document.getElementById("comparisonText").textContent = diferentes.length
                            ? "Campos divergentes: " + diferentes.join(", ")
                            : "As duas interpretações são idênticas.";
                    } else {
                        document.getElementById("comparisonText").textContent = "Comparação incompleta: um dos parsers está indisponível.";
                    }
                    if (data.error) {
                        document.getElementById("resultado").style.display = "block";
                        document.getElementById("questionText").textContent = data.question || "";
                        document.getElementById("interpretedQuery").textContent = "Nenhuma consulta executada.";
                        document.getElementById("sqlText").textContent = "SQL não executado.";
                        document.getElementById("summaryText").textContent = "Parser selecionado indisponível.";
                        document.getElementById("rawData").textContent = "[]";
                        document.getElementById("tableContainer").textContent = "";
                        Plotly.purge("chart");
                        mostrarErro(data.error);
                        return;
                    }
                    if (!data.query_interpretada || !data.plotly_json) {
                        throw new Error("Não foi possível interpretar a pergunta com os dados esperados.");
                    }

                    document.getElementById("resultado").style.display = "block";
                    document.getElementById("questionText").textContent = data.question || "";
                    document.getElementById("interpretedQuery").textContent = JSON.stringify(data.query_interpretada, null, 2);
                    document.getElementById("sqlText").textContent = data.sql || "SQL não disponível.";
                    document.getElementById("summaryText").textContent = data.summary || "Sem resumo disponível.";
                    document.getElementById("rawData").textContent = JSON.stringify(data.dados_brutos || [], null, 2);

                    renderizarTabela(data.dados_tabela || data.dados_brutos || []);
                    
                    Plotly.newPlot(
                        "chart",
                        data.plotly_json.data || [],
                        data.plotly_json.layout || {}
                    );

                } catch (error) {
                    mostrarErro(
                        "Não consegui interpretar ou processar sua pergunta. " +
                        "Tente reformular usando termos como 'valor arrecadado', 'documentos', 'município', 'mês', 'Fortaleza' ou 'Caucaia'. " +
                        "Detalhe técnico: " + error.message
                    );
                } finally {
                    esconderLoading();
                }
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)