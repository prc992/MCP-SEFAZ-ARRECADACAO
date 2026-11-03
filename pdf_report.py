"""Exportação de relatórios já exibidos, sem reconsultar o Redshift.

Os dados são fornecidos pelo Playground e os gráficos são capturas PNG dos
Plotly renderizados no navegador. O endpoint não armazena o documento.
"""
from __future__ import annotations

import base64
import binascii
from io import BytesIO
from xml.sax.saxutils import escape

from pydantic import BaseModel, Field


class PdfChart(BaseModel):
    title: str = Field(max_length=200)
    image: str = Field(max_length=5_000_000)


class PdfReportRequest(BaseModel):
    question: str = Field(max_length=2000)
    period: str = Field(max_length=300)
    notice: str | None = Field(default=None, max_length=1000)
    columns: list[str] = Field(min_length=1, max_length=18)
    rows: list[list[str]] = Field(default_factory=list, max_length=1000)
    charts: list[PdfChart] = Field(min_length=1, max_length=4)


def _png_bytes(data_uri: str) -> bytes:
    from PIL import Image as PILImage

    prefix = "data:image/png;base64,"
    if not data_uri.startswith(prefix):
        raise ValueError("Formato de imagem inválido: PNG esperado.")
    try:
        image_bytes = base64.b64decode(data_uri[len(prefix):], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Imagem do gráfico não pôde ser decodificada.") from exc
    if not image_bytes or len(image_bytes) > 4_000_000:
        raise ValueError("O gráfico ultrapassa o limite permitido de 4 MB.")
    try:
        with PILImage.open(BytesIO(image_bytes)) as img:
            if img.format != "PNG" or img.width * img.height > 8_000_000 or img.width < 100 or img.height < 100:
                raise ValueError("Dimensões ou formato de gráfico inválidos.")
            img.verify()
    except (OSError, SyntaxError) as exc:
        raise ValueError("Imagem do gráfico inválida.") from exc
    return image_bytes


def gerar_pdf_relatorio(report: PdfReportRequest) -> bytes:
    """Gera PDF A4 paisagem, com tabela paginada e imagens de até quatro gráficos.

    Requer reportlab e Pillow no ambiente da API. Não realiza SQL e não recalcula
    os indicadores. A tabela replica os valores já formatados pelo navegador.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, LongTable, PageBreak, Paragraph, SimpleDocTemplate, TableStyle

    if any(len(row) != len(report.columns) for row in report.rows):
        raise ValueError("A tabela contém linhas com número de colunas diferente do cabeçalho.")
    if any(len(value) > 500 for row in report.rows for value in row):
        raise ValueError("Uma célula da tabela excedeu o limite de 500 caracteres.")
    if any(len(column) > 160 for column in report.columns):
        raise ValueError("Um título de coluna excedeu o limite permitido.")

    images = [_png_bytes(chart.image) for chart in report.charts]
    output = BytesIO()
    page_width, page_height = landscape(A4)
    margin = 17 * mm
    usable_width = page_width - 2 * margin
    doc = SimpleDocTemplate(output, pagesize=(page_width, page_height),
                            leftMargin=margin, rightMargin=margin,
                            topMargin=margin, bottomMargin=margin + 5 * mm,
                            title="Faro - Relatório de arrecadação", author="Faro - SEFAZ")

    styles = getSampleStyleSheet()
    heading = ParagraphStyle("FaroTitulo", parent=styles["Heading1"], fontName="Helvetica-Bold",
                             fontSize=18, leading=23, textColor=colors.HexColor("#17442e"), spaceAfter=10)
    section = ParagraphStyle("FaroSecao", parent=styles["Heading2"], fontName="Helvetica-Bold",
                             fontSize=12, leading=16, textColor=colors.HexColor("#17442e"), spaceBefore=12, spaceAfter=7)
    body = ParagraphStyle("FaroCorpo", parent=styles["Normal"], fontName="Helvetica",
                          fontSize=9, leading=13, textColor=colors.HexColor("#303b44"), spaceAfter=6)
    warning = ParagraphStyle("FaroAviso", parent=body, textColor=colors.HexColor("#7b501a"))
    num_cols = len(report.columns)
    font_size = 8 if num_cols <= 5 else (7 if num_cols <= 9 else 6.2)
    colhead = ParagraphStyle("FaroTh", parent=body, fontName="Helvetica-Bold", fontSize=font_size,
                             leading=font_size + 2, textColor=colors.HexColor("#173425"), spaceAfter=0)
    cell = ParagraphStyle("FaroTd", parent=body, fontSize=font_size, leading=font_size + 2,
                          textColor=colors.HexColor("#1e293b"), spaceAfter=0)

    def safe(text):
        return escape(str(text)).replace("\n", "<br/>")

    story = [Paragraph("Faro | Relatório de arrecadação", heading)]
    if report.period:
        story.append(Paragraph(f"<b>{safe(report.period)}</b>", body))
    if report.question:
        story.append(Paragraph(f"<b>Pergunta:</b> {safe(report.question)}", body))
    if report.notice:
        story.append(Paragraph(f"<b>Observação:</b> {safe(report.notice)}", warning))
    story.append(Paragraph("Tabela", section))

    if report.rows:
        widths_weight = []
        for index, column in enumerate(report.columns):
            observed = [len(str(row[index])) for row in report.rows[:100]]
            typical = max([len(column)] + observed)
            widths_weight.append(max(8, min(34, typical)))
        total = sum(widths_weight)
        minimum = 30 if num_cols >= 12 else 39
        widths = [max(minimum, usable_width * weight / total) for weight in widths_weight]
        # Reequilibrar proporções caso o mínimo tenha comprimido a largura disponível.
        total_width = sum(widths)
        widths = [width * usable_width / total_width for width in widths]
        table_data = [[Paragraph(safe(col), colhead) for col in report.columns]]
        table_data += [[Paragraph(safe(value), cell) for value in row] for row in report.rows]
        table = LongTable(table_data, colWidths=widths, repeatRows=1, hAlign="LEFT")
        rules = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e4eee8")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fa")]),
            ("LINEBELOW", (0, 0), (-1, 0), 0.65, colors.HexColor("#9cb1a7")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]
        for index, row in enumerate(report.rows, 1):
            if row and str(row[0]).strip().casefold() == "total geral":
                rules.extend([
                    ("BACKGROUND", (0, index), (-1, index), colors.HexColor("#e7edf3")),
                    ("LINEABOVE", (0, index), (-1, index), 1, colors.HexColor("#889aaa")),
                ])
        table.setStyle(TableStyle(rules))
        story.append(table)
    else:
        story.append(Paragraph("Nenhum registro tabular disponível no relatório.", body))

    # Uma figura por página: os rótulos visíveis permanecem legíveis no PDF.
    from PIL import Image as PILImage
    for index, img in enumerate(images, 1):
        story.extend([PageBreak(), Paragraph(f"Gráfico {index} de {len(images)}", section)])
        with PILImage.open(BytesIO(img)) as original:
            original_width, original_height = original.size
        draw_width = usable_width
        draw_height = draw_width * original_height / original_width
        if draw_height > 420:
            draw_height = 420
            draw_width = draw_height * original_width / original_height
        story.append(Image(BytesIO(img), width=draw_width, height=draw_height, hAlign="CENTER"))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#687782"))
        canvas.drawString(margin, 11 * mm, "Faro | Dados e gráficos do relatório exibido")
        canvas.drawRightString(page_width - margin, 11 * mm, f"Página {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
