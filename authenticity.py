"""
Document checks: signs a statement PDF may have been altered.

Statements given to investigators are sometimes edited copies: transactions
deleted, payees renamed, balances retyped. Edits made with ordinary PDF tools
tend to leave the same tells, and this module looks for them:

- the PDF was made or re-saved by an editing tool, or saved long after it was created;
- a few transaction lines use a different font from the rest;
- dates outside the statement period, or out of date order;
- a description that contradicts the direction the balance moved ("payment from" as money out);
- running balances that don't follow from the line above;
- summary totals that don't agree with the transactions;
- amounts formatted differently from the rest of the statement.

None of these proves a statement is fake, and a clean result doesn't prove it is
genuine. The reliable test is a copy obtained directly from the bank.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from typing import Dict, List, Optional, Tuple

import pandas as pd
import pdfplumber

# A check's result: looks normal, worth checking, a note (for example "this is a scan"), or not checked.
OK, WARN, NOTE, SKIPPED = "ok", "warn", "note", "skipped"

# Tools people use to edit or rebuild PDFs. Banks produce statements with document-composition
# software, not these.
EDITING_TOOLS = re.compile(
    r"ilovepdf|smallpdf|sejda|pdfescape|pdffiller|dochub|pdf\s*candy|soda\s*pdf|pdfelement|wondershare|nitro|"
    r"foxit\s*phantom|phantompdf|photoshop|gimp|canva|microsoft.{0,20}word|libreoffice|openoffice|google\s*docs|"
    r"inkscape|illustrator|pdf\s*editor|pdf-xchange|able2extract|pdf2go|online2pdf|sodapdf|docfly|lightpdf",
    re.IGNORECASE,
)
# Printer drivers and scanners: a printed or scanned copy, not the bank's file (a note, not a warning).
PRINT_TOOLS = re.compile(r"print\s*to\s*pdf|quartz pdfcontext|scan|epson|canon|hp\s|xerox|ricoh|fujitsu|naps2", re.IGNORECASE)
# A date in a statement period: "April 01, 2025" or "04/01/2025".
DATE_TOKEN = re.compile(r"[A-Z][a-z]+\.? \d{1,2},? \d{4}|\d{1,2}/\d{1,2}/\d{2,4}")
# Amounts of $1,000 or more with and without a thousands comma.
WITH_COMMA = re.compile(r"(?<![\d.])\$?\d{1,3}(?:,\d{3})+\.\d{2}(?!\d)")
WITHOUT_COMMA = re.compile(r"(?<![\d,.])\$?\d{4,}\.\d{2}(?![\d])")
# Only money-in wording on money out is checked: relabelling "payment to" as "payment from" hides where money
# went, while banks word money-in lines too loosely ("transfer to savings" on the savings account) to check the reverse.
MONEY_IN_WORDS = re.compile(r"\b(?:payment|transfer|credit|deposit)\s+from\b", re.IGNORECASE)
# Lines that legitimately go against their wording (a reversed or returned payment).
REVERSAL_WORDS = re.compile(r"reversal|revers|return|refund|correction|adjust|void|cancel", re.IGNORECASE)
# The total deposits line in the statement's summary box.
SUMMARY_DEPOSITS = re.compile(
    r"^(?:total\s+)?(?:deposits|additions|deposits\s+and\s+(?:other\s+)?(?:additions|credits))\b[^\d$\n]*\$?\s?([\d,]+\.\d{2})",
    re.IGNORECASE | re.MULTILINE,
)
# A statement period written out: "April 01, 2025 through April 30, 2025".
PERIOD_TEXT = re.compile(
    r"(" + DATE_TOKEN.pattern + r")\s*(?:through|thru|to|-|–)\s*(" + DATE_TOKEN.pattern + r")", re.IGNORECASE
)
# A line that starts with a date and contains an amount: a transaction line.
TXN_LINE = re.compile(r"^\s*\*?\d{1,2}[/-]\d{1,2}\b.*\d\.\d{2}")


@dataclass
class Check:
    """The result of one document check, with up to eight example lines for the user to look at."""
    name: str
    status: str  # ok | warn | note | skipped
    detail: str
    examples: List[str] = field(default_factory=list)


def _money(value: float) -> str:
    """$1,234.56, or -$1,234.56 for a negative amount."""
    return f"-${-value:,.2f}" if value < 0 else f"${value:,.2f}"


def _pdf_date(value) -> Optional[datetime]:
    """A PDF date ('D:20250502100805+00'00'') as a datetime; None if it can't be read."""
    match = re.search(r"(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?", str(value or ""))
    if not match:
        return None
    try:
        return datetime(*(int(g) for g in match.groups(default="0")))
    except ValueError:
        return None


def _line_label(row) -> str:
    """A transaction as one readable line for the examples: date, description, signed amount and page."""
    when = row["txn_date"].strftime("%m/%d") if pd.notna(row["txn_date"]) else str(row.get("txn_date_raw") or "")
    amount = row["amount"] if pd.notna(row["amount"]) else 0.0
    return f"{when} {str(row['description'])[:60]} {_money(-amount if row['direction'] == 'debit' else amount)} (page {row['source_page']})"


def _metadata_checks(pdf) -> List[Check]:
    """
    Two checks from the PDF's own details: which software made it, and whether it was saved again long
    after it was created.
    """
    meta = {k: str(v) for k, v in (pdf.metadata or {}).items()}
    tools = " / ".join(dict.fromkeys(v for k, v in meta.items() if k in ("Creator", "Producer") and v.strip()))
    checks: List[Check] = []
    if not tools:
        checks.append(Check("Software that made the PDF", NOTE, "The PDF doesn't say what made it (that information was removed or never written)."))
    elif EDITING_TOOLS.search(tools):
        checks.append(Check(
            "Software that made the PDF", WARN,
            f"Made or last saved with {tools}, a PDF editing or office tool. Banks don't produce statements with these, "
            "so the file was rebuilt or edited after it left the bank.",
        ))
    elif PRINT_TOOLS.search(tools):
        checks.append(Check("Software that made the PDF", NOTE, f"Made with {tools}: a printed or scanned copy, not the bank's original file."))
    else:
        checks.append(Check("Software that made the PDF", OK, f"Made with {tools}; not a known editing tool."))

    created, modified = _pdf_date(meta.get("CreationDate")), _pdf_date(meta.get("ModDate"))
    if created and modified and (modified - created).days >= 1:
        checks.append(Check(
            "Saved again after it was created", WARN,
            f"Created {created:%m/%d/%Y} but saved again on {modified:%m/%d/%Y}, {(modified - created).days} days later. "
            "A bank's statement file is normally written once.",
        ))
    elif created and modified:
        checks.append(Check("Saved again after it was created", OK, f"Created and last saved on {created:%m/%d/%Y}."))
    else:
        checks.append(Check("Saved again after it was created", SKIPPED, "The PDF has no creation or modification date."))
    return checks


def _font_family(fontname: str) -> str:
    """'ABCDEF+Arial-BoldMT' -> 'Arial': bold and italic are styling, a different family is not."""
    name = re.sub(r"^[A-Z]{6}\+", "", str(fontname))
    return re.sub(r"(?:MT|PS)$", "", re.split(r"[-,]", name)[0]) or name


def _font_check(pdf) -> Check:
    """Fonts used on transaction lines; a few lines in a font the rest don't use were likely typed over."""
    lines: List[Tuple[int, str, frozenset]] = []
    for page_number, page in enumerate(pdf.pages, start=1):
        words = page.extract_words(extra_attrs=["fontname"], keep_blank_chars=False, use_text_flow=False)
        # Group words into lines by their height on the page (within 3 points).
        rows: Dict[int, List[dict]] = {}
        for word in words:
            rows.setdefault(round(word["top"] / 3), []).append(word)
        for _, row_words in sorted(rows.items()):
            row_words.sort(key=lambda w: w["x0"])
            text = " ".join(w["text"] for w in row_words)
            if TXN_LINE.match(text):
                fonts = frozenset(_font_family(w["fontname"]) for w in row_words)
                lines.append((page_number, text, fonts))
    if len(lines) < 5:
        return Check("Fonts on transaction lines", SKIPPED, "Too few transaction lines with font information to compare.")
    # A font family used on fewer than 35% of the transaction lines is "rare". If those lines are a
    # minority too, they were probably typed over the statement in an editor.
    usage = Counter(font for _, _, fonts in lines for font in fonts)
    rare = {font for font, count in usage.items() if count / len(lines) < 0.35}
    odd = [(page, text, fonts & rare) for page, text, fonts in lines if fonts & rare]
    if odd and len(odd) / len(lines) < 0.35:
        common = ", ".join(font for font, count in usage.most_common() if font not in rare)
        return Check(
            "Fonts on transaction lines", WARN,
            f"{len(odd)} of {len(lines)} transaction lines use a font ({', '.join(sorted(rare))}) that the other lines don't "
            f"(they use {common}). Text typed over a statement in an editor usually comes out in a different font.",
            [f"{text[:90]} (page {page})" for page, text, _ in odd[:8]],
        )
    return Check("Fonts on transaction lines", OK, f"All {len(lines)} transaction lines use the same fonts.")


def _date(token: str):
    """A date token as a datetime, reading 31/01/2025-style dates day first."""
    day_first = bool(re.match(r"(1[3-9]|2\d|3[01])/", token))
    return pd.to_datetime(token.replace(".", ""), errors="coerce", dayfirst=day_first)


def _period(text: str) -> Optional[Tuple[datetime, datetime]]:
    """(start, end) from text holding two dates, or None."""
    found = [_date(t) for t in DATE_TOKEN.findall(str(text or ""))]
    found = [d for d in found if pd.notna(d)]
    return (found[0], found[-1]) if len(found) >= 2 and found[-1] > found[0] else None


def _date_checks(tx: pd.DataFrame, full_text: str, is_card: bool) -> List[Check]:
    """
    Two checks: transactions dated outside their statement period, and transactions out of date order.
    Skipped for day-first dates, which the reader doesn't fully support yet.
    """
    if tx["txn_date_raw"].astype(str).str.match(r"\s*(?:1[3-9]|2\d|3[01])[/.-]\d").any():
        why = "Dates are written day first (31/01), which the reader doesn't fully support yet."
        return [Check("Dates inside the statement period", SKIPPED, why), Check("Transactions in date order", SKIPPED, why)]
    outside, backwards = [], []
    checked_period = False
    printed = PERIOD_TEXT.search(full_text)
    for (statement, account), grp in tx.groupby(["statement_id", tx["account_number"].fillna("")], sort=False):
        period = _period(grp["statement_date"].dropna().iloc[0] if grp["statement_date"].notna().any() else "")
        if period is None and printed and tx["statement_id"].nunique() == 1:
            period = _period(printed.group(0))
        if period:
            checked_period = True
            # Card transactions can be dated a few days before the period they post in.
            start, end = period[0] - pd.Timedelta(days=7 if is_card else 3), period[1] + pd.Timedelta(days=1)
            for _, row in grp.iterrows():
                if pd.notna(row["txn_date"]) and not (start <= row["txn_date"] <= end):
                    outside.append(_line_label(row))
        if is_card:
            continue  # card statements group lines by type (purchases, cash advances, fees), not by date
        for _, section in grp.groupby(grp["section"].fillna("all"), sort=False):
            if (section["section"] == "checks").any():
                continue  # checks are often listed by number, not date
            ordered = section[section["transaction_type"] != "check"].dropna(subset=["txn_date"]).sort_values(["source_page", "source_line"])
            backwards.extend(_out_of_order(ordered))
    checks = []
    if not checked_period:
        checks.append(Check("Dates inside the statement period", SKIPPED, "No statement period was found to compare against."))
    elif outside:
        checks.append(Check(
            "Dates inside the statement period", WARN,
            f"{len(outside)} transaction{'s are' if len(outside) != 1 else ' is'} dated outside the statement period. "
            "A line pasted in from another month is a common edit.", outside[:8],
        ))
    else:
        checks.append(Check("Dates inside the statement period", OK, "Every transaction falls inside its statement period."))
    if backwards:
        checks.append(Check(
            "Transactions in date order", WARN,
            f"{len(backwards)} line{'s are' if len(backwards) != 1 else ' is'} out of date order. Banks print transactions in "
            "date order; a line out of place may have been moved or added by hand.", backwards[:8],
        ))
    else:
        checks.append(Check("Transactions in date order", OK, "Transactions run in date order within each section."))
    return checks


def _out_of_order(ordered: pd.DataFrame) -> List[str]:
    """Lines that break the date order, naming the line most likely moved or added."""
    if len(ordered) < 3:
        return []
    dates = [d.normalize() for d in ordered["txn_date"]]
    rows = [r for _, r in ordered.iterrows()]
    if sum(b < a for a, b in zip(dates, dates[1:])) > sum(b > a for a, b in zip(dates, dates[1:])):
        dates, rows = dates[::-1], rows[::-1]  # printed newest first
    day = pd.Timedelta(days=1)
    found: List[str] = []
    blamed = set()
    # A step back of more than a day breaks the order. Blame the line that jumped ahead (later than the
    # lines on both sides) or, otherwise, the one that fell back; one break isn't counted twice.
    for i in range(1, len(dates)):
        if dates[i] >= dates[i - 1] - day or i - 1 in blamed:
            continue
        # The line above jumped ahead (it is later than the lines on both sides), or this one fell back.
        ahead = dates[i + 1] < dates[i - 1] - day if i + 1 < len(dates) else (i >= 2 and dates[i - 2] <= dates[i] + day)
        if ahead:
            blamed.add(i - 1)
            found.append(f"{_line_label(rows[i - 1])}, listed before {dates[i]:%m/%d}")
        else:
            blamed.add(i)
            found.append(f"{_line_label(rows[i])}, listed after {dates[i - 1]:%m/%d}")
    return found


def _direction_check(tx: pd.DataFrame, is_card: bool) -> Check:
    """
    Lines that say money came in ("payment from") although the running balance went down: a relabelled
    payment. Only lines confirmed by a printed balance are judged.
    """
    if is_card:
        return Check("Descriptions match money in and out", SKIPPED, "Not checked on credit card statements.")
    checked = tx[tx["balance_check"] == "ok"]
    if checked.empty:
        return Check("Descriptions match money in and out", SKIPPED, "No running balances to confirm which way money moved.")
    desc = checked["description"].fillna("").astype(str)
    plain = ~desc.str.contains(REVERSAL_WORDS)
    wrong = checked[plain & (checked["direction"] == "debit") & desc.str.contains(MONEY_IN_WORDS)]
    if wrong.empty:
        return Check("Descriptions match money in and out", OK, f"All {len(checked)} balance-checked lines move money the way their descriptions say.")
    return Check(
        "Descriptions match money in and out", WARN,
        f"{len(wrong)} line{'s say' if len(wrong) != 1 else ' says'} money came in (\"payment from\") but the running "
        "balance went down. Relabelling a payment is a common way to disguise where money went.",
        [_line_label(r) for _, r in wrong.head(8).iterrows()],
    )


def _balance_check(tx: pd.DataFrame, scanned: bool) -> Check:
    """
    Printed running balances that no reading of the amounts explains. A warning on a text PDF; only a
    note on a scan, where a misread digit is possible.
    """
    tested = tx[tx["balance_check"].isin(["ok", "break"])]
    if tested.empty:
        return Check("Running balances add up", SKIPPED, "The statement has no running balance column.")
    breaks = tx[tx["balance_check"] == "break"]
    if breaks.empty:
        return Check("Running balances add up", OK, f"All {len(tested)} printed balances follow from the line before.")
    why = ("On a scanned copy this can also be a misread digit; compare with the page image." if scanned else
           "On a statement straight from the bank every balance follows from the one before it; a break means an amount "
           "or balance was changed, or a line was removed or added.")
    return Check(
        "Running balances add up", NOTE if scanned else WARN,
        f"{len(breaks)} printed balance{'s don' if len(breaks) != 1 else ' doesn'}'t follow from the line above. {why}",
        [_line_label(r) for _, r in breaks.head(8).iterrows()],
    )


def _summary_check(tx: pd.DataFrame, full_text: str, is_card: bool) -> Check:
    """
    The statement's summary against its transactions: total deposits, and opening balance plus
    transactions against the printed ending balance.
    """
    name = "Summary agrees with the transactions"
    if tx["statement_id"].nunique() != 1 or tx["account_number"].fillna("").nunique() != 1:
        return Check(name, SKIPPED, "Checked only on single-account, single-month statements (the Bank Reconciliation tab covers the rest).")
    if tx["amount"].isna().any():
        return Check(name, SKIPPED, "Some amounts are redacted, so the totals can't be compared.")
    credits = float(tx["credit"].fillna(0).sum())
    debits = float(tx["debit"].fillna(0).sum())
    problems: List[str] = []
    compared = 0
    header = full_text.split("\n")
    # The summary box is above the first transaction line.
    header_text = "\n".join(header[: next((i for i, ln in enumerate(header) if TXN_LINE.match(ln)), len(header))])
    if not is_card:
        match = SUMMARY_DEPOSITS.search(header_text)
        if match:
            compared += 1
            printed = float(match.group(1).replace(",", ""))
            if abs(printed - credits) > 0.01:
                problems.append(f"The summary shows deposits of {_money(printed)}, but the deposits listed add up to {_money(credits)} "
                                f"(a difference of {_money(printed - credits)}).")
    opening, closing = tx["statement_opening_balance"].iloc[0], tx["statement_closing_balance"].iloc[0]
    # The same figure for both usually means the summary wasn't read, not that it is wrong.
    if pd.notna(opening) and pd.notna(closing) and opening != closing:
        compared += 1
        # A card balance rises with charges; a bank balance rises with deposits.
        expected = opening + debits - credits if is_card else opening + credits - debits
        if abs(expected - closing) > 0.01:
            problems.append(f"Opening balance {_money(opening)} plus the transactions comes to {_money(expected)}, but the ending "
                            f"balance printed is {_money(closing)}.")
    if not compared:
        return Check(name, SKIPPED, "No summary totals were found to compare.")
    if problems:
        return Check(name, WARN, " ".join(problems) + " Summary figures that don't match the detail are a sign one was edited without the other.")
    return Check(name, OK, "The summary totals agree with the transactions listed.")


def _format_check(full_text: str, scanned: bool) -> Check:
    """Amounts of $1,000 or more printed without a thousands comma where the rest of the statement uses one."""
    with_comma = WITH_COMMA.findall(full_text)
    without = WITHOUT_COMMA.findall(full_text)
    if len(with_comma) >= 3 and without and len(without) < len(with_comma):
        detail = (f"{len(without)} amount{'s' if len(without) != 1 else ''} over $1,000 printed without a comma "
                  f"({', '.join(without[:5])}) where the other {len(with_comma)} have one. A figure typed in by hand often doesn't match "
                  "the statement's own formatting.")
        if scanned:
            return Check("Amounts formatted consistently", NOTE, detail + " On a scan, OCR can also drop a comma.")
        return Check("Amounts formatted consistently", WARN, detail)
    return Check("Amounts formatted consistently", OK, "Amounts are formatted the same way throughout.")


def check_document(file_bytes: bytes, transactions: pd.DataFrame, full_text: str, scanned_pages: int = 0) -> List[Check]:
    """Run every check on one statement PDF and the transactions read from it."""
    checks: List[Check] = []
    scanned = scanned_pages > 0
    try:
        with pdfplumber.open(BytesIO(file_bytes)) as pdf:
            checks.extend(_metadata_checks(pdf))
            if scanned:
                checks.append(Check(
                    "Fonts on transaction lines", NOTE,
                    "This is a scanned copy (a picture of the pages), so fonts and other details of the original file can't be "
                    "checked. Ask for the statement directly from the bank if its authenticity matters.",
                ))
            else:
                checks.append(_font_check(pdf))
    except Exception:  # an unreadable or encrypted file still gets the checks below
        checks.append(Check("Software that made the PDF", SKIPPED, "The PDF's details couldn't be read."))
    if transactions.empty:
        return checks
    tx = transactions.copy()
    for column in ("section", "balance_check"):
        if column not in tx:
            tx[column] = None
    is_card = (tx["statement_kind"] == "credit_card").any()
    checks.extend(_date_checks(tx, full_text, is_card))
    checks.append(_direction_check(tx, is_card))
    checks.append(_balance_check(tx, scanned))
    checks.append(_summary_check(tx, full_text, is_card))
    checks.append(_format_check(full_text, scanned))
    return checks


def verdict(checks: List[Check]) -> Tuple[str, str]:
    """(level, headline) for a file: level is "clean", "review" or "altered"."""
    warnings = sum(c.status == WARN for c in checks)
    scanned = any(c.status == NOTE and "scanned copy" in c.detail for c in checks)
    if warnings >= 3:
        return "altered", f"{warnings} signs this copy may have been altered"
    if warnings:
        return "review", f"{warnings} sign{'s' if warnings != 1 else ''} worth checking"
    return "clean", "No signs of editing found" + (" (a scan allows fewer checks)" if scanned else "")


def checks_frame(file_name: str, checks: List[Check]) -> pd.DataFrame:
    """Rows for the workpaper and the app's table."""
    labels = {OK: "Looks normal", WARN: "Worth checking", NOTE: "Note", SKIPPED: "Not checked"}
    return pd.DataFrame(
        [
            {"file": file_name, "check": c.name, "result": labels[c.status], "detail": c.detail, "examples": "\n".join(c.examples)}
            for c in checks
        ],
        columns=["file", "check", "result", "detail", "examples"],
    )
