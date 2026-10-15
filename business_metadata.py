
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
