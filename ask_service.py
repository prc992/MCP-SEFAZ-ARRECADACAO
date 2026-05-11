from schemas import QuerySpec
from catalog_service import listar_segmentos, listar_subgrupos_receita
import re
from datetime import date
from calendar import monthrange
from functools import lru_cache


MESES = {
    "janeiro": 1,
    "fevereiro": 2,
    "março": 3,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}

def detectar_group_by(texto: str):
    texto_norm = normalizar_texto(texto)

    termos_subgrupo = [
        "subgrupo",
        "subgrupo de receita",
        "grupo de receita",
        "agrupamento de receita",
        "classificacao da receita",
        "classe da receita",
        "tipo de receita",
        "categoria da receita",
        "natureza da receita",
    ]

    termos_receita = [
        "receita",
        "descricao da receita",
        "descrição da receita",
        "nome da receita",
    ]

    termos_codigo = [
        "codigo",
        "codigo da receita",
        "cod receita",
        "cod_receita",
    ]

    termos_data = [
        "data",
        "dia",
        "pagamento",
        "tempo",
        "serie diaria",
        "série diária",
        "evolucao",
        "evolução",
    ]

    termos_segmento = [
        "segmento",
        "segmento economico",
        "segmento econômico",
        "setor",
        "setor economico",
        "setor econômico",
    ]

    if any(termo in texto_norm for termo in termos_data):
        return "data_pagamento"

    if any(termo in texto_norm for termo in termos_codigo):
        return "codigo_receita"

    if any(termo in texto_norm for termo in termos_subgrupo):
        return "subgrupo"

    # precisa vir depois de subgrupo para não capturar "grupo de receita" como "receita"
    if any(termo in texto_norm for termo in termos_receita):
        return "receita"

    if any(termo in texto_norm for termo in termos_segmento):
        return "segmento"

    return "segmento"

def intervalo_mes(nome_mes: str, ano: int):
    numero_mes = MESES[nome_mes]
    ultimo_dia = monthrange(ano, numero_mes)[1]

    start_date = date(ano, numero_mes, 1).isoformat()
    end_date = date(ano, numero_mes, ultimo_dia).isoformat()

    return start_date, end_date


def extrair_intervalo_datas(texto: str):
    for nome_mes, numero_mes in MESES.items():
        padrao = rf"(m[eê]s\s+de\s+)?{nome_mes}\s+de\s+(\d{{4}})"
        match = re.search(padrao, texto)

        if match:
            ano = int(match.group(2))
            ultimo_dia = monthrange(ano, numero_mes)[1]

            start_date = date(ano, numero_mes, 1).isoformat()
            end_date = date(ano, numero_mes, ultimo_dia).isoformat()

            return start_date, end_date

    return None, None


def extrair_comparacao_meses(texto: str):
    """
    Detecta padrões:
    - abril e maio de 2026
    - abril vs maio de 2026
    - abril contra maio de 2026
    - abril de 2025 e abril de 2026
    - abril de 2025 vs maio de 2026
    """

    nomes_meses = "|".join(MESES.keys())

    # Caso 1:
    # abril de 2025 e abril de 2026
    # abril de 2025 vs maio de 2026
    padrao_mes_ano_vs_mes_ano = (
        rf"({nomes_meses})\s+de\s+(\d{{4}})\s+"
        rf"(?:e|vs|contra|com|entre)\s+"
        rf"({nomes_meses})\s+de\s+(\d{{4}})"
    )

    match = re.search(padrao_mes_ano_vs_mes_ano, texto)

    if match:
        mes_1 = match.group(1)
        ano_1 = int(match.group(2))
        mes_2 = match.group(3)
        ano_2 = int(match.group(4))

        p1_start, p1_end = intervalo_mes(mes_1, ano_1)
        p2_start, p2_end = intervalo_mes(mes_2, ano_2)

        return {
            "period_1_start": p1_start,
            "period_1_end": p1_end,
            "period_1_label": f"{mes_1}_{ano_1}",
            "period_2_start": p2_start,
            "period_2_end": p2_end,
            "period_2_label": f"{mes_2}_{ano_2}",
        }

    # Caso 2:
    # abril e maio de 2026
    # abril vs maio de 2026
    padrao_mes_vs_mes_mesmo_ano = (
        rf"({nomes_meses})\s+"
        rf"(?:e|vs|contra|com|entre)\s+"
        rf"({nomes_meses})\s+de\s+(\d{{4}})"
    )

    match = re.search(padrao_mes_vs_mes_mesmo_ano, texto)

    if match:
        mes_1 = match.group(1)
        mes_2 = match.group(2)
        ano = int(match.group(3))

        p1_start, p1_end = intervalo_mes(mes_1, ano)
        p2_start, p2_end = intervalo_mes(mes_2, ano)

        return {
            "period_1_start": p1_start,
            "period_1_end": p1_end,
            "period_1_label": f"{mes_1}_{ano}",
            "period_2_start": p2_start,
            "period_2_end": p2_end,
            "period_2_label": f"{mes_2}_{ano}",
        }

    return None

@lru_cache(maxsize=1)
def listar_segmentos_cache():
    return listar_segmentos()


@lru_cache(maxsize=1)
def listar_subgrupos_cache():
    return listar_subgrupos_receita()

def extrair_valor_catalogo(texto: str, valores: list[str]):
    texto_norm = normalizar_texto(texto)

    melhor_valor = None
    melhor_score = 0

    for valor in valores:
        if not valor:
            continue

        valor_limpo = valor.strip()

        if not valor_limpo:
            continue

        valor_norm = normalizar_texto(valor_limpo)

        if not valor_norm:
            continue

        # match completo
        if valor_norm in texto_norm:
            return valor_limpo

        palavras_valor = set(valor_norm.split())
        palavras_texto = set(texto_norm.split())

        if not palavras_valor:
            continue

        intersecao = palavras_valor.intersection(palavras_texto)

        score = len(intersecao) / len(palavras_valor)

        palavras_informativas = {
            p for p in intersecao
            if len(p) >= 5
        }

        if palavras_informativas:
            score += 0.25

        if score > melhor_score:
            melhor_score = score
            melhor_valor = valor_limpo

    if melhor_score >= 0.45:
        return melhor_valor

    return None

def normalizar_texto(texto: str) -> str:
    texto = texto.lower()

    texto = texto.replace("á", "a")
    texto = texto.replace("à", "a")
    texto = texto.replace("ã", "a")
    texto = texto.replace("â", "a")
    texto = texto.replace("é", "e")
    texto = texto.replace("ê", "e")
    texto = texto.replace("í", "i")
    texto = texto.replace("ó", "o")
    texto = texto.replace("ô", "o")
    texto = texto.replace("õ", "o")
    texto = texto.replace("ú", "u")
    texto = texto.replace("ç", "c")

    # remove espaços extras no começo/fim e colapsa múltiplos espaços
    texto = " ".join(texto.split())

    return texto

def extrair_segmento(texto: str):
    return extrair_valor_catalogo(texto, listar_segmentos_cache())

def extrair_subgrupo(texto: str):
    return extrair_valor_catalogo(texto, listar_subgrupos_cache())

def extrair_ultimos_meses(texto: str):
    texto_norm = normalizar_texto(texto)

    match = re.search(r"ultimos\s+(\d+)\s+meses", texto_norm)
    if match:
        return int(match.group(1))

    match = re.search(r"ultimo\s+(\d+)\s+meses", texto_norm)
    if match:
        return int(match.group(1))

    if "ultimo ano" in texto_norm or "ultimos 12 meses" in texto_norm:
        return 12

    return None


def interpretar_pergunta(question: str) -> QuerySpec:
    texto = question.lower()

    segmento = extrair_segmento(question)
    subgrupo = extrair_subgrupo(question)
    months_back = extrair_ultimos_meses(question)

    comparacao = extrair_comparacao_meses(texto)

    if "documento" in texto or "dae" in texto or "quantidade" in texto:
        metric = "qtd_documentos"
    else:
        metric = "valor_arrecadado"

    group_by = detectar_group_by(question)

    if group_by == "data_pagamento":
        chart_type = "line"
        top_n = None
    else:
        chart_type = "bar"
        top_n = 10

    if comparacao:
        return QuerySpec(
            metric=metric,
            group_by=group_by,
            chart_type="bar",
            top_n=top_n,
            analysis_type="compare_periods",
            period_1_start=comparacao["period_1_start"],
            period_1_end=comparacao["period_1_end"],
            period_1_label=comparacao["period_1_label"],
            period_2_start=comparacao["period_2_start"],
            period_2_end=comparacao["period_2_end"],
            period_2_label=comparacao["period_2_label"],
            segmento=segmento,
            subgrupo=subgrupo,
        )

    if months_back:
        return QuerySpec(
            metric=metric,
            group_by="mes",
            chart_type="line",
            top_n=None,
            analysis_type="time_series",
            months_back=months_back,
            segmento=segmento,
            subgrupo=subgrupo,
        )
    
    start_date, end_date = extrair_intervalo_datas(texto)

    return QuerySpec(
        metric=metric,
        group_by=group_by,
        chart_type=chart_type,
        top_n=top_n,
        start_date=start_date,
        end_date=end_date,
        segmento=segmento,
        subgrupo=subgrupo,
    )


def gerar_summary(spec: QuerySpec) -> str:
    metric_label = {
        "valor_arrecadado": "valor arrecadado",
        "qtd_documentos": "quantidade de DAE pagos"
    }

    group_by_label = {
        "data_pagamento": "data de pagamento",
        "receita": "receita",
        "codigo_receita": "código da receita",
        "subgrupo": "subgrupo da receita",
        "segmento": "segmento"
    }

    if spec.analysis_type == "time_series":
        partes = [
            f"Consulta interpretada como série temporal mensal de {metric_label[spec.metric]}"
        ]

        if spec.months_back:
            partes.append(f"nos últimos {spec.months_back} meses")

        if spec.segmento:
            partes.append(f"filtrando o segmento {spec.segmento}")

        if spec.subgrupo:
            partes.append(f"filtrando o grupo de receita {spec.subgrupo}")

        if spec.receita:
            partes.append(f"filtrando a receita {spec.receita}")

        partes.append(f"com gráfico do tipo {spec.chart_type}")

        return ", ".join(partes) + "."    

    if spec.analysis_type == "compare_periods":
        return (
            f"Consulta interpretada como comparação de {metric_label[spec.metric]} "
            f"por {group_by_label[spec.group_by]}, comparando "
            f"{spec.period_1_label} contra {spec.period_2_label}, "
            f"com cálculo de diferença, variação percentual e tendência."
        )

    partes = [
        f"Consulta interpretada como {metric_label[spec.metric]} por {group_by_label[spec.group_by]}"
    ]

    if spec.start_date and spec.end_date:
        partes.append(f"no período de {spec.start_date} a {spec.end_date}")

    if spec.top_n is not None:
        partes.append(f"retornando o top {spec.top_n}")

    partes.append(f"com gráfico do tipo {spec.chart_type}")

    return ", ".join(partes) + "."