#!/usr/bin/env python3
"""Render the AreaDay Markdown guide as a polished, clickable Chinese PDF."""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    CondPageBreak,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "customer-guide" / "AreaDay-安装和使用指南.md"
OUTPUT_DIR = ROOT / "docs" / "customer-guide"
DOCUMENT_VERSION = ""

GREEN = colors.HexColor("#0F766E")
GREEN_DARK = colors.HexColor("#134E4A")
GREEN_PALE = colors.HexColor("#ECFDF5")
INK = colors.HexColor("#17212B")
MUTED = colors.HexColor("#5E6C76")
LINE = colors.HexColor("#D7E3E0")
CODE_BG = colors.HexColor("#F4F7F6")
WARNING_BG = colors.HexColor("#FFF8E7")


def register_fonts() -> None:
    pdfmetrics.registerFont(
        TTFont("AreaDayCN", "/System/Library/Fonts/STHeiti Light.ttc", subfontIndex=0)
    )
    pdfmetrics.registerFont(
        TTFont("AreaDayCNBold", "/System/Library/Fonts/STHeiti Medium.ttc", subfontIndex=0)
    )
    pdfmetrics.registerFontFamily(
        "AreaDayCN",
        normal="AreaDayCN",
        bold="AreaDayCNBold",
        italic="AreaDayCN",
        boldItalic="AreaDayCNBold",
    )


def inline_markup(text: str) -> str:
    tokens: dict[str, str] = {}

    def hold(value: str) -> str:
        key = f"TOKEN{len(tokens):04d}TOKEN"
        tokens[key] = value
        return key

    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        lambda m: hold(
            f'<link href="{html.escape(m.group(2), quote=True)}" '
            f'color="#0F766E"><u>{html.escape(m.group(1))}</u></link>'
        ),
        text,
    )
    text = re.sub(
        r"<(https?://[^>]+)>",
        lambda m: hold(
            f'<link href="{html.escape(m.group(1), quote=True)}" '
            f'color="#0F766E"><u>{html.escape(m.group(1))}</u></link>'
        ),
        text,
    )
    text = re.sub(
        r"`([^`]+)`",
        lambda m: hold(
            f'<font name="AreaDayCNBold" color="#134E4A">{html.escape(m.group(1))}</font>'
        ),
        text,
    )
    text = re.sub(
        r"\*\*([^*]+)\*\*",
        lambda m: hold(f"<b>{html.escape(m.group(1))}</b>"),
        text,
    )
    rendered = html.escape(text)
    for key, value in tokens.items():
        rendered = rendered.replace(key, value)
    return rendered


def make_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TitleCN",
            parent=base["Title"],
            fontName="AreaDayCNBold",
            fontSize=28,
            leading=38,
            textColor=GREEN_DARK,
            alignment=TA_LEFT,
            spaceAfter=8 * mm,
        ),
        "h2": ParagraphStyle(
            "H2CN",
            parent=base["Heading2"],
            fontName="AreaDayCNBold",
            fontSize=17,
            leading=24,
            textColor=GREEN_DARK,
            spaceBefore=7 * mm,
            spaceAfter=3 * mm,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "H3CN",
            parent=base["Heading3"],
            fontName="AreaDayCNBold",
            fontSize=12.5,
            leading=19,
            textColor=GREEN,
            spaceBefore=4 * mm,
            spaceAfter=2 * mm,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "BodyCN",
            parent=base["BodyText"],
            fontName="AreaDayCN",
            fontSize=10.2,
            leading=17.2,
            textColor=INK,
            spaceAfter=2.5 * mm,
            wordWrap="CJK",
        ),
        "lead": ParagraphStyle(
            "LeadCN",
            parent=base["BodyText"],
            fontName="AreaDayCN",
            fontSize=12,
            leading=20,
            textColor=MUTED,
            spaceAfter=5 * mm,
            wordWrap="CJK",
        ),
        "bullet": ParagraphStyle(
            "BulletCN",
            parent=base["BodyText"],
            fontName="AreaDayCN",
            fontSize=10.1,
            leading=16.5,
            textColor=INK,
            leftIndent=5 * mm,
            firstLineIndent=-3.5 * mm,
            spaceAfter=1.6 * mm,
            wordWrap="CJK",
        ),
        "number": ParagraphStyle(
            "NumberCN",
            parent=base["BodyText"],
            fontName="AreaDayCN",
            fontSize=10.1,
            leading=16.5,
            textColor=INK,
            leftIndent=7 * mm,
            firstLineIndent=-5 * mm,
            spaceAfter=1.8 * mm,
            wordWrap="CJK",
        ),
        "quote": ParagraphStyle(
            "QuoteCN",
            parent=base["BodyText"],
            fontName="AreaDayCN",
            fontSize=10.5,
            leading=17.5,
            textColor=GREEN_DARK,
            wordWrap="CJK",
        ),
        "code": ParagraphStyle(
            "CodeCN",
            parent=base["BodyText"],
            fontName="AreaDayCN",
            fontSize=8.8,
            leading=14.3,
            textColor=colors.HexColor("#23312F"),
            wordWrap="CJK",
        ),
        "small": ParagraphStyle(
            "SmallCN",
            parent=base["BodyText"],
            fontName="AreaDayCN",
            fontSize=8.2,
            leading=12,
            textColor=MUTED,
            alignment=TA_CENTER,
        ),
    }


def boxed(paragraph: Paragraph, background, border=LINE, left_bar=None):
    style = [
        ("BACKGROUND", (0, 0), (-1, -1), background),
        ("BOX", (0, 0), (-1, -1), 0.7, border),
        ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 4 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
    ]
    if left_bar:
        style.append(("LINEBEFORE", (0, 0), (0, -1), 3, left_bar))
    table = Table([[paragraph]], colWidths=[168 * mm])
    table.setStyle(TableStyle(style))
    return table


def parse_markdown(markdown: str, styles):
    story = []
    lines = markdown.splitlines()
    paragraph_lines: list[str] = []
    in_code = False
    code_lines: list[str] = []
    body_count = 0

    def flush_paragraph():
        nonlocal paragraph_lines, body_count
        if not paragraph_lines:
            return
        raw = " ".join(line.strip() for line in paragraph_lines)
        style = styles["lead"] if body_count == 0 else styles["body"]
        story.append(Paragraph(inline_markup(raw), style))
        body_count += 1
        paragraph_lines = []

    for line in lines:
        if line.startswith("```"):
            flush_paragraph()
            if in_code:
                safe_lines = [inline_markup(part) for part in code_lines]
                code_para = Paragraph("<br/>".join(safe_lines), styles["code"])
                story.append(boxed(code_para, CODE_BG))
                story.append(Spacer(1, 2.5 * mm))
                code_lines = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(line if line else " ")
            continue
        if not line.strip():
            flush_paragraph()
            continue
        if line.startswith("# "):
            flush_paragraph()
            story.append(Spacer(1, 8 * mm))
            story.append(Paragraph(inline_markup(line[2:].strip()), styles["title"]))
            continue
        if line.startswith("## "):
            flush_paragraph()
            heading = line[3:].strip()
            if heading == "七、常见问题":
                story.append(PageBreak())
            else:
                story.append(CondPageBreak(44 * mm))
            story.append(Paragraph(inline_markup(heading), styles["h2"]))
            continue
        if line.startswith("### "):
            flush_paragraph()
            story.append(CondPageBreak(30 * mm))
            story.append(Paragraph(inline_markup(line[4:].strip()), styles["h3"]))
            continue
        if line.startswith("> "):
            flush_paragraph()
            quote = Paragraph(inline_markup(line[2:].strip()), styles["quote"])
            story.append(boxed(quote, GREEN_PALE, left_bar=GREEN))
            story.append(Spacer(1, 3 * mm))
            continue
        bullet = re.match(r"^-\s+(.*)$", line)
        if bullet:
            flush_paragraph()
            story.append(Paragraph(inline_markup(bullet.group(1)), styles["bullet"], bulletText="•"))
            continue
        numbered = re.match(r"^(\d+)\.\s+(.*)$", line)
        if numbered:
            flush_paragraph()
            story.append(
                Paragraph(
                    inline_markup(numbered.group(2)),
                    styles["number"],
                    bulletText=f"{numbered.group(1)}.",
                )
            )
            continue
        paragraph_lines.append(line)

    flush_paragraph()
    return story


def draw_page(canvas, doc):
    canvas.saveState()
    width, height = A4
    if doc.page == 1:
        canvas.setFillColor(GREEN)
        canvas.rect(0, height - 13 * mm, width, 13 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("AreaDayCNBold", 9)
        canvas.drawString(20 * mm, height - 8.4 * mm, "AreaDay  ·  把研究语言变成自己的词表")
    else:
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.5)
        canvas.line(20 * mm, height - 14 * mm, width - 20 * mm, height - 14 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont("AreaDayCN", 8)
        canvas.drawString(20 * mm, height - 10.5 * mm, "AreaDay 安装和使用指南")

    canvas.setStrokeColor(LINE)
    canvas.line(20 * mm, 14 * mm, width - 20 * mm, 14 * mm)
    canvas.setFillColor(MUTED)
    canvas.setFont("AreaDayCN", 8)
    footer = f"AreaDay v{DOCUMENT_VERSION}  ·  视频教程：guide.areaday.app"
    canvas.drawString(20 * mm, 9.5 * mm, footer)
    canvas.drawRightString(width - 20 * mm, 9.5 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


def build() -> None:
    global DOCUMENT_VERSION
    register_fonts()
    styles = make_styles()
    markdown = SOURCE.read_text(encoding="utf-8")
    version_match = re.search(r"适用版本：AreaDay v(\d+\.\d+\.\d+)", markdown)
    if version_match is None:
        raise ValueError("guide must declare '适用版本：AreaDay vMAJOR.MINOR.PATCH'")
    DOCUMENT_VERSION = version_match.group(1)
    output = OUTPUT_DIR / f"AreaDay-安装和使用指南-v{DOCUMENT_VERSION}.pdf"
    story = parse_markdown(markdown, styles)

    doc = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=21 * mm,
        rightMargin=21 * mm,
        topMargin=20 * mm,
        bottomMargin=27 * mm,
        title="AreaDay 安装和使用指南",
        author="AreaDay",
        subject=f"AreaDay {DOCUMENT_VERSION} 安装与基本使用",
        creator="AreaDay",
    )
    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    print(output)


if __name__ == "__main__":
    try:
        build()
    except Exception as exc:
        print(f"PDF build failed: {exc}", file=sys.stderr)
        raise
