# business_metadata.py

BUSINESS_METADATA = """
CONTEXTO DE NEGÓCIO — ARRECADAÇÃO SEFAZ-CE

A aplicação consulta dados de arrecadação tributária
armazenados no Amazon Redshift.

TABELA PRINCIPAL:
arrecadacao.f_arrecadacao_diaria_consolidada

DIMENSÕES:

1. SEGMENTO ECONÔMICO
Coluna: dsc_segmento
Filtro QuerySpec: segmento
Agrupamento QuerySpec: group_by="segmento"

Representa a classificação econômica do contribuinte.

Exemplos de perguntas:
- Quais segmentos arrecadaram mais?
- Quanto arrecadou o comércio atacadista?
- Compare os setores econômicos.

Quando o usuário pergunta por todos os segmentos,
não aplique filtro segmento.

2. SUBGRUPO DA RECEITA
Coluna: receita_class_subgrupo
Filtro QuerySpec: subgrupo
Agrupamento QuerySpec: group_by="subgrupo"

Representa uma classificação agregada de receitas.

O subgrupo reúne receitas individuais que pertencem
a uma mesma classificação.

Exemplos:
- Arrecadação por grupo de receita.
- Arrecadação do subgrupo ICMS.
- Compare os subgrupos de receita.

Quando o usuário menciona um subgrupo conhecido,
utilize o campo subgrupo para filtrar.

3. RECEITA INDIVIDUAL
Coluna: dsc_receita
Filtro QuerySpec: receita
Agrupamento QuerySpec: group_by="receita"

Representa a descrição de uma receita específica.

Exemplos:
- Quais receitas arrecadaram mais?
- Detalhe a arrecadação por receita.
- Mostre as receitas do subgrupo ICMS.

IMPORTANTE:
A palavra "receita" sozinha não identifica uma
receita específica e não deve gerar filtro receita.

Não utilize receita="ICMS" automaticamente quando
ICMS corresponder a um subgrupo conhecido.

4. TOTAL DE ARRECADAÇÃO
Agrupamento QuerySpec: group_by="total"

Representa uma agregação sem separar os resultados
por qualquer dimensão.

Exemplos:
- Quanto foi arrecadado em maio?
- Qual o total de ICMS?
- Compare o total de abril com maio.

5. DECÊNDIOS OFICIAIS
Tabela auxiliar: arrecadacao.decendios_regra
Relacionamento: decendios_regra.dat_pagamento =
  f_arrecadacao_diaria_consolidada.dat_pagamento
Coluna da dimensão: decendios_regra.decendio
Agrupamento QuerySpec: group_by="decendio"
Filtro QuerySpec: decendio (inteiro de 1 a 3, ou null)

A coluna contém os textos "1 Decêndio", "2 Decêndio" e
"3 Decêndio", mas o filtro QuerySpec utiliza somente o número.
A classificação de datas já é estabelecida na carga da tabela:
não infira os limites do decêndio a partir de dias do calendário,
dias úteis ou feriados.

Exemplos:
- "Arrecadação por decêndio em setembro de 2026":
  group_by="decendio", decendio=null.
- "Quanto arrecadou no 2º decêndio de setembro de 2026?":
  group_by="total", decendio=2.
- "Compare agosto e setembro de 2026 por decêndio":
  analysis_type="compare_periods", group_by="decendio", decendio=null.
- "Compare o 3º decêndio de agosto com o de setembro de 2026":
  analysis_type="compare_periods", group_by="total", decendio=3.

A dimensão decendio é independente dos filtros de receita,
subgrupo e segmento econômico.

6. RELATÓRIO DE COMPOSIÇÃO ICMS/FECOP
Campo QuerySpec: report_type="icms_fecop" (padrão: "standard").

O Fundo Estadual de Combate à Pobreza (FECOP) corresponde,
nesta base, à parcela da arrecadação de ICMS marcada por
f_arrecadacao_diaria_consolidada.tip_fecop = 1.

Indicadores deste relatório, todos calculados no SQL:
A - ICMS bruto (icms_a): SUM(vlr_arrecadado) dos registros
    com receita_class_subgrupo = 'ICMS'. Inclui FECOP.
B - FECOP (fecop_b): SUM(vlr_arrecadado) apenas dos registros
    de A com tip_fecop = 1. É subconjunto de A.
C - ICMS sem FECOP (icms_sem_fecop_c): A - B.
D - ICMS líquido Tesouro (icms_liquido_tesouro_d): 0,60 * C.

Use report_type="icms_fecop" em pedidos de composição,
detalhamento conjunto, comparação de ICMS e FECOP, ou quando
forem mencionados FECOP, ICMS sem FECOP ou ICMS líquido Tesouro
como indicadores. O relatório retorna A, B, C e D juntos,
mesmo quando a pergunta destacar um dos indicadores.

Neste relatório, use metric="valor_arrecadado" e não filtre
receita individual: receita=null. A restrição ao subgrupo
ICMS é aplicada diretamente no SQL; subgrupo="ICMS" ou null
são compatíveis. Não selecione outros subgrupos.

Agrupamentos suportados no relatório: group_by="decendio" ou
group_by="total". Tipos de análise: aggregate e compare_periods.
Em pedidos por decêndio, use group_by="decendio", decendio=null.
Em pedidos restritos a um único decêndio, use group_by="total"
e decendio=1, 2 ou 3. Sem agrupamento, use group_by="total".

Para um ano inteiro solicitado "por decêndio", cada linha
agrega os decêndios de mesmo número dos 12 meses, sem separar
mês a mês. Não crie um agrupamento novo.
Para comparação de meses, preserve os dois intervalos completos
e use compare_periods, com labels nome_mes_ano.

A disponibilidade de dados deve ser verificada no banco.
Não considere um período sem registros como arrecadação zero
nem altere períodos explicitamente solicitados.

Exemplos:
- "Composição de ICMS e FECOP por decêndio em dezembro de 2025":
  report_type="icms_fecop", analysis_type="aggregate",
  group_by="decendio", start_date="2025-12-01",
  end_date="2025-12-31", decendio=null.
- "Compare ICMS, FECOP, ICMS sem FECOP e ICMS líquido Tesouro
  por decêndio entre setembro de 2025 e setembro de 2026":
  report_type="icms_fecop", analysis_type="compare_periods",
  group_by="decendio", decendio=null; ambos os intervalos.
- "Arrecadação de ICMS por decêndio":
  report_type="standard" quando não houver pedido de composição
  nem referência a FECOP, C ou D.

REGRAS GERAIS:

- Diferencie agrupamentos de filtros.
- Não confunda descrição de receita com subgrupo.
- Não aplique filtros implícitos sem evidência.
- Utilize os valores reais dos catálogos fornecidos.
- Priorize correspondências exatas com os catálogos.
- Não invente classificações de receitas.
- Quando houver referência explícita a um subgrupo
  conhecido, prefira subgrupo ao filtro receita.
- A interpretação deve respeitar o contrato QuerySpec.
"""
