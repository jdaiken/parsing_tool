"""
Optical character recognition for scanned (image-only) statement pages.

Runs entirely on this computer with RapidOCR, whose models ship inside the
pip package, so no statement image is ever sent anywhere. Black redaction
boxes are found first and replaced with "XXXX" so the reader sees them as
redactions instead of reading the labels printed inside them (e.g. "43B").

Optional: if rapidocr/onnxruntime aren't installed (or in the browser version,
where they can't run), ocr_available() is False and scanned pages are reported
to the user instead of read.
"""

from __future__ import annotations

import re
from typing import List, Optional

try:  # Heavy optional dependencies; the app works without them for text PDFs.
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw
    from rapidocr import RapidOCR
except Exception:  # pragma: no cover - depends on the environment
    RapidOCR = None

_engine = None

# OCR often reads the thousands comma as a period: "1.683.98" means 1,683.98.
_PERIOD_THOUSANDS_RE = re.compile(r"(?<![\d.,])(\d{1,3})\.(\d{3})\.(\d{2})(?![\d])")


def ocr_available() -> bool:
    """True when the OCR engine is installed (the computer and server versions; not the browser version)."""
    return RapidOCR is not None


def _get_engine():
    """The OCR engine, created on first use (loading its models takes a moment)."""
    global _engine
    if _engine is None:
        # Statement scans are upright; the text-direction classifier sometimes flips amounts
        # (reading "-69.98" as "86'9"), so it is turned off.
        _engine = RapidOCR(params={"Global.log_level": "error", "Global.use_cls": False})
    return _engine


def _mask_redaction_boxes(image: "Image.Image") -> tuple["Image.Image", int]:
    """Replace solid black rectangles with white boxes reading XXXX; return the image and box count."""
    gray = np.array(image.convert("L"))
    dark = (gray < 100).astype(np.uint8)
    # Opening with a 9x9 square erases anything thinner than 9px (all text strokes, even bold)
    # and keeps solid areas: redaction boxes, including ones that touch nearby letters.
    solid = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    # A white label inside a box ("43B") splits it in two; join pieces side by side on one line.
    solid = cv2.morphologyEx(solid, cv2.MORPH_CLOSE, np.ones((1, 45), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(solid, connectivity=8)
    out = image.convert("RGB")
    draw = ImageDraw.Draw(out)
    boxes = 0
    for index, (x, y, w, h, area) in enumerate(stats[1:], start=1):
        if w < 14 or h < 10:
            continue
        if area / float(w * h) < 0.6 and h <= 60:
            continue
        if h > gray.shape[0] * 0.5 and w > gray.shape[1] * 0.5:
            continue  # not a redaction: a page-sized dark region
        # Boxes on neighbouring lines can touch; split the shape into bands of consistent width
        # so each box is erased on its own and the text beside it survives.
        for left, top, right, bottom in _bands(labels[y : y + h, x : x + w] == index):
            bx, by, bw, bh = x + left, y + top, right - left + 1, bottom - top + 1
            if bw < 14 or bh < 10:
                continue
            draw.rectangle([bx - 2, by - 2, bx + bw + 2, by + bh + 2], fill="white")
            if bh <= 60:
                _draw_marker(draw, bx, by, bw, bh)
            boxes += 1
    return out, boxes


def _bands(mask: "np.ndarray") -> List[tuple]:
    """Split a component into (left, top, right, bottom) row bands whose horizontal extent stays the same."""
    bands: List[list] = []
    for row in range(mask.shape[0]):
        cols = np.flatnonzero(mask[row])
        if not cols.size:
            continue
        lo, hi = int(cols[0]), int(cols[-1])
        if bands and abs(bands[-1][0] - lo) <= 10 and abs(bands[-1][2] - hi) <= 10 and bands[-1][3] == row - 1:
            band = bands[-1]
            band[0], band[2], band[3] = min(band[0], lo), max(band[2], hi), row
        else:
            bands.append([lo, row, hi, row])
    return [tuple(band) for band in bands]


def _draw_marker(draw: "ImageDraw.ImageDraw", x: int, y: int, w: int, h: int) -> None:
    """Draw XXXX with simple strokes (no font file needed) so OCR reads the box as a redaction."""
    marker_h = max(8, int(h * 0.7))
    step = min(marker_h * 0.8, (w - 4) / 4)
    for i in range(4):
        left = x + 2 + i * step
        draw.line([left, y + (h - marker_h) / 2, left + step * 0.7, y + (h + marker_h) / 2], fill="black", width=2)
        draw.line([left, y + (h + marker_h) / 2, left + step * 0.7, y + (h - marker_h) / 2], fill="black", width=2)


_MONEY_ONLY_RE = re.compile(r"^[-(]?\s?[$S]?\s?-?\d{1,3}(?:[,.]\d{3})*[.,]\d{2}\)?-?$")
_LEADING_DATE_RE = re.compile(r"^\d{1,2}[/-]\d{1,2}\b")


def _boxes_to_lines(result, page_width: float) -> List[str]:
    """
    Rebuild text lines from OCR boxes.

    Text is grouped into lines by vertical position. Amount columns are handled
    separately: on scans an amount column is often shifted up or down by part of
    a line, so each column's amounts are matched in order to the dated rows
    (one amount per row per column) after measuring the column's offset.
    """
    items = []
    for box, text in zip(result.boxes, result.txts):
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        items.append({"cy": sum(ys) / len(ys), "x0": min(xs), "x1": max(xs), "h": max(ys) - min(ys), "text": text})
    if not items:
        return []
    line_h = float(np.median([it["h"] for it in items])) * 1.25

    is_amount = lambda it: it["x0"] > page_width * 0.55 and _MONEY_ONLY_RE.match(it["text"].strip())  # noqa: E731
    amounts = [it for it in items if is_amount(it)]
    others = sorted((it for it in items if not is_amount(it)), key=lambda it: it["cy"])

    lines: List[dict] = []
    for it in others:
        if lines and abs(lines[-1]["cy"] - it["cy"]) < line_h * 0.45:
            line = lines[-1]
            line["parts"].append(it)
            line["cy"] = sum(p["cy"] for p in line["parts"]) / len(line["parts"])
        else:
            lines.append({"cy": it["cy"], "parts": [it]})
    for line in lines:
        line["parts"].sort(key=lambda p: p["x0"])
        first = line["parts"][0]
        line["anchor"] = first["x0"] < page_width * 0.3 and bool(_LEADING_DATE_RE.match(first["text"].strip()))

    anchors = [line for line in lines if line["anchor"]]
    for column in _amount_columns(amounts, line_h):
        unmatched = _align_column(column, anchors, line_h) if anchors else column
        for it in unmatched:
            nearest = min(lines, key=lambda line: abs(line["cy"] - it["cy"]), default=None)
            if nearest is not None and abs(nearest["cy"] - it["cy"]) < line_h * 0.45:
                nearest["parts"].append(it)
            else:
                lines.append({"cy": it["cy"], "parts": [it], "anchor": False})
    lines.sort(key=lambda line: line["cy"])
    return [" ".join(p["text"] for p in sorted(line["parts"], key=lambda p: p["x0"])) for line in lines]


def _amount_columns(amounts: List[dict], line_h: float) -> List[List[dict]]:
    """Cluster amount boxes into columns by their right edge (amounts are right-aligned)."""
    columns: List[List[dict]] = []
    for it in sorted(amounts, key=lambda it: it["x1"]):
        if columns and abs(columns[-1][-1]["x1"] - it["x1"]) < line_h * 3:
            columns[-1].append(it)
        else:
            columns.append([it])
    return [sorted(column, key=lambda it: it["cy"]) for column in columns]


def _align_column(column: List[dict], anchors: List[dict], line_h: float) -> List[dict]:
    """
    Attach a column's amounts to dated rows, in order, allowing rows without an amount
    (e.g. "Starting Balance") and stray amounts. Returns the amounts left unattached.
    """
    a_ys = [a["cy"] for a in anchors]
    # The column's vertical offset: the shift that best lines its amounts up with the rows.
    offsets = np.arange(-1.2, 1.21, 0.05) * line_h
    offset = min(offsets, key=lambda off: sum(min(abs(it["cy"] - off - y) for y in a_ys) for it in column))
    n, m = len(anchors), len(column)
    skip_row, skip_amount, limit = line_h * 0.5, line_h * 0.9, line_h * 0.75
    cost = np.full((n + 1, m + 1), np.inf)
    move = np.zeros((n + 1, m + 1), dtype=np.int8)
    cost[0, :] = np.arange(m + 1) * skip_amount
    cost[:, 0] = np.arange(n + 1) * skip_row
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            options = [(cost[i - 1, j] + skip_row, 1), (cost[i, j - 1] + skip_amount, 2)]
            residual = abs(column[j - 1]["cy"] - offset - a_ys[i - 1])
            if residual < limit:
                options.append((cost[i - 1, j - 1] + residual, 0))
            cost[i, j], move[i, j] = min(options)
    i, j, unmatched = n, m, []
    while i > 0 or j > 0:
        step = move[i, j] if i > 0 and j > 0 else (1 if i > 0 else 2)
        if step == 0:
            anchors[i - 1]["parts"].append(column[j - 1])
            i, j = i - 1, j - 1
        elif step == 1:
            i -= 1
        else:
            unmatched.append(column[j - 1])
            j -= 1
    return unmatched


def _clean_line(line: str) -> str:
    # Non-Latin characters in an English statement are misreads of redaction marks or smudges.
    """
    Fix the misreads OCR commonly makes on statements: smudges, period thousands separators, a slash
    read as 1, S for $, and the XXXX marker drawn into redaction boxes.
    """
    line = re.sub(r"[^\x00-\u024F\u2010-\u2027█]+", " XXXX ", line)
    line = _PERIOD_THOUSANDS_RE.sub(r"\1,\2.\3", line)
    # A slash read as 1/l/I in a leading date that is followed by a clean date: "04122 04/22".
    line = re.sub(r"^(\d{2})[1lI|](\d{2})(?=\s+\d{1,2}/\d{1,2}\b)", r"\1/\2", line)
    # A dollar sign is often read as S: "S-428.13" -> "$-428.13".
    line = re.sub(r"(?<![A-Za-z])S(?=-?\d[\d,]*\.\d{2}\b)", "$", line)
    # The XXXX marker drawn into redaction boxes reads back as X/x/K runs.
    line = re.sub(r"\b[XxKk×]{3,6}\b", "XXXX", line)
    # Keep the marker a separate word when OCR glues it to its neighbours ("DraftXXXX").
    line = re.sub(r"\s*X{3,}\s*", " XXXX ", line)
    return re.sub(r"\s{2,}", " ", line).strip()


def ocr_image(image: "Image.Image") -> tuple[str, int]:
    """OCR one page image; return its text and how many redaction boxes were found."""
    masked, boxes = _mask_redaction_boxes(image)
    result = _get_engine()(np.array(masked))
    if result is None or not getattr(result, "txts", None):
        return "", boxes
    return "\n".join(_clean_line(line) for line in _boxes_to_lines(result, masked.width)), boxes


def render_page(file_bytes: bytes, page_index: int, scale: float = 2.0) -> Optional["Image.Image"]:
    """Render one PDF page to an image with pdfium (installed alongside pdfplumber)."""
    try:
        import pypdfium2 as pdfium
    except Exception:  # pragma: no cover
        return None
    pdf = pdfium.PdfDocument(file_bytes)
    try:
        return pdf[page_index].render(scale=scale).to_pil()
    finally:
        pdf.close()
