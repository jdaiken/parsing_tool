"""
PDF text extraction that respects redaction boxes.

A common redaction mistake is drawing a black box over text without removing
the text, so it can still be copied out of the PDF. Text that sits under a
dark filled box and is itself dark (so it is invisible on the page) is treated
as redacted: it is replaced with "█" and counted, never returned as readable
text. White text on a dark banner (a styled header) is left alone.

Scanned pages (images with no text layer) are read with OCR when it is
installed (see ocr.py); otherwise they are counted so the app can say so.

Statements that print money in and money out in separate columns ("Deposits/
Additions" and "Withdrawals/Subtractions") without signs lose that column when
the page is turned into text. On such pages each amount is tagged " CR" or
" DR" from the column heading it sits under, so the reader knows its direction.
"""

from __future__ import annotations

import copy
import hashlib
from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO
from typing import List, Optional, Sequence

import re

import pdfplumber

from ocr import ocr_available, ocr_image, render_page

REDACTION_CHAR = "█"


@dataclass
class ExtractedPdf:
    pages: List[str]
    hidden_chars: int  # characters that were under black boxes but still present in the file
    hidden_lines: int  # lines containing such characters
    ocr_pages: int = 0  # scanned pages read with OCR
    unread_scanned_pages: int = 0  # scanned pages that couldn't be read because OCR isn't available
    image_redaction_boxes: int = 0  # black boxes found on scanned pages

    @property
    def has_leaky_redactions(self) -> bool:
        return self.hidden_chars > 0


def _luminance(color: Optional[Sequence[float]]) -> float:
    """0 = black, 1 = white, for the gray/RGB/CMYK color tuples pdfplumber reports."""
    if color is None:
        return 0.0  # PDF default fill color is black
    if isinstance(color, (int, float)):
        color = (color,)
    values = [float(v) for v in color if isinstance(v, (int, float))]
    if len(values) == 1:
        return values[0]
    if len(values) == 3:
        r, g, b = values
        return 0.299 * r + 0.587 * g + 0.114 * b
    if len(values) == 4:
        c, m, y, k = values
        return (1 - c) * (1 - m) * (1 - y) * (1 - k) * 0.6 + (1 - k) * 0.4
    return 1.0


def _redaction_boxes(page) -> List[dict]:
    """Dark filled rectangles small enough to be redaction marks rather than page backgrounds."""
    page_area = float(page.width) * float(page.height)
    boxes = []
    for rect in page.rects:
        if not rect.get("fill"):
            continue
        if _luminance(rect.get("non_stroking_color")) > 0.25:
            continue
        if rect["width"] * rect["height"] > page_area * 0.25 or rect["height"] < 4:
            continue
        boxes.append(rect)
    return boxes


def _hide_covered_chars(page) -> tuple[int, int]:
    """Replace dark characters under redaction boxes with REDACTION_CHAR; return (chars, lines) hidden."""
    boxes = _redaction_boxes(page)
    if not boxes:
        return 0, 0
    hidden = 0
    lines = set()
    for char in page.chars:
        if _luminance(char.get("non_stroking_color")) > 0.5:
            continue  # light text on a dark banner is meant to be seen
        cx = (char["x0"] + char["x1"]) / 2
        cy = (char["top"] + char["bottom"]) / 2
        for box in boxes:
            if box["x0"] <= cx <= box["x1"] and box["top"] <= cy <= box["bottom"]:
                if char["text"].strip():
                    char["text"] = REDACTION_CHAR
                    hidden += 1
                    lines.add(round(char["top"]))
                break
    return hidden, len(lines)


_CACHE: "OrderedDict[str, ExtractedPdf]" = OrderedDict()


def extract_pdf(file_bytes: bytes, progress=None) -> ExtractedPdf:
    """
    Text of every page. `progress(done, total)` is called while scanned pages are OCR'd.
    Results are kept for recently read files, so changing a setting doesn't repeat OCR.
    """
    key = hashlib.sha256(file_bytes).hexdigest()
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return copy.deepcopy(_CACHE[key])
    result = _extract(file_bytes, progress)
    _CACHE[key] = copy.deepcopy(result)
    while len(_CACHE) > 20:
        _CACHE.popitem(last=False)
    return result


def _extract(file_bytes: bytes, progress=None) -> ExtractedPdf:
    result = ExtractedPdf(pages=[], hidden_chars=0, hidden_lines=0)
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        scanned = [i for i, page in enumerate(pdf.pages) if _is_scanned(page)]
        for index, page in enumerate(pdf.pages):
            if index in scanned:
                result.pages.append(_read_scanned_page(file_bytes, index, result))
                if progress and ocr_available():
                    progress(scanned.index(index) + 1, len(scanned))
                continue
            chars, lines = _hide_covered_chars(page)
            result.hidden_chars += chars
            result.hidden_lines += lines
            result.pages.append(_text_with_column_tags(page) or page.extract_text() or "")
    return result


_CREDIT_HEADING = re.compile(r"^(deposits?|credits?|additions|deposits/?|credits/?|money\s*in)\b", re.IGNORECASE)
_DEBIT_HEADING = re.compile(r"^(withdrawals?|debits?|subtractions|withdrawals/?|debits/?|charges|money\s*out)\b", re.IGNORECASE)
_AMOUNT_WORD = re.compile(r"^\(?-?\$?\d{1,3}(?:,\d{3})*\.\d{2}\)?-?$")


def _group_lines(words: List[dict], tolerance: float = 3.0) -> List[List[dict]]:
    lines: List[List[dict]] = []
    for word in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if lines and abs(lines[-1][0]["top"] - word["top"]) <= tolerance:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def _text_with_column_tags(page) -> Optional[str]:
    """Page text with amounts tagged CR/DR by column, or None if the page has no such columns."""
    words = page.extract_words()
    lines = _group_lines(words)
    columns: List[tuple] = []  # (top of heading line, credit right edge, debit right edge)
    for line in lines:
        credit = [w for w in line if _CREDIT_HEADING.match(w["text"])]
        debit = [w for w in line if _DEBIT_HEADING.match(w["text"])]
        if credit and debit and not any(_AMOUNT_WORD.match(w["text"]) for w in line):
            columns.append((line[0]["top"], credit[0]["x1"], debit[0]["x1"]))
    if not columns:
        return None
    gap = abs(columns[0][1] - columns[0][2])
    out: List[str] = []
    for line in lines:
        heading = [c for c in columns if c[0] < line[0]["top"]]
        parts = []
        for word in line:
            text = word["text"]
            if heading and _AMOUNT_WORD.match(text):
                _, credit_x, debit_x = heading[-1]
                # Amounts are right-aligned under their heading; take the nearer column if it is close.
                to_credit, to_debit = abs(word["x1"] - credit_x), abs(word["x1"] - debit_x)
                if min(to_credit, to_debit) < gap * 0.6:
                    text += " CR" if to_credit < to_debit else " DR"
            parts.append(text)
        out.append(" ".join(parts))
    return "\n".join(out)


def _is_scanned(page) -> bool:
    """A page that is a picture of text: images but (almost) no text layer."""
    return bool(page.images) and len((page.extract_text() or "").strip()) < 20


def _read_scanned_page(file_bytes: bytes, index: int, result: ExtractedPdf) -> str:
    if not ocr_available():
        result.unread_scanned_pages += 1
        return ""
    image = render_page(file_bytes, index)
    if image is None:
        result.unread_scanned_pages += 1
        return ""
    text, boxes = ocr_image(image)
    result.ocr_pages += 1
    result.image_redaction_boxes += boxes
    return text
