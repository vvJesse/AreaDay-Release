"""The spreadsheet the workbench hands to a reader.

The sheet mirrors the workbook the product ships: fifteen labelled columns, a
sheet of the words to learn (个人词表) and a sheet of the words the run already
counts as known (其他候选), and every calibration row joined with its reviewed
card. ``build_personalized_workbook`` returns the xlsx bytes.

Two deliberate differences from the machine-readable
``analysis/personalized-vocabulary.tsv``: the columns are the reader-facing
labels rather than the internal field names, and the values are formatted the
way a reader reads them (``87.3%``, ``未抽到``, ``建议加入``). That file stays
untouched: the pipeline reads it.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Callable, Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.utils import get_column_letter

SHEET_SELECTED = "个人词表"
SHEET_OTHER = "其他候选"
DOWNLOAD_FILENAME = "personalized-vocabulary.xlsx"
CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Column label, field. The order is the column order of both sheets.
WORKBOOK_COLUMNS: tuple[tuple[str, str], ...] = (
    ("词", "display_form"),
    ("词性", "part_of_speech"),
    ("领域英文释义", "meaning_en"),
    ("领域中文释义", "meaning_zh"),
    ("论文原句", "context"),
    ("论文标题", "source_title"),
    ("论文链接", "source_url"),
    ("论文标识", "source_paper_id"),
    ("收录状态", "inclusion"),
    ("优先级", "importance_tier"),
    ("预测掌握度", "probability_known"),
    ("30 词回答", "direct_response"),
    ("覆盖论文数", "document_count"),
    ("出现次数", "total_count"),
    ("本次阈值", "selected_threshold"),
)

#: Columns E, F, G hold the source sentence, its paper title, and its link.
_WIDE_COLUMNS = {4: 60, 5: 36, 6: 46}

#: The worksheet writer the product ships writes a character width a fraction
#: wider than asked for; the delivered sheet keeps the very same widths.
_WIDTH_PADDING = 0.83203125

_TIER_RANK = {"A": 0, "B": 1, "C": 2, "D": 3}

#: Card fields that replace the calibration row's own copy of the same fact.
_CARD_FIELDS = (
    "display_form",
    "part_of_speech",
    "meaning_en",
    "meaning_zh",
    "context",
    "source_paper_id",
    "source_title",
    "source_url",
)

#: Characters a worksheet cannot hold. Tab, newline, and carriage return can:
#: they are a sentence's own line breaks.
_ILLEGAL_IN_WORKSHEET = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

CardLookup = Callable[[str, str], Mapping[str, Any] | None]


def read_export_rows(tsv_text: str) -> list[dict[str, str]]:
    """Read the calibration rows from the exported tab-separated file."""

    return [dict(row) for row in csv.DictReader(tsv_text.splitlines(), delimiter="\t")]


def build_personalized_workbook(rows: Sequence[Mapping[str, Any]], card_for: CardLookup) -> bytes:
    """Return the xlsx a download serves: the calm table of this run's words.

    ``card_for`` returns the reviewed card for a lemma and part of speech, or
    None when the corpus has no card for it. A row without a card keeps empty
    card columns instead of failing the download, the same way the calibration
    question drops its answer detail when a word has no card.
    """

    if not rows:
        raise ValueError("Personalized result has no rows.")
    ordered = sorted(rows, key=_sort_key)
    selected = [
        _export_row(row, card_for)
        for row in ordered
        if _classification(row) != "likely_known"
    ]
    other = [
        _export_row(row, card_for)
        for row in ordered
        if _classification(row) == "likely_known"
    ]
    workbook = Workbook()
    workbook.remove(workbook.active)
    _write_sheet(workbook.create_sheet(SHEET_SELECTED), selected)
    _write_sheet(workbook.create_sheet(SHEET_OTHER), other)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _write_sheet(sheet: Any, rows: Sequence[Mapping[str, str]]) -> None:
    sheet.append([label for label, _field in WORKBOOK_COLUMNS])
    for row in rows:
        sheet.append([row[label] for label, _field in WORKBOOK_COLUMNS])
    sheet.freeze_panes = "A2"
    last_column = get_column_letter(len(WORKBOOK_COLUMNS))
    sheet.auto_filter.ref = f"A1:{last_column}{sheet.max_row}"
    for index, width in enumerate(_column_widths(), start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width


def _column_widths() -> list[float]:
    widths = [float(min(max(len(label) + 2, 14), 36)) for label, _field in WORKBOOK_COLUMNS]
    for index, width in _WIDE_COLUMNS.items():
        widths[index] = float(width)
    return [width + _WIDTH_PADDING for width in widths]


def _export_row(row: Mapping[str, Any], card_for: CardLookup) -> dict[str, str]:
    card = card_for(
        str(row.get("lemma") or ""),
        str(row.get("part_of_speech") or ""),
    )
    merged: dict[str, Any] = {**row}
    if card is not None:
        merged.update({field: card[field] for field in _CARD_FIELDS if field in card})
    merged["inclusion"] = _inclusion(row)
    merged["display_form"] = (
        str(card.get("display_form") or "").strip() if card is not None else ""
    ) or str(row.get("lemma") or "")
    merged["probability_known"] = _percent(row.get("probability_known"), places=1)
    merged["selected_threshold"] = _percent(row.get("selected_threshold"), places=0)
    merged["direct_response"] = str(row.get("direct_response") or "") or "未抽到"
    return {
        label: _cell_value(merged.get(field))
        for label, field in WORKBOOK_COLUMNS
    }


def _inclusion(row: Mapping[str, Any]) -> str:
    if _classification(row) == "likely_known":
        return "暂不加入"
    if _flag(row.get("important_boundary_protected")):
        return "重要词保护后加入"
    return "建议加入"


def _cell_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    text = str(value).strip()
    if not text:
        return ""
    number = _number(text)
    if number is not None and text.lstrip("+-").replace(".", "", 1).isdigit():
        return int(number) if number.is_integer() else number
    return _worksheet_text(text)


def _worksheet_text(text: str) -> str:
    """Escape the characters a worksheet cannot hold the way Excel reads them back.

    A extracted sentence can carry a control character (``13.7\x01C``); written
    raw it makes the file unreadable. ``_xHHHH_`` is the escape Excel itself
    uses, so the cell shows the sentence the corpus contains.
    """

    return _ILLEGAL_IN_WORKSHEET.sub(lambda match: f"_x{ord(match.group()):04X}_", text)


def _classification(row: Mapping[str, Any]) -> str:
    return str(row.get("classification") or "").strip()


def _flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"true", "1", "yes"}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value or "").strip())
    except ValueError:
        return None


def _percent(value: Any, places: int) -> str:
    number = _number(value)
    if number is None:
        return ""
    # The percentage is rounded from the exact value of the double, not from a
    # shortened decimal: 12.349999999999999644729% is 12.3%, and 6.25% is 6.3%
    # because a tie goes away from zero.
    step = Decimal(1).scaleb(-places)
    rounded = Decimal(number * 100).quantize(step, rounding=ROUND_HALF_UP)
    return f"{rounded:.{places}f}%"


def _sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """Order the sheets: the words to learn first, then tier, then certainty."""

    probability = _number(row.get("probability_known"))
    return (
        0 if _classification(row) != "likely_known" else 1,
        _TIER_RANK.get(str(row.get("importance_tier") or "").strip(), 4),
        1.0 if probability is None else probability,
        -(_number(row.get("document_count")) or 0.0),
        -(_number(row.get("total_count")) or 0.0),
        str(row.get("lemma") or ""),
    )


__all__ = [
    "CONTENT_TYPE",
    "DOWNLOAD_FILENAME",
    "SHEET_OTHER",
    "SHEET_SELECTED",
    "WORKBOOK_COLUMNS",
    "build_personalized_workbook",
    "read_export_rows",
]
