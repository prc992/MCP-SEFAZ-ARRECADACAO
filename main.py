from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from schemas import QuerySpec, AskRequest
from query_engine import executar_query
from chart_engine import gerar_plotly_figure
from metadata_service import get_metadata
from ask_service import interpretar_pergunta, gerar_summary

app = FastAPI()


@app.get("/")
def home():
    return {"mensagem": "API funcionando"}


@app.get("/metadata")
def metadata():
    return get_metadata()


@app.post("/grafico")
def gerar_grafico(spec: QuerySpec):
    dados = executar_query(spec)
    fig = gerar_plotly_figure(dados, spec)

    return {
        "title": f"{spec.metric} por {spec.group_by}",
        "chart_type": spec.chart_type,
        "dados_brutos": dados,
        "plotly_json": fig.to_dict()
    }


@app.post("/grafico-html", response_class=HTMLResponse)
def gerar_grafico_html(spec: QuerySpec):
    dados = executar_query(spec)
    fig = gerar_plotly_figure(dados, spec)
    return HTMLResponse(content=fig.to_html(full_html=True))


@app.post("/ask")
def ask(req: AskRequest):
    try:
        spec = interpretar_pergunta(req.question)
    except ValueError as e:
        return {
            "question": req.question,
            "error": str(e)
        }

    dados = executar_query(spec)
    fig = gerar_plotly_figure(dados, spec)
    summary = gerar_summary(spec)

    return {
        "question": req.question,
        "query_interpretada": spec.model_dump(),
        "summary": summary,
        "title": f"{spec.metric} por {spec.group_by}",
        "chart_type": spec.chart_type,
        "dados_brutos": dados,
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
                margin: 40px;
                background: #f7f7f8;
                color: #222;
            }
            .container {
                max-width: 1000px;
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

            table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 8px;
            }

            th, td {
                border: 1px solid #e5e7eb;
                padding: 8px 10px;
                text-align: left;
            }

            th {
                background: #f3f4f6;
                font-weight: bold;
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
            <button onclick="enviarPergunta()">Gerar resposta</button>

            <div class="examples">
                <div class="muted">Exemplos clicáveis:</div>

                <span class="example-chip" onclick="usarExemplo('qual o valor arrecadado por segmento no mês de abril de 2026?')">
                    valor por segmento em abril/2026
                </span>

                <span class="example-chip" onclick="usarExemplo('quero comparar valor arrecadado por segmento entre abril de 2025 e abril de 2026')">
                    abril/2025 vs abril/2026
                </span>

                <span class="example-chip" onclick="usarExemplo('quero comparar valor arrecadado apenas do segmento ATACADISTA entre abril de 2025 e abril de 2026')">
                    comparar segmento ATACADISTA
                </span>

                <span class="example-chip" onclick="usarExemplo('quero ver a arrecadação nos últimos 12 meses para o subgrupo ICMS')">
                    últimos 12 meses ICMS
                </span>

                <span class="example-chip" onclick="usarExemplo('quero a quantidade de DAE pagos por grupo de receita no mês de abril de 2026')">
                    DAE por grupo de receita
                </span>

                <span class="example-chip" onclick="usarExemplo('mostre valor arrecadado por receita no mês de abril de 2026')">
                    valor por receita
                </span>

                <span class="example-chip" onclick="usarExemplo('mostre valor arrecadado por data de pagamento no mês de abril de 2026')">
                    série diária abril/2026
                </span>

                <span class="example-chip" onclick="usarExemplo('compare o valor arrecadado do subgrupo ICMS entre abril e maio de 2026')">
                    ICMS abril vs maio
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
                    <pre id="interpretedQuery"></pre>
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

            function renderizarTabela(dados) {
                const container = document.getElementById("tableContainer");

                if (!dados || dados.length === 0) {
                    container.innerHTML = "<p>Nenhum dado encontrado.</p>";
                    return;
                }

                const colunas = Object.keys(dados[0]);

                let html = "<table>";
                html += "<thead><tr>";

                colunas.forEach(coluna => {
                    html += `<th>${coluna}</th>`;
                });

                html += "</tr></thead>";
                html += "<tbody>";

                dados.forEach(row => {
                    html += "<tr>";
                    colunas.forEach(coluna => {
                        let valor = row[coluna];

                        if (typeof valor === "number") {
                            valor = valor.toLocaleString("pt-BR");
                        }

                        html += `<td>${valor}</td>`;
                    });
                    html += "</tr>";
                });

                html += "</tbody></table>";

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
                    const response = await fetch("/ask", {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json"
                        },
                        body: JSON.stringify({ question })
                    });

                    if (!response.ok) {
                        const errorText = await response.text();
                        throw new Error("Falha na API: " + errorText);
                    }

                    const data = await response.json();

                    if (!data.query_interpretada || !data.plotly_json) {
                        throw new Error("Não foi possível interpretar a pergunta com os dados esperados.");
                    }

                    document.getElementById("resultado").style.display = "block";
                    document.getElementById("questionText").textContent = data.question || "";
                    document.getElementById("interpretedQuery").textContent = JSON.stringify(data.query_interpretada, null, 2);
                    document.getElementById("summaryText").textContent = data.summary || "Sem resumo disponível.";
                    document.getElementById("rawData").textContent = JSON.stringify(data.dados_brutos || [], null, 2);

                    renderizarTabela(data.dados_brutos || []);
                    
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