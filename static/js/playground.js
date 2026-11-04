function usarExemplo(texto) {
            const campo = document.getElementById("questionInput");
            campo.value = texto;
            campo.focus({preventScroll: true});
            campo.scrollIntoView({behavior: "smooth", block: "center"});
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

        // Controla todas as ações enquanto uma consulta está em processamento.
        // Não altera o estado anterior dos botões ao terminar a operação.
        let requisicaoEmAndamento = false;
        let estadoBotoesLoading = [];
        let overflowAnterior = "";

        function mostrarLoading(titulo = "Faro está analisando sua pergunta…",
                               subtitulo = "Consultando os dados e preparando a resposta.") {
            if (requisicaoEmAndamento) return false;
            requisicaoEmAndamento = true;
            document.getElementById("loadingTitle").textContent = titulo;
            document.getElementById("loadingSubtitle").textContent = subtitulo;
            estadoBotoesLoading = Array.from(document.querySelectorAll("button"), botao =>
                ({botao, disabled: botao.disabled}));
            estadoBotoesLoading.forEach(({botao}) => { botao.disabled = true; });
            overflowAnterior = document.body.style.overflow;
            document.body.style.overflow = "hidden";
            document.getElementById("loadingOverlay").hidden = false;
            return true;
        }

        function esconderLoading() {
            document.getElementById("loadingOverlay").hidden = true;
            document.body.style.overflow = overflowAnterior;
            estadoBotoesLoading.forEach(({botao, disabled}) => { botao.disabled = disabled; });
            estadoBotoesLoading = [];
            requisicaoEmAndamento = false;
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
            mes: "Mês",
            periodo: "Período",
            icms_a: "ICMS (A) — R$",
            fecop_b: "FECOP (B) — R$",
            icms_sem_fecop_c: "ICMS sem FECOP (C) — R$",
            icms_liquido_tesouro_d: "ICMS líquido Tesouro (D) — R$"
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

        // O recorte vem sempre do QuerySpec executado, não do texto livre da pergunta.
        const nomesMeses = [
            "janeiro", "fevereiro", "março", "abril", "maio", "junho",
            "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"
        ];

        function lerDataISO(valor) {
            if (typeof valor !== "string") return null;
            const match = valor.match(/^(\d{4})-(\d{2})-(\d{2})(?:$|T|\s)/);
            if (!match) return null;
            const ano = Number(match[1]);
            const mes = Number(match[2]);
            const dia = Number(match[3]);
            const ultimoDia = new Date(Date.UTC(ano, mes, 0)).getUTCDate();
            if (mes < 1 || mes > 12 || dia < 1 || dia > ultimoDia) return null;
            return {ano, mes, dia};
        }

        function dataCurta(data) {
            return `${String(data.dia).padStart(2, "0")}/${String(data.mes).padStart(2, "0")}/${data.ano}`;
        }

        function formatarIntervalo(inicioBruto, fimBruto) {
            const inicio = lerDataISO(inicioBruto);
            const fim = lerDataISO(fimBruto);
            if (!inicio && !fim) return "";
            if (!inicio || !fim) return inicio ? `a partir de ${dataCurta(inicio)}` : `até ${dataCurta(fim)}`;

            const mesCompleto = inicio.ano === fim.ano && inicio.mes === fim.mes &&
                inicio.dia === 1 && fim.dia === new Date(Date.UTC(fim.ano, fim.mes, 0)).getUTCDate();
            if (mesCompleto) return `${nomesMeses[inicio.mes - 1]} de ${inicio.ano}`;

            const anoCompleto = inicio.ano === fim.ano && inicio.mes === 1 && inicio.dia === 1 &&
                fim.mes === 12 && fim.dia === 31;
            if (anoCompleto) return `ano de ${inicio.ano}`;
            if (dataCurta(inicio) === dataCurta(fim)) return dataCurta(inicio);
            return `${dataCurta(inicio)} a ${dataCurta(fim)}`;
        }

        function formatarNomePeriodo(rotulo) {
            if (typeof rotulo !== "string" || !rotulo.trim()) return "";
            const texto = rotulo.trim();
            const match = texto.match(/^([a-zA-ZÀ-ÿ]+)[_\s/-]+(\d{4})$/);
            if (match) {
                const mes = match[1].toLocaleLowerCase("pt-BR");
                if (nomesMeses.includes(mes)) return `${mes} de ${match[2]}`;
            }
            return texto.replace(/_/g, " ");
        }

        function obterPeriodoRelatorio(spec) {
            if (!spec || typeof spec !== "object") return "Período não informado no QuerySpec";
            if (spec.analysis_type === "compare_periods") {
                const periodo1 = formatarNomePeriodo(spec.period_1_label) ||
                    formatarIntervalo(spec.period_1_start, spec.period_1_end) || "período 1";
                const periodo2 = formatarNomePeriodo(spec.period_2_label) ||
                    formatarIntervalo(spec.period_2_start, spec.period_2_end) || "período 2";
                return `Comparação: ${periodo1} × ${periodo2}`;
            }
            const periodo = formatarIntervalo(spec.start_date, spec.end_date);
            return periodo ? `Período: ${periodo}` : "Período não informado no QuerySpec";
        }

        // Inclui o período também no título de cada figura Plotly: útil ao salvar
        // um gráfico isolado, sem o cabeçalho da seção no Playground.
        function adicionarPeriodoNoGrafico(layoutOriginal, periodo) {
            const layout = { ...(layoutOriginal || {}) };
            const titulo = typeof layout.title === "string" ? {text: layout.title} : {...(layout.title || {})};
            const tituloTexto = titulo.text || "Gráfico";
            layout.title = {
                ...titulo,
                text: `${tituloTexto}<br><span style="font-size:12px;color:#64748b">${escaparHtml(periodo)}</span>`
            };
            const margem = { ...(layout.margin || {}) };
            layout.margin = { ...margem, t: Math.max(Number(margem.t) || 0, 90) };
            return layout;
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

        let conversaAtual = null;
        let historicoChat = [];
        let modoInteracao = null; // null | chat; nova análise retorna à tela inicial
        let sessaoId = (typeof crypto !== "undefined" && crypto.randomUUID)
            ? crypto.randomUUID() : null;
        let ultimaInteracaoId = null;
        const votosLocais = {};

        function criarFeedback(interactionId, container) {
            container.replaceChildren();
            if (!interactionId || !sessaoId) return;
            const texto = document.createElement("span");
            texto.className = "feedback-note";
            texto.textContent = "Esta resposta foi útil?";
            container.appendChild(texto);
            const botoes = [];
            for (const [voto, simbolo, rotulo] of [
                ["positive", "👍", "Útil"], ["negative", "👎", "Não útil"]]) {
                const botao = document.createElement("button");
                botao.type = "button";
                botao.className = "feedback-button";
                botao.textContent = simbolo;
                botao.title = rotulo;
                botao.setAttribute("aria-label", rotulo);
                botao.setAttribute("aria-pressed", votosLocais[interactionId] === voto ? "true" : "false");
                if (votosLocais[interactionId] === voto) botao.classList.add("selected");
                botao.onclick = async () => {
                    botoes.forEach(b => b.disabled = true);
                    try {
                        const resposta = await fetch("/feedback", {
                            method:"POST", headers:{"Content-Type":"application/json"},
                            body:JSON.stringify({session_id:sessaoId,
                                interaction_id:interactionId, vote:voto})
                        });
                        if (!resposta.ok) throw new Error("HTTP " + resposta.status);
                        votosLocais[interactionId] = voto;
                        botoes.forEach(b => {
                            const ativo = b.dataset.voto === voto;
                            b.classList.toggle("selected", ativo);
                            b.setAttribute("aria-pressed", ativo ? "true" : "false");
                        });
                        texto.textContent = "Feedback registrado. Obrigado.";
                    } catch (erro) {
                        texto.textContent = "Não foi possível registrar o feedback.";
                    } finally { botoes.forEach(b => b.disabled = false); }
                };
                botao.dataset.voto = voto;
                botoes.push(botao);
                container.appendChild(botao);
            }
        }

        function adicionarMensagem(texto, classe, interactionId=null, rolar=true) {
            const painel = document.getElementById("chatMessages");
            const mensagem = document.createElement("div");
            mensagem.className = "chat-message " + classe;
            mensagem.textContent = texto;
            if (classe === "chat-assistant" || classe === "chat-error") {
                const envelope = document.createElement("div");
                envelope.className = "chat-assistant-wrapper";
                const linha = document.createElement("div");
                linha.className = "faro-chat-row";
                const avatar = document.createElement("img");
                avatar.className = "faro-chat-avatar";
                avatar.src = "/static/images/faro.jpeg";
                avatar.alt = "Faro";
                avatar.width = 38;
                avatar.height = 38;
                linha.appendChild(avatar);
                linha.appendChild(mensagem);
                envelope.appendChild(linha);
                if (interactionId) {
                    const feedback = document.createElement("div");
                    feedback.className = "feedback-row";
                    criarFeedback(interactionId, feedback);
                    envelope.appendChild(feedback);
                }
                painel.appendChild(envelope);
            } else {
                painel.appendChild(mensagem);
            }
            if (rolar) mensagem.scrollIntoView({behavior:"smooth", block:"nearest"});
        }

        function sincronizarAcoes() {
            const podeInteragir = Boolean(conversaAtual);
            document.getElementById("actionPanel").hidden = !podeInteragir;
            const chatAberto = podeInteragir && modoInteracao === "chat";
            document.getElementById("chatSection").hidden = !chatAberto;
            document.getElementById("chooseChat").setAttribute("aria-pressed", String(chatAberto));
        }

        function escolherAcao(tipo) {
            if (!conversaAtual || tipo !== "chat") return;
            modoInteracao = modoInteracao === "chat" ? null : "chat";
            sincronizarAcoes();
            if (modoInteracao === "chat") document.getElementById("chatQuestion").focus();
        }

        function iniciarNovaAnalise() {
            if (requisicaoEmAndamento) return;
            // A nova análise reinicia a experiência visual e o contexto do relatório,
            // mas preserva o ID da sessão para rastreabilidade das interações.
            conversaAtual = null;
            historicoChat = [];
            modoInteracao = null;
            ultimaInteracaoId = null;

            document.getElementById("questionInput").value = "";
            document.getElementById("chatQuestion").value = "";
            document.getElementById("chatMessages").replaceChildren();
            document.getElementById("initialFeedback").replaceChildren();
            document.getElementById("pdfStatus").textContent = "";
            document.getElementById("queryDetails").open = false;
            document.getElementById("resultado").style.display = "none";
            document.getElementById("faroWelcome").hidden = false;
            document.getElementById("initialQueryPanel").hidden = false;
            esconderErro();
            esconderLoading();
            sincronizarAcoes();
            window.scrollTo({ top: 0, behavior: "smooth" });
            document.getElementById("questionInput").focus({ preventScroll: true });
        }

        async function baixarRelatorioPdf() {
            if (requisicaoEmAndamento) return;
            const status = document.getElementById("pdfStatus");
            const botao = document.getElementById("downloadPdf");
            if (!conversaAtual) {
                status.textContent = "Faça uma consulta antes de exportar.";
                return;
            }
            botao.disabled = true;
            status.classList.remove("error");
            status.textContent = "Preparando tabela e gráficos para o PDF...";
            try {
                const tabela = document.querySelector("#tableContainer table.data-table");
                if (!tabela) throw new Error("A tabela do relatório não está disponível.");
                const columns = Array.from(tabela.querySelectorAll("thead th"), th => th.textContent.trim());
                const rows = Array.from(tabela.querySelectorAll("tbody tr"), tr =>
                    Array.from(tr.querySelectorAll("td"), td => td.textContent.trim()));

                const varios = document.getElementById("chartsContainer").style.display !== "none";
                const elementos = varios
                    ? Array.from(document.querySelectorAll("#chartsContainer .chart-panel"))
                    : [document.getElementById("chart")];
                const charts = [];
                for (const elemento of elementos) {
                    const grafico = elemento.matches(".js-plotly-plot") ? elemento : elemento.querySelector(".js-plotly-plot");
                    if (!grafico) throw new Error("Não foi possível localizar um dos gráficos Plotly.");
                    const image = await Plotly.toImage(grafico, {
                        format: "png", width: varios ? 1024 : 1200,
                        height: varios ? 630 : 660, scale: 1.5
                    });
                    if (!image.startsWith("data:image/png;base64,")) {
                        throw new Error("A captura de um gráfico não retornou imagem PNG.");
                    }
                    charts.push({title: "Gráfico " + (charts.length + 1), image});
                }
                if (!charts.length) throw new Error("Nenhum gráfico disponível para exportação.");
                const aviso = document.getElementById("availabilityNotice");
                const request = {
                    question: document.getElementById("questionText").textContent.trim(),
                    period: document.getElementById("tablePeriod").textContent.trim(),
                    notice: aviso.hidden ? null : aviso.textContent.trim(),
                    columns, rows, charts
                };
                status.textContent = "Gerando PDF...";
                const resposta = await fetch("/export/pdf", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify(request)
                });
                if (!resposta.ok) {
                    let detalhe = "HTTP " + resposta.status;
                    try {
                        const erro = await resposta.json();
                        if (erro.detail && typeof erro.detail === "string") detalhe = erro.detail;
                    } catch (_) { /* resposta não JSON */ }
                    throw new Error(detalhe);
                }
                const pdf = await resposta.blob();
                if (pdf.size < 100 || !pdf.type.includes("pdf")) {
                    throw new Error("A API não retornou um PDF válido.");
                }
                const url = URL.createObjectURL(pdf);
                const link = document.createElement("a");
                link.href = url;
                link.download = "faro_relatorio.pdf";
                document.body.appendChild(link);
                link.click();
                link.remove();
                setTimeout(() => URL.revokeObjectURL(url), 15000);
                status.textContent = "PDF preparado para download.";
            } catch (erro) {
                status.classList.add("error");
                status.textContent = "Não foi possível exportar o PDF: " + erro.message;
            } finally {
                botao.disabled = false;
            }
        }

        async function atualizarRelatorio(data) {
                document.getElementById("resultado").style.display = "block";
                document.getElementById("queryDetails").open = false;
                document.getElementById("tableSection").hidden = false;
                document.getElementById("chartsSection").hidden = false;
                sincronizarAcoes();
                document.getElementById("questionText").textContent = data.question || document.getElementById("questionText").textContent;
                document.getElementById("interpretedQuery").textContent = JSON.stringify(data.query_interpretada, null, 2);
                document.getElementById("sqlText").textContent = data.sql || "SQL não disponível.";
                document.getElementById("summaryText").textContent = (data.summary || "Sem resumo disponível.")
                    + (data.aviso_disponibilidade ? " " + data.aviso_disponibilidade : "");
                const notice = document.getElementById("availabilityNotice");
                const noticeText = (data.aviso_disponibilidade || "").trim();
                notice.textContent = noticeText;
                notice.hidden = !noticeText;
                document.getElementById("rawData").textContent = JSON.stringify(data.dados_brutos || [], null, 2);
                const periodoRelatorio = obterPeriodoRelatorio(data.query_interpretada);
                document.getElementById("tablePeriod").textContent = periodoRelatorio;
                document.getElementById("chartPeriod").textContent = periodoRelatorio;

                renderizarTabela(data.dados_tabela || data.dados_brutos || []);

                const grade = document.getElementById("chartsContainer");
                grade.replaceChildren();
                const multiplo = Array.isArray(data.plotly_charts) && data.plotly_charts.length > 0;
                grade.style.display = multiplo ? "grid" : "none";
                document.getElementById("chart").style.display = multiplo ? "none" : "block";
                if (multiplo) {
                    Plotly.purge("chart");
                    for (const grafico of data.plotly_charts) {
                        const painel = document.createElement("div");
                        painel.className = "chart-panel";
                        grade.appendChild(painel);
                        // Cada figura deve ocupar somente a largura de sua célula.
                        // Evita que um gráfico Plotly invada/recorte o gráfico vizinho.
                        const larguraPainel = Math.floor(painel.getBoundingClientRect().width);
                        const layoutPainel = {
                            ...adicionarPeriodoNoGrafico(grafico.layout, periodoRelatorio),
                            autosize: false,
                            width: larguraPainel
                        };
                        await Plotly.newPlot(
                            painel,
                            grafico.data || [],
                            layoutPainel,
                            {responsive: true, displaylogo: false}
                        );
                    }
                } else {
                    await Plotly.newPlot("chart", data.plotly_json.data || [],
                        adicionarPeriodoNoGrafico(data.plotly_json.layout, periodoRelatorio),
                        {responsive: true});
                }

        }

        async function enviarContinuacao() {
            if (requisicaoEmAndamento) return;
            const caixa = document.getElementById("chatQuestion");
            const pergunta = caixa.value.trim();
            if (!pergunta || !conversaAtual) return;
            caixa.value = "";
            adicionarMensagem(pergunta, "chat-user");
            const botao = document.getElementById("chatSend");
            botao.disabled = true;
            document.getElementById("downloadPdf").disabled = true;
            botao.textContent = "Faro está analisando...";
            mostrarLoading("Faro está analisando sua continuação…",
                "Verificando o contexto da conversa e preparando a resposta.");
            try {
                const resposta = await fetch("/chat", {
                    method:"POST", headers:{"Content-Type":"application/json",
                        "X-Session-ID": sessaoId || "",
                        "X-Parent-Interaction-ID": ultimaInteracaoId || ""},
                    body:JSON.stringify({
                        question:pergunta,
                        previous_spec:conversaAtual.query_interpretada,
                        previous_data:(conversaAtual.dados_brutos || []).slice(0, 101),
                        history:historicoChat.slice(-8)
                    })
                });
                if (!resposta.ok) throw new Error("Falha HTTP " + resposta.status);
                const dados = await resposta.json();
                if (dados.session_id) sessaoId = dados.session_id;
                if (dados.interaction_id) ultimaInteracaoId = dados.interaction_id;
                if (dados.action === "error") {
                    adicionarMensagem(dados.error || "Não foi possível continuar.", "chat-error", dados.interaction_id);
                    return;
                }
                if (dados.action === "query") {
                    if (!dados.plotly_json) throw new Error("Nova consulta não retornou gráfico.");
                    dados.question = pergunta;
                    await atualizarRelatorio(dados);
                    conversaAtual = dados;
                    document.getElementById("pdfStatus").textContent = "";
                    adicionarMensagem(dados.answer || "Consulta atualizada.", "chat-assistant", dados.interaction_id, false);
                    document.getElementById("tableSection").scrollIntoView({behavior:"smooth", block:"start"});
                } else if (dados.action === "answer") {
                    adicionarMensagem(dados.answer, "chat-assistant", dados.interaction_id);
                } else {
                    throw new Error("Resposta inesperada.");
                }
                historicoChat.push({user:pergunta, assistant:dados.answer || "Nova análise gerada."});
                historicoChat = historicoChat.slice(-8);
            } catch (erro) {
                adicionarMensagem("Erro ao continuar: " + erro.message, "chat-error");
            } finally {
                esconderLoading();
                botao.disabled = false;
                document.getElementById("downloadPdf").disabled = false;
                botao.textContent = "Enviar";
            }
        }

        async function enviarPergunta() {
            if (requisicaoEmAndamento) return;
            const question = document.getElementById("questionInput").value.trim();

            if (!question) {
                mostrarErro("Digite uma pergunta primeiro.");
                return;
            }

            esconderErro();
            conversaAtual = null;
            document.getElementById("actionPanel").hidden = true;
            document.getElementById("chatSection").hidden = true;
            ultimaInteracaoId = null;
            document.getElementById("initialFeedback").replaceChildren();
            mostrarLoading("Faro está analisando sua pergunta…",
                "Consultando os dados e preparando tabela e gráficos.");
            document.getElementById("resultado").style.display = "none";
            document.getElementById("queryDetails").open = false;
            document.getElementById("tablePeriod").textContent = "";
            document.getElementById("chartPeriod").textContent = "";
            document.getElementById("availabilityNotice").hidden = true;
            document.getElementById("availabilityNotice").textContent = "";

            try {
                const response = await fetch("/ask", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-Session-ID": sessaoId || ""
                    },
                    body: JSON.stringify({ question })
                });

                if (!response.ok) {
                    const errorText = await response.text();
                    throw new Error("Falha na API: " + errorText);
                }

                const data = await response.json();
                if (data.session_id) sessaoId = data.session_id;
                if (data.interaction_id) ultimaInteracaoId = data.interaction_id;

                if (data.error) {
                    document.getElementById("resultado").style.display = "block";
                    document.getElementById("tableSection").hidden = true;
                    document.getElementById("chartsSection").hidden = true;
                    document.getElementById("chatSection").hidden = true;
                    document.getElementById("questionText").textContent = data.question || "";
                    document.getElementById("interpretedQuery").textContent = data.query_interpretada
                        ? JSON.stringify(data.query_interpretada, null, 2)
                        : "Nenhuma consulta executada.";
                    document.getElementById("sqlText").textContent = "SQL não executado.";
                    document.getElementById("summaryText").textContent = data.error_type === "period_unavailable"
                        ? "Consulta não executada: período sem dados disponíveis."
                        : "Não foi possível executar a consulta.";
                    document.getElementById("rawData").textContent = "[]";
                    document.getElementById("tableContainer").textContent = "";
                    Plotly.purge("chart");
                    document.getElementById("chartsContainer").replaceChildren();
                    mostrarErro(data.error);
                    document.getElementById("initialQueryPanel").hidden = false;
                    // Sem gráficos, mantém o feedback visível fora dos detalhes recolhidos.
                    document.getElementById("queryDetails").after(document.getElementById("initialFeedback"));
                    criarFeedback(data.interaction_id, document.getElementById("initialFeedback"));
                    return;
                }
                if (!data.query_interpretada || !data.plotly_json) {
                    throw new Error("Não foi possível interpretar a pergunta com os dados esperados.");
                }

                conversaAtual = data;
                modoInteracao = null;
                document.getElementById("initialQueryPanel").hidden = true;
                document.getElementById("pdfStatus").textContent = "";
                document.getElementById("faroWelcome").hidden = true;
                historicoChat = [];
                document.getElementById("chatMessages").replaceChildren();
                await atualizarRelatorio(data);
                document.getElementById("chart").after(document.getElementById("initialFeedback"));
                criarFeedback(data.interaction_id, document.getElementById("initialFeedback"));
                // A conversa só aparece se o usuário escolher essa ação.

                document.getElementById("tableSection").scrollIntoView({behavior:"smooth", block:"start"});

            } catch (error) {
                document.getElementById("initialQueryPanel").hidden = false;
                mostrarErro(
                    "Não consegui interpretar ou processar sua pergunta. " +
                    "Verifique a pergunta e tente novamente. " +
                    "Detalhe técnico: " + error.message
                );
            } finally {
                esconderLoading();
            }
        }
