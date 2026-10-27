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
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Dict, List, Optional, Tuple

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
LEADING_DATE_RE = re.compile(rf"^(?P<d1>{DATE})(?:\s+(?P<d2>{DATE}))?(?=\s|$)", re.IGNORECASE)
# Description first, then the date(s), then only amounts to the end of the line.
TRAILING_DATE_RE = re.compile(
    rf"^(?P<desc>.*?\S)\s+(?P<d1>{DATE})(?:\s+(?P<d2>{DATE}))?\s+(?P<amts>[-($\d][\d,.\s$()\-CRDcrd]*)$",
    re.IGNORECASE,
)
CHECK_NUM_FIRST_RE = re.compile(rf"(?P<num>\d{{3,7}})\*?\s+(?P<date>{DATE})\s+(?P<amt>\$?\d[\d,]*\.\d{{2}})", re.IGNORECASE)
CHECK_DATE_FIRST_RE = re.compile(rf"(?P<date>{DATE})\s+(?P<num>\d{{3,7}})\*?\s+(?P<amt>\$?\d[\d,]*\.\d{{2}})", re.IGNORECASE)
DATE_AMOUNT_PAIR_RE = re.compile(rf"{DATE}\s+\$?\d[\d,]*\.\d{{2}}", re.IGNORECASE)
ACCOUNT_RE = re.compile(r"account\s*(?:number|no\.?|#)\s*:?\s*([0-9Xx*][0-9Xx*\-]{3,})", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
PAGE_FOOTER_RE = re.compile(r"^page\s*\d+\s*(of\s*\d+)?$", re.IGNORECASE)

OPENING_BALANCE_RE = re.compile(
    r"(previous|beginning|opening|starting|prior)\s+balance|balance\s+(forward|brought forward|last statement)",
    re.IGNORECASE,
)
CLOSING_BALANCE_RE = re.compile(r"(ending|closing|new)\s+balance", re.IGNORECASE)
CREDIT_SECTION_RE = re.compile(r"deposits|credits|additions|interest paid", re.IGNORECASE)
DEBIT_SECTION_RE = re.compile(
    r"withdrawals|debits|subtractions|purchases|payments|fees|charges|check card", re.IGNORECASE
)
CHECK_SECTION_RE = re.compile(r"checks(?!\s*card)|checkspaid", re.IGNORECASE)
SKIP_SECTION_RE = re.compile(
    r"daily\s+(ending\s+)?balance|balance\s+summary|ledger\s+balance|interest\s+charge\s+calculation",
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


@dataclass
class AutoParseOutput:
    rows: List[Dict]
    has_balance_column: bool
    balance_rows: int
    balance_verified_rows: int
    bank_name: Optional[str]
    detection_keywords: List[str] = field(default_factory=list)

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


def _parse_amount(match: re.Match) -> Tuple[float, int]:
    value = float(f"{match.group('num').replace(',', '')}.{match.group('cents')}")
    sign = 0
    suffix = (match.group("suffix") or "").strip().upper()
    if match.group("neg") or match.group("close") or suffix in ("-", "DR"):
        sign = -1
    elif suffix == "CR":
        sign = 1
    return value, sign


def _strip_amounts_and_dates(text: str) -> str:
    text = AMOUNT_RE.sub(" ", text)
    text = DATE_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip(" -*=:")


def _section_for_header(line: str) -> Optional[str]:
    """Return the section a heading line starts, or None when the line is not a heading."""
    if AMOUNT_RE.search(line) or len(line.split()) > 9:
        return None
    if SKIP_SECTION_RE.search(line):
        return "skip"
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
    """Best guess at the bank's name from the first page header."""
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


def _collect_candidates(pages: List[str]) -> List[_Candidate]:
    candidates: List[_Candidate] = []
    section = "all"
    account: Optional[str] = None
    orphan_lines: List[str] = []  # Description text seen before its dated line (multi-line layouts).
    last_was_txn = False
    pending: Optional[_Candidate] = None  # Dated line whose amount is on a later line.

    for page_number, page_text in enumerate(pages, start=1):
        lines = [re.sub(r"\s+", " ", ln).strip() for ln in page_text.splitlines()]
        last_was_txn = False
        orphan_lines.clear()
        for line_number, line in enumerate(lines, start=1):
            if not line or PAGE_FOOTER_RE.search(line):
                continue
            account_match = ACCOUNT_RE.search(line)
            if account_match:
                account = account_match.group(1)

            header_section = _section_for_header(line)
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
            if section == "skip" or "%" in line or lower.startswith(("total", "subtotal")):
                last_was_txn = False
                continue
            if OPENING_BALANCE_RE.search(line) or CLOSING_BALANCE_RE.search(line):
                if amount_matches and LEADING_DATE_RE.match(line):
                    value, sign = _parse_amount(amount_matches[-1])
                    candidates.append(
                        _Candidate(page_number, line_number, "", "__balance__", [(value, sign)], section, account)
                    )
                last_was_txn = False
                continue

            # Grid of checks: "4416 07/08/19 $100.00 4419* 07/08/19 $266.00" or "05-12 1001 75.00 0001257".
            check_hits = list(CHECK_NUM_FIRST_RE.finditer(line))
            if not check_hits and section == "checks":
                check_hits = list(CHECK_DATE_FIRST_RE.finditer(line))
            if check_hits and (section == "checks" or len(check_hits) >= 2):
                for hit in check_hits:
                    value = float(hit.group("amt").replace("$", "").replace(",", ""))
                    candidates.append(
                        _Candidate(
                            page_number, line_number, hit.group("date"), f"Check #{hit.group('num')}",
                            [(value, -1)], "checks", account, is_check=True, check_number=hit.group("num"),
                        )
                    )
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
                if not rest_amounts:
                    pending = _Candidate(page_number, line_number, leading.group("d1"), description, [], section, account)
                    last_was_txn = False
                    continue
                if not description and orphan_lines:
                    description = " ".join(orphan_lines)
                candidates.append(
                    _Candidate(
                        page_number, line_number, leading.group("d1"), description,
                        [_parse_amount(m) for m in rest_amounts], section, account,
                    )
                )
                orphan_lines.clear()
                pending = None
                last_was_txn = True
                continue

            trailing = TRAILING_DATE_RE.match(line)
            if trailing and AMOUNT_RE.search(trailing.group("amts")):
                tail_amounts = list(AMOUNT_RE.finditer(trailing.group("amts")))
                description = " ".join(orphan_lines + [trailing.group("desc")]).strip()
                candidates.append(
                    _Candidate(
                        page_number, line_number, trailing.group("d1"), _strip_amounts_and_dates(description),
                        [_parse_amount(m) for m in tail_amounts], section, account,
                    )
                )
                orphan_lines.clear()
                pending = None
                last_was_txn = True
                continue

            if pending is not None:
                if amount_matches:
                    pending.amounts = [_parse_amount(m) for m in amount_matches]
                    extra = _strip_amounts_and_dates(line)
                    if extra:
                        pending.description = f"{pending.description} {extra}".strip()
                    candidates.append(pending)
                    pending = None
                    last_was_txn = True
                elif len(pending.description) < 200:
                    pending.description = f"{pending.description} {line}".strip()
                continue

            if amount_matches:
                last_was_txn = False
                orphan_lines.clear()
                continue

            # Text-only line: continues the previous transaction, or precedes the next one.
            if last_was_txn and candidates and len(line) <= 60:
                candidates[-1].description = f"{candidates[-1].description} {line}".strip()
                last_was_txn = False
            else:
                orphan_lines.append(line)
                orphan_lines = orphan_lines[-3:]

    return _drop_duplicate_checks(candidates)


def _drop_duplicate_checks(candidates: List[_Candidate]) -> List[_Candidate]:
    """Many banks list each check in the register and again in a check summary; keep it once."""
    register = [c for c in candidates if not c.is_check and c.description != "__balance__"]
    kept: List[_Candidate] = []
    for cand in candidates:
        if cand.is_check:
            amount = cand.amounts[0][0]
            duplicate = any(
                any(abs(value - amount) < 0.005 for value, _ in reg.amounts[:1])
                and re.search(rf"\b{re.escape(cand.check_number or '')}\b", reg.description)
                for reg in register
            )
            if duplicate:
                continue
        kept.append(cand)
    return kept


def _keyword_direction(description: str, credit_keywords: List[str]) -> Optional[str]:
    text = description.lower()
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
    candidates = _collect_candidates(pages)

    real = [c for c in candidates if c.description != "__balance__" and not c.is_check]
    multi = sum(1 for c in real if len(c.amounts) >= 2)
    has_balance_column = bool(real) and multi / len(real) >= 0.6

    base_year = _infer_year(full_text)
    months = {d.month for d in (_to_date(c.date_raw, base_year, False) for c in candidates if c.date_raw) if d}
    wraps_year = 1 in months and 12 in months

    label = bank_format or f"auto:{bank_name or 'unknown'}"
    rows: List[Dict] = []
    prev_balance: Dict[Optional[str], Optional[float]] = {}
    balance_rows = 0
    verified = 0
    verified_by_account: Dict[Optional[str], int] = {}

    for cand in candidates:
        acct = cand.account or account_number
        if cand.description == "__balance__":
            value, sign = cand.amounts[0]
            prev_balance[acct] = -value if sign < 0 else value
            continue

        amount, sign = cand.amounts[0]
        running_balance: Optional[float] = None
        direction: Optional[str] = None
        checked = False

        if has_balance_column and len(cand.amounts) >= 2 and not cand.is_check:
            bal_value, bal_sign = cand.amounts[-1]
            running_balance = -bal_value if bal_sign < 0 else bal_value
            previous = prev_balance.get(acct)
            if previous is not None:
                # Try each non-balance amount; the one that explains the balance change is the transaction.
                for value, _ in cand.amounts[:-1]:
                    if value == 0:
                        continue
                    if abs(previous + value - running_balance) <= 0.011:
                        amount, direction, checked = value, "credit", True
                        break
                    if abs(previous - value - running_balance) <= 0.011:
                        amount, direction, checked = value, "debit", True
                        break
            prev_balance[acct] = running_balance
            balance_rows += 1
            verified += int(checked)
            verified_by_account[acct] = verified_by_account.get(acct, 0) + int(checked)
        elif len(cand.amounts) >= 2:
            nonzero = [a for a in cand.amounts if a[0] != 0]
            amount, sign = nonzero[0] if nonzero else cand.amounts[0]

        if direction is None and sign:
            direction = "debit" if sign < 0 else "credit"
        if direction is None and cand.section in ("credit", "debit"):
            direction = cand.section
        if direction is None and cand.section == "checks":
            direction = "debit"
        if direction is None:
            direction = _keyword_direction(cand.description, credit_words) or default_direction

        description = cand.description or ("Check" if cand.is_check else "Transaction")
        check_number = cand.check_number
        if check_number is None and "check" in description.lower():
            check_match = re.search(r"\b(\d{3,6})\b", description)
            check_number = check_match.group(1) if check_match else None

        rows.append(
            {
                "statement_id": statement_id,
                "bank_format": label,
                "account_number": acct,
                "statement_date": statement_date,
                "txn_date": _to_date(cand.date_raw, base_year, wraps_year),
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
            }
        )

    # An account where no running balance could be checked (e.g. a loan's payment table) has no
    # trustworthy balance column; leave its balances blank so it reconciles as "needs review".
    verified_accounts = {acct for acct, ok in verified_by_account.items() if ok}
    for row in rows:
        if row["account_number"] not in verified_accounts:
            row["running_balance"] = None

    return AutoParseOutput(
        rows=rows,
        has_balance_column=has_balance_column,
        balance_rows=balance_rows,
        balance_verified_rows=verified,
        bank_name=bank_name,
        detection_keywords=suggest_detection_keywords(full_text, bank_name),
    )
