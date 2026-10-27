"""
Format-agnostic statement reader.

Reads a text-based bank statement PDF without a hand-built template. It looks
for lines that look like transactions (a date plus a dollar amount) and works
out debit vs. credit from, in priority order:

1. the running balance column (did the balance go up or down?),
2. an explicit sign on the amount (-, parentheses, DR/CR),
3. the section heading the line sits under ("Deposits", "Checks Paid", ...),
4. keywords in the description.

It also suggests a template (bank name + detection keywords) so a user can
save a new format with one click.

Credit card statements are detected and read with card conventions (charges
are debits; payments, credits and negative amounts reduce the balance).
Redacted text ("[REDACTED]", "XXXX", "█") is kept as "[redacted]"; when an
amount is redacted but the running balance is not, the amount is recovered
from the change in balance.
"""

from __future__ import annotations

from collections import Counter
from itertools import combinations
from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Dict, List, Optional, Tuple

from bank_directory import recognize_bank

MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_ALT = "jan|feb|mar|apr|may|jun|jul|aug|sept|sep|oct|nov|dec"

# One date token: 07/01/2019, 7/1/19, 07/01, 05-15, 05-15-2003, Jan 5, Jan 05, 2024.
DATE = (
    r"(?:(?<![\d/\-])\d{1,2}/\d{1,2}(?:/\d{2,4})?(?![\d/])"
    r"|(?<![\d/\-])\d{1,2}-\d{1,2}(?:-\d{2,4})?(?![\d\-])"
    rf"|\b(?:{_MONTH_ALT})[a-z]*\.?\s+\d{{1,2}}(?:,?\s+\d{{4}})?\b)"
)
# One money amount with optional sign markers: -1,234.56  (45.00)  $45.00  45.00-  45.00 CR
AMOUNT = (
    r"(?<![\w.,/])(?P<neg>-\s?|\()?\$?\s?(?P<num>\d{1,3}(?:,\d{3})+|\d+)\.(?P<cents>\d{2})"
    r"(?P<close>\))?(?P<suffix>-|\s?(?:CR|DR|Cr|Dr)\b)?(?![\d%])"
)

DATE_RE = re.compile(DATE, re.IGNORECASE)
AMOUNT_RE = re.compile(AMOUNT)
# A trailing * on a date (Amex marks some lines that way) is part of the date column.
LEADING_DATE_RE = re.compile(rf"^(?P<d1>{DATE})\*?(?:\s+(?P<d2>{DATE})\*?)?(?=\s|$)", re.IGNORECASE)
# "June 1, 2025 - June 30, 2025", "Feb 05, 2025 - Mar 06, 2025 | 30 days": a statement period, not a transaction.
DATE_RANGE_RE = re.compile(rf"^(?:[A-Za-z ]{{0,30}}:?\s*)?{DATE}\s*(?:-|–|to|through|thru)\s*{DATE}", re.IGNORECASE)
# Description first, then the date(s), then only amounts to the end of the line.
TRAILING_DATE_RE = re.compile(
    rf"^(?P<desc>.*?\S)\s+(?P<d1>{DATE})(?:\s+(?P<d2>{DATE}))?\s+(?P<amts>[-($\d][\d,.\s$()\-CRDcrd]*)$",
    re.IGNORECASE,
)
CHECK_NUM_FIRST_RE = re.compile(rf"(?P<num>\d{{3,7}})\*?\s+(?P<date>{DATE})\s+(?P<amt>\$?\d[\d,]*\.\d{{2}})", re.IGNORECASE)
CHECK_DATE_FIRST_RE = re.compile(rf"(?P<date>{DATE})\s+(?P<num>\d{{3,7}})\*?\s+(?P<amt>\$?\d[\d,]*\.\d{{2}})", re.IGNORECASE)
DATE_AMOUNT_PAIR_RE = re.compile(rf"{DATE}\s+\$?\d[\d,]*\.\d{{2}}", re.IGNORECASE)
MASK_CHARS = "Xx*•█"
ACCOUNT_RE = re.compile(
    rf"(?:account|card)\s*(?:number|no\.?|#)\s*:?\s*([0-9{MASK_CHARS}][0-9{MASK_CHARS}\- ]{{2,}}[0-9{MASK_CHARS}])"
    r"|(?:(?:account|card)\s+ending\s+(?:in\s+)?|\bending\s+in\s+)(\d[\d-]{3,})\b",
    re.IGNORECASE,
)
# "[REDACTED]", "REDACTED", runs of block characters, or 4+ X / * / • used to blank out text.
REDACTION_RE = re.compile(r"\[\s*redacted\s*\]|\bredacted\b|(?:[█■▇]+\s*)+|\bX{4,}\b|\*{4,}|•{4,}", re.IGNORECASE)
# "Statement Date: 03/01/2008 through 03/31/2008", "Statement period 06/28/24 - 07/29/24".
PERIOD_RE = re.compile(
    r"(?:statement|period)[^\n]*?(\d{1,2}/\d{1,2}/\d{2,4})\s*(?:through|thru|to|-|–)\s*(\d{1,2}/\d{1,2}/\d{2,4})",
    re.IGNORECASE,
)
# A heading that starts one account within a statement: "ID : 10 POWER CHECKING", "00 SHARE SAVINGS".
ACCOUNT_SECTION_RE = re.compile(r"^(?:[A-Za-z█\[\]]{0,10}\s*:\s*)?(?:\d{1,4}\s+)?((?:[A-Z]+\s+){0,3}(?:CHECKING|SAVINGS|MONEY MARKET))$")
# Printed control totals: "10 Total Deposits : $8,337.98", "43 Total XXXX : $-8,754.29", "Total Checks Paid $305.00".
CONTROL_TOTAL_RE = re.compile(r"^(?:(?P<count>\d{1,4})\s+)?total\b(?P<label>.*?)[:\s]\s*(?P<amount>-?\s?\$?\s?-?[\d,]+\.\d{2})\s*$", re.IGNORECASE)
CONTROL_TOTAL_SKIP_RE = re.compile(r"interest|year|ytd|today|period|in (?:19|20)\d\d", re.IGNORECASE)
CHECK_PAIR_RE = re.compile(
    rf"(?P<date>{DATE})\s+(?:(?P<num>\d{{3,7}})\*?\s+|(?:XXXX|\[redacted\]|█+)\s+)?(?P<amt>\$?\d[\d,]*\.\d{{2}})",
    re.IGNORECASE,
)
CARD_MARKERS = ("minimum payment due", "credit card", "card ending", "cash advance", "new balance", "credit limit")
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
PAGE_FOOTER_RE = re.compile(r"^page\s*\d+\s*(of\s*\d+)?$", re.IGNORECASE)

OPENING_BALANCE_RE = re.compile(
    r"(previous|beginning|opening|starting|prior)\s+balance|balance\s+(forward|brought forward|last statement)",
    re.IGNORECASE,
)
CLOSING_BALANCE_RE = re.compile(r"(ending|closing|new)\s+balance", re.IGNORECASE)
CREDIT_SECTION_RE = re.compile(r"deposits|credits|additions|interest paid", re.IGNORECASE)
DEBIT_SECTION_RE = re.compile(
    r"withdrawals|debits|subtractions|purchases|payments|fees|charges|check card|interest charged", re.IGNORECASE
)
CARD_CREDIT_SECTION_RE = re.compile(r"payments|credits|refunds|returns", re.IGNORECASE)
CARD_DEBIT_SECTION_RE = re.compile(
    r"purchases|fees|interest charged|cash advances?|balance transfers?|charges", re.IGNORECASE
)
CARD_CREDIT_WORDS = ("payment", "credit", "refund", "return", "reversal")
CHECK_SECTION_RE = re.compile(r"checks(?!\s*card)|checkspaid", re.IGNORECASE)
SKIP_SECTION_RE = re.compile(
    r"daily\s+(ending\s+)?balance|balance\s+summary|ledger\s+balance|interest\s+charge\s+calculation|year[-\s]to[-\s]date|\bytd\b",
    re.IGNORECASE,
)
COLUMN_HEADER_RE = re.compile(r"\bdate\b.*\b(description|amount|balance|debits?|credits?|withdrawals?|deposits?)\b", re.IGNORECASE)

CREDIT_WORDS = (
    "deposit", "credit", "refund", "reversal", "interest paid", "interest earned", "transfer from",
    "payroll", "direct dep", "received", "rebate", "cash back",
)
DEBIT_WORDS = (
    "withdrawal", "debit", "purchase", "payment", "fee", "charge", "check", "transfer to", "pos ", "atm",
)

BANK_NAME_RE = re.compile(
    r"\b([A-Z][A-Za-z&.'\-]*(?:\s+[A-Z][A-Za-z&.'\-]*){0,4}\s+"
    r"(?:Bank|Bancorp|Credit Union|Savings Bank|Trust Company|Trust|Financial|Federal Credit Union|N\.A\.))\b"
)
WEBSITE_RE = re.compile(r"\b(?:www\.)?([a-z0-9\-]+\.(?:com|org|net|bank|us))\b", re.IGNORECASE)
PRODUCT_RE = re.compile(r"^([A-Z][A-Z &'\-]{2,40}\b(?:CHECKING|SAVINGS|MONEY MARKET|ACCOUNT))\b")


@dataclass
class _Candidate:
    page: int
    line_no: int
    date_raw: str
    description: str
    amounts: List[Tuple[float, int]]  # (value, sign hint: -1 debit, +1 credit, 0 none)
    section: str
    account: Optional[str]
    is_check: bool = False
    check_number: Optional[str] = None
    redacted: bool = False
    period: Optional[Tuple[str, str]] = None  # (start, end) of the statement this line belongs to
    control: Optional[Tuple[str, float, Optional[int]]] = None  # printed total: (direction, amount, count)


@dataclass
class AutoParseOutput:
    rows: List[Dict]
    has_balance_column: bool
    balance_rows: int
    balance_verified_rows: int
    bank_name: Optional[str]
    detection_keywords: List[str] = field(default_factory=list)
    statement_kind: str = "bank"
    redacted_rows: int = 0
    recovered_amounts: int = 0

    @property
    def confidence(self) -> str:
        """Plain-English confidence rating used by the UI."""
        if not self.rows:
            return "none"
        if self.balance_rows and self.balance_verified_rows / self.balance_rows >= 0.95:
            return "high"
        if self.balance_rows and self.balance_verified_rows / self.balance_rows >= 0.75:
            return "medium"
        if not self.has_balance_column and len(self.rows) >= 3:
            return "medium"
        return "low"


# Sign hints: 1 = CR (money in), -1 = printed negative, DEBIT_MARK = DR (money out).
DEBIT_MARK = -2


def _parse_amount(match: re.Match) -> Tuple[float, int]:
    value = float(f"{match.group('num').replace(',', '')}.{match.group('cents')}")
    sign = 0
    suffix = (match.group("suffix") or "").strip().upper()
    if suffix == "DR":
        sign = DEBIT_MARK  # explicitly money out, even on a card statement
    elif match.group("neg") or match.group("close") or suffix == "-":
        sign = -1
    elif suffix == "CR":
        sign = 1
    return value, sign


def _strip_amounts_and_dates(text: str) -> str:
    text = AMOUNT_RE.sub(" ", text)
    text = DATE_RE.sub(" ", text)
    text = REDACTION_RE.sub(" [redacted] ", text)
    text = re.sub(r"(?:\[redacted\]\s*)+", "[redacted] ", text)
    return re.sub(r"\s+", " ", text).strip(" -*=:")


def detect_statement_kind(full_text: str) -> str:
    """'credit_card' or 'bank', from wording on the first pages."""
    head = "\n".join(full_text.splitlines()[:80]).lower()
    if re.search(r"\bchecking\b", head) and "credit card" not in head:
        return "bank"
    bank = recognize_bank(full_text)
    if bank and bank["kind"] == "card_issuer":
        return "credit_card"
    return "credit_card" if sum(marker in head for marker in CARD_MARKERS) >= 2 else "bank"


def normalize_account(match: re.Match) -> Optional[str]:
    """Account number from an ACCOUNT_RE match; masked numbers become ****1234."""
    if match.group(2):
        return f"****{re.sub(r'\D', '', match.group(2))[-4:]}"
    raw = match.group(1).strip()
    if any(ch in raw for ch in MASK_CHARS):
        digits = re.sub(r"\D", "", raw)
        return f"****{digits[-4:]}" if digits else None  # fully redacted: no usable number
    tokens = raw.split()
    if len(tokens) > 1 and all(re.fullmatch(r"\d{3,5}", token) for token in tokens):
        return "".join(tokens)  # printed in groups: "0000 1111 2222"
    return tokens[0]


def summary_balances(full_text: str) -> Tuple[Optional[float], Optional[float]]:
    """Opening and closing balance from the statement's summary lines (previous/new, beginning/ending)."""
    opening: Optional[float] = None
    closing: Optional[float] = None
    for line in full_text.splitlines():
        for pattern, is_opening in ((OPENING_BALANCE_RE, True), (CLOSING_BALANCE_RE, False)):
            if (opening if is_opening else closing) is not None:
                continue
            found = pattern.search(line)
            amount = AMOUNT_RE.search(line, found.end()) if found else None
            if amount:
                value, sign = _parse_amount(amount)
                value = -value if sign < 0 else value
                if is_opening:
                    opening = value
                else:
                    closing = value
    return opening, closing


def _section_for_header(line: str, is_card: bool = False) -> Optional[str]:
    """Return the section a heading line starts, or None when the line is not a heading."""
    if AMOUNT_RE.search(line) or len(line.split()) > 9:
        return None
    if SKIP_SECTION_RE.search(line):
        return "skip"
    if is_card:
        # On a card, payments and credits lower the balance; purchases, fees and interest raise it.
        if CARD_CREDIT_SECTION_RE.search(line):
            return "credit"
        if CARD_DEBIT_SECTION_RE.search(line):
            return "debit"
    if CHECK_SECTION_RE.search(line):
        return "checks"
    is_credit = bool(CREDIT_SECTION_RE.search(line))
    is_debit = bool(DEBIT_SECTION_RE.search(line))
    if is_credit and not is_debit:
        return "credit"
    if is_debit and not is_credit:
        return "debit"
    if re.search(r"\btransactions?\b|\bactivity\b", line, re.IGNORECASE):
        return "all"
    return None


def _infer_year(full_text: str) -> int:
    years = [int(y) for y in YEAR_RE.findall(full_text)]
    if not years:
        return datetime.now().year
    return Counter(years).most_common(1)[0][0]


def _to_date(raw: str, base_year: int, wraps_year: bool) -> Optional[datetime]:
    raw = raw.strip()
    month_match = re.match(rf"({_MONTH_ALT})[a-z]*\.?\s+(\d{{1,2}})(?:,?\s+(\d{{4}}))?", raw, re.IGNORECASE)
    if month_match:
        month = MONTH_NAMES[month_match.group(1).lower()]
        day = int(month_match.group(2))
        year = int(month_match.group(3)) if month_match.group(3) else None
    else:
        parts = re.split(r"[/\-]", raw)
        if len(parts) < 2:
            return None
        month, day = int(parts[0]), int(parts[1])
        year = None
        if len(parts) == 3:
            year = int(parts[2])
            if year < 100:
                year += 2000 if year < 70 else 1900
    if year is None:
        year = base_year - 1 if (wraps_year and month >= 11) else base_year
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def suggest_bank_name(full_text: str) -> Optional[str]:
    """The bank's name: from the built-in directory if it's a known institution, else a guess from the header."""
    known = recognize_bank(full_text)
    if known:
        return known["name"]
    head_lines = [ln.strip() for ln in full_text.splitlines()[:40] if ln.strip()]
    for line in head_lines:
        match = BANK_NAME_RE.search(line)
        if match and "statement" not in match.group(1).lower():
            return match.group(1).strip()
    for line in head_lines:
        match = WEBSITE_RE.search(line)
        if match and "www." in line.lower():
            return match.group(1).lower()
    for line in head_lines:
        match = PRODUCT_RE.match(line)
        if match:
            return match.group(1).title()
    return None


def suggest_detection_keywords(full_text: str, bank_name: Optional[str]) -> List[str]:
    """Keywords that identify this bank's layout but not this customer (no names, numbers or dates)."""
    lowered = full_text.lower()
    keywords: List[str] = []
    if bank_name and bank_name.lower() in lowered:
        keywords.append(bank_name.lower())
    head = "\n".join(full_text.splitlines()[:60])
    for line in head.splitlines():
        match = PRODUCT_RE.match(line.strip())
        if match and match.group(1).lower() not in keywords:
            keywords.append(match.group(1).lower())
            break
    if not keywords:
        site = WEBSITE_RE.search(head)
        if site:
            keywords.append(site.group(1).lower())
    return keywords[:2]


def _collect_candidates(pages: List[str], is_card: bool = False) -> List[_Candidate]:
    candidates: List[_Candidate] = []
    section = "all"
    orphan_lines: List[str] = []  # Description text seen before its dated line (multi-line layouts).
    last_was_txn = False
    pending: Optional[_Candidate] = None  # Dated line whose amount is on a later line.
    period: Optional[Tuple[str, str]] = None
    account_number: Optional[str] = None
    sub_account: Optional[str] = None
    continued = 0  # follow-on description lines added to the last transaction

    def add(cand: _Candidate) -> None:
        cand.period = period
        if account_number and sub_account:
            cand.account = f"{account_number} · {sub_account}"
        else:
            cand.account = sub_account or account_number
        candidates.append(cand)

    for page_number, page_text in enumerate(pages, start=1):
        lines = [re.sub(r"\s+", " ", ln).strip() for ln in page_text.splitlines()]
        last_was_txn = False
        orphan_lines.clear()
        for line_number, line in enumerate(lines, start=1):
            if not line or PAGE_FOOTER_RE.search(line):
                continue
            account_match = ACCOUNT_RE.search(line)
            if account_match:
                found = normalize_account(account_match)
                if found != account_number:
                    sub_account = None
                account_number = found
            period_match = PERIOD_RE.search(line)
            if period_match:
                if period and period_match.groups() != period:
                    sub_account = None
                period = period_match.groups()
            section_match = ACCOUNT_SECTION_RE.match(line)
            if section_match and not AMOUNT_RE.search(line):
                sub_account = section_match.group(1).title()
                section = "all"
                orphan_lines.clear()
                pending = None
                last_was_txn = False
                continue

            header_section = _section_for_header(line, is_card)
            if header_section:
                section = header_section
                orphan_lines.clear()
                pending = None
                last_was_txn = False
                continue
            if COLUMN_HEADER_RE.search(line) and not AMOUNT_RE.search(line):
                orphan_lines.clear()
                last_was_txn = False
                continue

            lower = line.lower()
            amount_matches = list(AMOUNT_RE.finditer(line))
            control = CONTROL_TOTAL_RE.match(line)
            if control and section != "skip" and not CONTROL_TOTAL_SKIP_RE.search(control.group("label")):
                value, sign = _parse_amount(AMOUNT_RE.search(control.group("amount")) or amount_matches[-1])
                if "-" in control.group("amount"):
                    sign = -1
                label_text = control.group("label")
                if CREDIT_SECTION_RE.search(label_text) and not DEBIT_SECTION_RE.search(label_text):
                    direction = "credit"
                elif DEBIT_SECTION_RE.search(label_text) or CHECK_SECTION_RE.search(label_text) or sign < 0:
                    direction = "debit"
                else:
                    direction = None
                if direction:
                    if is_card and re.search(r"payments|credits", label_text, re.IGNORECASE):
                        direction = "credit"
                    count = int(control.group("count")) if control.group("count") else None
                    add(_Candidate(page_number, line_number, "", "__control__", [], section, None, control=(direction, value, count)))
                last_was_txn = False
                continue
            if section == "skip" or lower.startswith(("total", "subtotal")):
                last_was_txn = False
                continue
            if OPENING_BALANCE_RE.search(line) or CLOSING_BALANCE_RE.search(line):
                if amount_matches and LEADING_DATE_RE.match(line):
                    value, sign = _parse_amount(amount_matches[-1])
                    add(_Candidate(page_number, line_number, "", "__balance__", [(value, sign)], section, None))
                last_was_txn = False
                continue

            # Grid of checks: "4416 07/08/19 $100.00 4419* 07/08/19 $266.00" or "05-12 1001 75.00 0001257".
            check_hits = list(CHECK_NUM_FIRST_RE.finditer(line))
            if not check_hits and section == "checks":
                check_hits = list(CHECK_DATE_FIRST_RE.finditer(line))
            if not check_hits and section == "checks":
                # Check summary with the check numbers blacked out: "03/03/2008 XXXX 531.42 03/17/2008 657.00".
                check_hits = list(CHECK_PAIR_RE.finditer(line))
            if check_hits and (section == "checks" or len(check_hits) >= 2):
                for hit in check_hits:
                    value = float(hit.group("amt").replace("$", "").replace(",", ""))
                    number = hit.group("num")
                    add(
                        _Candidate(
                            page_number, line_number, hit.group("date"), f"Check #{number}" if number else "Check (number redacted)",
                            [(value, -1)], "checks", None, is_check=True, check_number=number, redacted=not number,
                        )
                    )
                last_was_txn = False
                continue

            if DATE_RANGE_RE.match(line) and not AMOUNT_RE.search(line):
                pending = None
                last_was_txn = False
                continue

            # Daily balance grids: "07/01/2019 $2,860.22 07/15/2019 $11,373.85".
            if len(DATE_AMOUNT_PAIR_RE.findall(line)) >= 2 and not _strip_amounts_and_dates(line):
                last_was_txn = False
                continue

            leading = LEADING_DATE_RE.match(line)
            if leading:
                rest = line[leading.end():]
                rest_amounts = list(AMOUNT_RE.finditer(rest))
                description = _strip_amounts_and_dates(rest)
                redacted = bool(REDACTION_RE.search(rest))
                if not rest_amounts and redacted:
                    # Amount (and balance) blacked out: keep the row so the gap is visible.
                    add(_Candidate(page_number, line_number, leading.group("d1"), description, [], section, None, redacted=True))
                    orphan_lines.clear()
                    pending = None
                    last_was_txn, continued = True, 0
                    continue
                if not rest_amounts:
                    pending = _Candidate(page_number, line_number, leading.group("d1"), description, [], section, None)
                    last_was_txn = False
                    continue
                if not description and orphan_lines:
                    description = " ".join(orphan_lines)
                add(
                    _Candidate(
                        page_number, line_number, leading.group("d1"), description,
                        [_parse_amount(m) for m in rest_amounts], section, None, redacted=redacted,
                    )
                )
                orphan_lines.clear()
                pending = None
                last_was_txn, continued = True, 0
                continue

            trailing = TRAILING_DATE_RE.match(line)
            if trailing and AMOUNT_RE.search(trailing.group("amts")):
                tail_amounts = list(AMOUNT_RE.finditer(trailing.group("amts")))
                description = " ".join(orphan_lines + [trailing.group("desc")]).strip()
                add(
                    _Candidate(
                        page_number, line_number, trailing.group("d1"), _strip_amounts_and_dates(description),
                        [_parse_amount(m) for m in tail_amounts], section, None,
                        redacted=bool(REDACTION_RE.search(description)),
                    )
                )
                orphan_lines.clear()
                pending = None
                last_was_txn, continued = True, 0
                continue

            if pending is not None:
                if amount_matches:
                    pending.amounts = [_parse_amount(m) for m in amount_matches]
                    extra = _strip_amounts_and_dates(line)
                    if extra:
                        pending.description = f"{pending.description} {extra}".strip()
                    add(pending)
                    pending = None
                    last_was_txn, continued = True, 0
                elif len(pending.description) < 200:
                    pending.description = f"{pending.description} {line}".strip()
                continue

            if amount_matches:
                last_was_txn = False
                orphan_lines.clear()
                continue

            # Text-only line: continues the previous transaction (up to three lines), or precedes the next one.
            if last_was_txn and candidates and len(line) <= 140 and continued < 3:
                candidates[-1].description = f"{candidates[-1].description} {_strip_amounts_and_dates(line) or line}".strip()
                candidates[-1].redacted = candidates[-1].redacted or bool(REDACTION_RE.search(line))
                continued += 1
            else:
                last_was_txn = False
                orphan_lines.append(line)
                orphan_lines = orphan_lines[-3:]

    return _drop_duplicate_checks(candidates)


NOT_A_CHECK_RE = re.compile(r"\bpos\b|debit card|deposit|transfer|\batm\b|\bfee\b|withdrawal|purchase|ach\b", re.IGNORECASE)


def _day_number(raw: str) -> Optional[int]:
    """Rough day-of-year from a date token, for "within a few days" comparisons."""
    parts = re.findall(r"\d+", raw)
    if len(parts) >= 2 and not re.match(r"[A-Za-z]", raw):
        return int(parts[0]) * 31 + int(parts[1])
    month = re.match(rf"({_MONTH_ALT})", raw, re.IGNORECASE)
    if month and parts:
        return MONTH_NAMES[month.group(1).lower()] * 31 + int(parts[0])
    return None


def _drop_duplicate_checks(candidates: List[_Candidate]) -> List[_Candidate]:
    """
    Many banks list each check in the register and again in a check summary; keep it once.
    Matched by check number, or, when numbers are redacted, by the same amount within ten days
    on a register line that isn't clearly something else (card purchase, ATM, deposit...).
    """
    register = [c for c in candidates if not c.is_check and c.description not in ("__balance__", "__control__")]
    used: set = set()
    kept: List[_Candidate] = []
    for cand in candidates:
        if cand.is_check:
            amount = cand.amounts[0][0]
            match = None
            for i, reg in enumerate(register):
                if i in used or reg.period != cand.period or not any(abs(v - amount) < 0.005 for v, _ in reg.amounts[:1]):
                    continue
                if cand.check_number and re.search(rf"\b{re.escape(cand.check_number)}\b", reg.description):
                    match = i
                    break
                if not cand.check_number and not NOT_A_CHECK_RE.search(reg.description):
                    a, b = _day_number(cand.date_raw), _day_number(reg.date_raw)
                    if a is not None and b is not None and abs(a - b) <= 10:
                        match = i
                        break
            if match is not None:
                used.add(match)
                continue
        kept.append(cand)
    return kept


def _keyword_direction(description: str, credit_keywords: List[str], is_card: bool = False) -> Optional[str]:
    text = description.lower()
    if is_card:
        return "credit" if any(word in text for word in CARD_CREDIT_WORDS) else "debit"
    if any(word in text for word in credit_keywords):
        return "credit"
    if any(word in text for word in DEBIT_WORDS):
        return "debit"
    return None


def auto_parse(
    pages: List[str],
    statement_id: str,
    account_number: Optional[str],
    statement_date: Optional[str],
    bank_format: Optional[str] = None,
    default_direction: str = "debit",
    credit_keywords: Optional[List[str]] = None,
) -> AutoParseOutput:
    """Parse statement pages into transaction rows without a layout-specific parser."""
    full_text = "\n".join(pages)
    bank_name = suggest_bank_name(full_text)
    credit_words = list(credit_keywords) if credit_keywords else list(CREDIT_WORDS)
    is_card = detect_statement_kind(full_text) == "credit_card"
    candidates = _collect_candidates(pages, is_card)

    controls = [c for c in candidates if c.description == "__control__"]
    candidates = [c for c in candidates if c.description != "__control__"]
    real = [c for c in candidates if c.description != "__balance__" and not c.is_check]
    multi = sum(1 for c in real if len(c.amounts) >= 2)
    # Some banks print the balance only on the last line of each day, so a minority of lines can be enough.
    has_balance_column = multi >= 2 and multi / len(real) >= 0.25
    # A single signed amount column: money out printed negative (money in, on a card), the rest unsigned.
    # Then an unsigned amount means the other direction, whatever its description says.
    hints = [c.amounts[0][1] for c in real if c.amounts]
    signed_column = (
        len(hints) >= 4 and hints.count(-1) / len(hints) >= 0.1 and not any(h in (1, DEBIT_MARK) for h in hints)
    )

    base_year = _infer_year(full_text)
    months = {d.month for d in (_to_date(c.date_raw, base_year, False) for c in candidates if c.date_raw) if d}
    wraps_year = 1 in months and 12 in months
    # One PDF can hold several monthly statements; each period becomes its own statement.
    periods = list(dict.fromkeys(c.period for c in candidates + controls if c.period))
    period_names = {period: _period_name(period) for period in periods}

    def statement_for(cand: _Candidate) -> str:
        if len(periods) > 1 and cand.period:
            return f"{statement_id} · {period_names[cand.period]}"
        return statement_id

    def date_for(cand: _Candidate) -> Optional[datetime]:
        end = _to_date(cand.period[1], base_year, False) if cand.period else None
        if end is None:
            return _to_date(cand.date_raw, base_year, wraps_year)
        # Undated years follow the statement period; December items on a January statement are last year's.
        return _to_date(cand.date_raw, end.year, end.month <= 2)

    label = bank_format or f"auto:{bank_name or 'unknown'}"
    rows: List[Dict] = []
    prev_balance: Dict[Optional[str], Optional[float]] = {}
    balance_rows = 0
    verified = 0
    verified_by_account: Dict[Optional[str], int] = {}
    redacted_rows = 0
    recovered = 0
    # Lines since the last printed balance, per statement and account: [(row, direction is certain)].
    waiting: Dict[Tuple, List[Tuple[Dict, bool]]] = {}

    def sign_direction(sign_hint: int) -> Optional[str]:
        if sign_hint == 1:
            return "credit"
        if sign_hint == DEBIT_MARK:
            return "debit"
        if sign_hint == -1:
            # Banks print money out as negative; card issuers print payments and credits as negative.
            return "credit" if is_card else "debit"
        return None

    for index, cand in enumerate(candidates):
        acct = cand.account or account_number
        if cand.description == "__balance__":
            value, sign = cand.amounts[0]
            prev_balance[(cand.period, acct)] = -value if sign < 0 else value
            continue

        amount: Optional[float] = cand.amounts[0][0] if cand.amounts else None
        sign = cand.amounts[0][1] if cand.amounts else 0
        running_balance: Optional[float] = None
        direction: Optional[str] = None
        checked = False
        broken = False  # a printed balance that no reading of the amounts explains
        note = ""

        amounts = cand.amounts
        if cand.redacted and has_balance_column and len(amounts) == 1 and _is_balance_only(candidates, index, acct, amounts[0]):
            # The amount was blacked out but the balance wasn't: the balance change is the amount.
            amounts = [(0.0, 0), amounts[0]]
            amount = None

        # Best guess before any balance check, and whether it rests on firm evidence (sign, column, section).
        guess = sign_direction(sign)
        certain = guess is not None
        if guess is None and cand.section in ("credit", "debit"):
            guess, certain = cand.section, True
        if guess is None and cand.section == "checks":
            guess, certain = "debit", True
        if guess is None and signed_column and sign == 0:
            guess, certain = ("debit" if is_card else "credit"), True
        if guess is None:
            guess = _keyword_direction(cand.description, credit_words, is_card) or default_direction

        key = (cand.period, acct)
        if has_balance_column and len(amounts) >= 2 and not cand.is_check:
            bal_value, bal_sign = amounts[-1]
            running_balance = -bal_value if bal_sign < 0 else bal_value
            previous = prev_balance.get(key)
            earlier = waiting.pop(key, [])
            if previous is not None:
                if amount is None:
                    # Amount blacked out: what the balance moved by, less the day's other lines.
                    others = sum(r["amount"] if r["direction"] == "credit" else -r["amount"] for r, _ in earlier)
                    change = round(running_balance - previous - others, 2)
                    amount, direction, checked = abs(change), ("credit" if change > 0 else "debit"), True
                    note = " (amount redacted; recovered from running balance)"
                    recovered += 1
                else:
                    options = [(value, sign_direction(hint)) for value, hint in amounts[:-1] if value]
                    solved = _solve_balance(previous, running_balance, earlier, options, guess, certain)
                    if solved:
                        amount, direction = solved
                        checked = True
                    else:
                        broken = True
                if checked:
                    for earlier_row, _ in earlier:
                        earlier_row["balance_check"] = "ok"
                    verified += len(earlier)
                    verified_by_account[acct] = verified_by_account.get(acct, 0) + len(earlier)
                    balance_rows += len(earlier)
            prev_balance[key] = running_balance
            balance_rows += 1
            verified += int(checked)
            verified_by_account[acct] = verified_by_account.get(acct, 0) + int(checked)
        elif len(amounts) >= 2:
            nonzero = [a for a in amounts if a[0] != 0]
            amount, sign = nonzero[0] if nonzero else amounts[0]
            guess = sign_direction(sign) or guess

        if amount is None:
            note = " (amount redacted)"
        if direction is None:
            direction = guess

        description = (cand.description or ("Check" if cand.is_check else "Transaction")) + note
        check_number = cand.check_number
        in_check_section = cand.section == "checks"
        if check_number is None and (in_check_section or re.search(r"\bcheck\b", description, re.IGNORECASE)):
            check_match = re.search(r"\b(\d{3,6})\b", description)
            check_number = check_match.group(1) if check_match else None
            if in_check_section and check_number and description.strip() == check_number:
                description = f"Check #{check_number}"
        redacted_rows += int(cand.redacted)

        rows.append(
            {
                "statement_id": statement_for(cand),
                "bank_format": label,
                "account_number": acct,
                "statement_date": f"{cand.period[0]} – {cand.period[1]}" if cand.period else statement_date,
                "txn_date": date_for(cand),
                "txn_date_raw": cand.date_raw,
                "description": description,
                "transaction_type": "check" if (cand.is_check or check_number) else "statement",
                "direction": direction,
                "amount": amount,
                "debit": amount if direction == "debit" else None,
                "credit": amount if direction == "credit" else None,
                "running_balance": running_balance,
                "check_number": check_number,
                "source_page": cand.page,
                "source_line": cand.line_no,
                "redacted": cand.redacted,
                "section": cand.section,
                "balance_check": "ok" if checked else "break" if broken else None,
            }
        )
        if has_balance_column and running_balance is None and amount is not None and not cand.is_check:
            # No balance on this line: it is checked together with the next line that has one.
            waiting.setdefault(key, []).append((rows[-1], certain))

    # An account where no running balance could be checked (e.g. a loan's payment table) has no
    # trustworthy balance column; leave its balances blank so it reconciles as "needs review".
    verified_accounts = {acct for acct, ok in verified_by_account.items() if ok}
    for row in rows:
        if row["account_number"] not in verified_accounts:
            row["running_balance"] = None

    # Printed control totals ("10 Total Deposits : $8,337.98") per statement and account.
    totals: Dict[Tuple[str, Optional[str]], Dict[str, float]] = {}
    for control in controls:
        direction, value, count = control.control
        key = (statement_for(control), control.account or account_number)
        entry = totals.setdefault(key, {})
        entry[f"control_{direction}_total"] = entry.get(f"control_{direction}_total", 0.0) + value
        if count is not None:
            entry[f"control_{direction}_count"] = entry.get(f"control_{direction}_count", 0) + count
    for row in rows:
        row.update(totals.get((row["statement_id"], row["account_number"]), {}))

    return AutoParseOutput(
        rows=rows,
        has_balance_column=has_balance_column,
        balance_rows=balance_rows,
        balance_verified_rows=verified,
        bank_name=bank_name,
        detection_keywords=suggest_detection_keywords(full_text, bank_name),
        statement_kind="credit_card" if is_card else "bank",
        redacted_rows=redacted_rows,
        recovered_amounts=recovered,
    )


def _solve_balance(
    previous: float,
    balance: float,
    earlier: List[Tuple[Dict, bool]],
    options: List[Tuple[float, Optional[str]]],
    guess: str,
    certain: bool,
) -> Optional[Tuple[float, str]]:
    """
    Make the lines since the last printed balance add up to this one.

    Each line moves the balance up (credit) or down (debit). Starting from the best guesses,
    flip as few uncertain directions as needed until previous + changes == balance; if the
    certain ones (signs, columns) can't be made to fit, they may be flipped too. On success the
    earlier rows are updated in place and (amount, direction) for this line is returned.
    """
    for value, marked in options:
        lines = [(row["amount"], row["direction"], is_certain) for row, is_certain in earlier]
        lines.append((value, marked or guess, marked is not None or certain))
        for allow_certain in (False, True):
            flippable = [i for i, line in enumerate(lines) if allow_certain or not line[2]]
            if len(flippable) > 12:
                flippable = flippable[:12]
            for size in range(len(flippable) + 1):
                for flips in combinations(flippable, size):
                    directions = [
                        ("debit" if d == "credit" else "credit") if i in flips else d for i, (_, d, _) in enumerate(lines)
                    ]
                    total = sum(a if d == "credit" else -a for (a, _, _), d in zip(lines, directions))
                    if abs(previous + total - balance) <= 0.011:
                        for (row, _), new_direction in zip(earlier, directions):
                            if row["direction"] != new_direction:
                                row["direction"] = new_direction
                                row["debit"] = row["amount"] if new_direction == "debit" else None
                                row["credit"] = row["amount"] if new_direction == "credit" else None
                        return value, directions[-1]
    return None


def _period_name(period: Tuple[str, str]) -> str:
    """'Mar 2008' for a one-month period, otherwise 'Mar 1 – Apr 15, 2008'."""
    start = _to_date(period[0], datetime.now().year, False)
    end = _to_date(period[1], datetime.now().year, False)
    if not start or not end:
        return f"{period[0]} – {period[1]}"
    if (end - start).days <= 31 and start.month == end.month:
        return end.strftime("%b %Y")
    return f"{start:%b} {start.day} – {end:%b} {end.day}, {end.year}"


def _is_balance_only(candidates: List[_Candidate], index: int, account: Optional[str], value: Tuple[float, int]) -> bool:
    """
    For a redacted row with a single number: is that number the running balance (amount blacked out)?
    True when the next row's balance follows from it, or, on the last row, when nothing else is left.
    """
    balance = -value[0] if value[1] < 0 else value[0]
    for nxt in candidates[index + 1:]:
        if nxt.description == "__balance__" or nxt.is_check or (nxt.account or account) != (candidates[index].account or account):
            continue
        if len(nxt.amounts) < 2:
            return False
        nxt_balance = -nxt.amounts[-1][0] if nxt.amounts[-1][1] < 0 else nxt.amounts[-1][0]
        return any(abs(balance + delta - nxt_balance) <= 0.011 for v, _ in nxt.amounts[:-1] for delta in (v, -v))
    return True
