"""
Reads one statement PDF into a table of transactions, with categories, risk scores and flags.

parse_statement() is the entry point the app calls for every uploaded file:

1. pdf_text.extract_pdf gets each page's text (OCR for scanned pages, redaction-aware).
2. A reader turns the text into transaction rows. A saved bank (template_manager) is used if
   its keywords match; two older built-in layouts have their own readers; everything else,
   which is nearly every statement, goes to the generic reader in auto_parser.py.
3. Each row gets a category (deposit, check, card purchase, ...) and a simple risk score.
4. Per-file flags are added (duplicates, large and round amounts, check-number gaps), and
   authenticity.check_document runs the document checks.

Fraud patterns that need several statements together (structuring, new payees, ...) are
found later, across all uploaded files, by fraud_rules.py.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Dict, List, Optional

import pandas as pd

from auto_parser import (
    auto_parse,
    detect_statement_kind,
    suggest_bank_name,
    suggest_detection_keywords,
    summary_balances,
)
from authenticity import check_document
from pdf_text import extract_pdf
from template_manager import detect_template, load_templates

# Patterns used by the older line-based readers below (the generic reader has its own).
AMOUNT_RE = re.compile(r"\$?\d[\d,]*\.\d{2}")  # 1,234.56 or $1,234.56
DATE_SLASH_RE = re.compile(r"^\d{2}/\d{2}/\d{4}")  # a line starting 03/14/2025
DATE_DASH_RE = re.compile(r"\b\d{2}-\d{2}\b")  # 03-14

# Checked in order, as whole words ("fee" doesn't match "coffee"); the first match wins.
CATEGORY_RULES = {
    "deposit": ("deposit", "credit", "refund", "reversal"),
    "fee_charge": ("service charge", "paper statement charge", "fee", "charge", "maintenance fee"),
    "atm_withdrawal": ("atm withdrawal", "atm", "cash withdrawal", "withdrwl"),
    "card_purchase": ("visa", "debit card", "card purchase", "retail", "checkcard", "check card", "purchase", "pos"),
    "check": ("check",),
    "ach_transfer": ("ach", "transfer", "settlement"),
    "loan_payment": ("loan payment", "reserve", "interest charged"),
}


@dataclass
class ParseResult:
    """Everything read from one statement file, as the app displays and exports it."""
    transactions: pd.DataFrame
    flags: pd.DataFrame
    raw_text: pd.DataFrame
    notes: List[str] = field(default_factory=list)  # Plain-English remarks shown next to the file name.
    document_checks: List = field(default_factory=list)  # authenticity.Check results for the file
    # The file as received: name, size, SHA-256 fingerprint, pages, pages read with OCR (for the evidence record).
    source: Dict = field(default_factory=dict)


def _to_amount(text: str) -> Optional[float]:
    """'$1,234.56' -> 1234.56; None if the text isn't an amount."""
    if text is None:
        return None
    cleaned = text.replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_pdf_pages(file_bytes: bytes) -> List[str]:
    """The text of each page (see pdf_text.extract_pdf)."""
    return extract_pdf(file_bytes).pages


def _detect_format(full_text: str) -> str:
    """Which of the two older built-in layouts the statement is, if either; otherwise 'generic_statement'."""
    lowered = full_text.lower()
    if "true checking" in lowered and "account activity summary" in lowered:
        return "carson_bank_statement"
    if "connections checking" in lowered and "deposits & other credits" in lowered:
        return "legacy_sectioned_statement"
    return "generic_statement"


def _parse_meta(text: str) -> Dict[str, Optional[str]]:
    """The account number and statement date printed in the header, when they can be found."""
    account_match = re.search(r"Account(?:\s+#|\s+Number:)\s*([0-9]+)", text, re.IGNORECASE)
    account_number = account_match.group(1) if account_match else None

    statement_date = None
    date_match = re.search(r"Statement Date:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})", text)
    if date_match:
        statement_date = date_match.group(1)
    else:
        date_match = re.search(r"([A-Za-z]+\s+\d{1,2},\s+20\d{2})\s+Account Number", text)
        if date_match:
            statement_date = date_match.group(1)

    return {"account_number": account_number, "statement_date": statement_date}


def _classify_direction(description: str, section: str = "") -> str:
    """
    'credit' when the description (or section) says money came in, otherwise 'debit'. Used by the older
    readers only.
    """
    check_text = f"{description} {section}".lower()
    credit_terms = ("deposit", "credit", "refund", "reversal")
    return "credit" if any(term in check_text for term in credit_terms) else "debit"


def _safe_date(raw_date: str, statement_date: Optional[str]) -> Optional[datetime]:
    """Parse '03/14/2025' or '03-14' (taking the year from the statement date); None if it can't be read."""
    for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%m-%d/%Y"):
        try:
            return datetime.strptime(raw_date, fmt)
        except ValueError:
            continue

    if "-" in raw_date and statement_date:
        try:
            year = datetime.strptime(statement_date, "%B %d, %Y").year
            return datetime.strptime(f"{raw_date}-{year}", "%m-%d-%Y")
        except ValueError:
            return None
    return None


def _categorize_transaction(
    description: str,
    direction: str,
    transaction_type: str,
    check_number: Optional[str],
    statement_kind: str = "bank",
) -> str:
    """
    The transaction's category, for summaries, charts and risk scoring.

    Credit card statements use card categories (payment, credit, fee, cash advance, purchase). For bank
    statements, checks are recognized first, then CATEGORY_RULES are tried in order as whole words;
    whatever doesn't match is other_credit or other_debit.
    """
    text = (description or "").lower()
    if statement_kind == "credit_card":
        if direction == "credit":
            return "card_payment" if "payment" in text else "card_credit"
        if "interest" in text or "fee" in text:
            return "fee_charge"
        if "cash advance" in text or "atm" in text:
            return "atm_withdrawal"
        return "card_purchase"
    has_check_number = check_number is not None and not pd.isna(check_number) and str(check_number).strip() != ""
    if transaction_type == "check" or (re.search(r"\bcheck\b", text) and has_check_number) or re.match(r"(share\s+)?draft\b", text):
        return "check"

    for category, terms in CATEGORY_RULES.items():
        if any(re.search(rf"\b{re.escape(term)}\b", text) for term in terms):
            if category == "deposit" and direction != "credit":
                continue
            return category

    if direction == "credit":
        return "other_credit"
    return "other_debit"


def _score_transaction_risk(row: pd.Series, large_txn_threshold: float) -> tuple[int, str, str]:
    # Points add up from a baseline of 5 and are capped at 100: 70+ is high, 40+ medium.
    """
    A simple per-transaction risk score: (score 0-100, 'low'/'medium'/'high', reasons). Fraud patterns
    found across statements (fraud_rules.py) add to it later.
    """
    score = 5
    reasons: List[str] = []

    amount = float(row.get("amount", 0) or 0)
    category = row.get("txn_category", "other_debit")
    description = str(row.get("description", "")).lower()
    check_number = row.get("check_number")
    txn_date = row.get("txn_date")

    # Size, relative to the "Flag transactions over" setting.
    if amount >= large_txn_threshold * 3:
        score += 35
        reasons.append("very large amount")
    elif amount >= large_txn_threshold * 1.5:
        score += 25
        reasons.append("large amount")
    elif amount >= large_txn_threshold:
        score += 15
        reasons.append("threshold amount")

    # Kinds of transaction that move money out of reach (cash, transfers, checks) weigh more.
    if category in {"atm_withdrawal", "ach_transfer"}:
        score += 18
        reasons.append("cash/transfer movement")
    if category == "check":
        score += 15
        reasons.append("check transaction")
    if category == "fee_charge":
        score += 8
        reasons.append("fee/charge activity")
    if category == "loan_payment":
        score += 10
        reasons.append("loan-linked activity")

    # Habits common in fraud: round amounts, corrections, unusual check numbers, weekends.
    if amount > 0 and float(amount).is_integer():
        score += 8
        reasons.append("round-dollar amount")
    if any(term in description for term in ("correction", "adjustment", "reversal")):
        score += 12
        reasons.append("correction/reversal keyword")
    if check_number and str(check_number).isdigit() and int(check_number) >= 4000:
        score += 6
        reasons.append("high check number range")

    if isinstance(txn_date, pd.Timestamp) and txn_date.weekday() >= 5:
        score += 6
        reasons.append("weekend transaction")

    score = min(int(score), 100)
    if score >= 70:
        risk_level = "high"
    elif score >= 40:
        risk_level = "medium"
    else:
        risk_level = "low"

    return score, risk_level, "; ".join(reasons) if reasons else "baseline profile"


def _parse_carson_lines(
    pages: List[str],
    statement_id: str,
    account_number: Optional[str],
    statement_date: Optional[str],
) -> List[Dict]:
    """Reader for the older built-in 'Carson Bank' layout. Kept as a fallback; the generic reader handles it first."""
    rows: List[Dict] = []
    pending: Optional[Dict] = None

    for page_number, page_text in enumerate(pages, start=1):
        lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
        for line_number, line in enumerate(lines, start=1):
            # A dated line starts a transaction; its amounts may be on the same line or the next.
            if DATE_SLASH_RE.match(line):
                date_text = line[:10]
                body = line[10:].strip()
                amounts = AMOUNT_RE.findall(body)
                description = body
                for amt in amounts:
                    description = description.replace(amt, "")
                description = re.sub(r"\s+", " ", description).strip(" -")

                if not amounts:
                    pending = {
                        "statement_id": statement_id,
                        "bank_format": "carson_bank_statement",
                        "account_number": account_number,
                        "statement_date": statement_date,
                        "txn_date": _safe_date(date_text, statement_date),
                        "txn_date_raw": date_text,
                        "description": description,
                        "source_page": page_number,
                        "source_line": line_number,
                    }
                    continue

                amount = _to_amount(amounts[0])
                running_balance = _to_amount(amounts[1]) if len(amounts) > 1 else None
                direction = _classify_direction(description)
                debit = amount if direction == "debit" else None
                credit = amount if direction == "credit" else None
                check_match = re.search(r"\b(\d{3,6})\b", description)

                rows.append(
                    {
                        "statement_id": statement_id,
                        "bank_format": "carson_bank_statement",
                        "account_number": account_number,
                        "statement_date": statement_date,
                        "txn_date": _safe_date(date_text, statement_date),
                        "txn_date_raw": date_text,
                        "description": description,
                        "transaction_type": "check" if "check" in description.lower() else "statement",
                        "direction": direction,
                        "amount": amount,
                        "debit": debit,
                        "credit": credit,
                        "running_balance": running_balance,
                        "check_number": check_match.group(1) if check_match else None,
                        "source_page": page_number,
                        "source_line": line_number,
                    }
                )
                continue

            # A transaction whose amount wasn't on its dated line: finish it, or add to its description.
            if pending:
                if AMOUNT_RE.search(line):
                    amounts = AMOUNT_RE.findall(line)
                    amount = _to_amount(amounts[0]) if amounts else None
                    running_balance = _to_amount(amounts[1]) if len(amounts) > 1 else None
                    direction = _classify_direction(pending["description"])
                    debit = amount if direction == "debit" else None
                    credit = amount if direction == "credit" else None
                    check_match = re.search(r"\b(\d{3,6})\b", pending["description"])
                    rows.append(
                        {
                            **pending,
                            "transaction_type": "statement",
                            "direction": direction,
                            "amount": amount,
                            "debit": debit,
                            "credit": credit,
                            "running_balance": running_balance,
                            "check_number": check_match.group(1) if check_match else None,
                        }
                    )
                    pending = None
                else:
                    pending["description"] = f"{pending['description']} {line}".strip()

    return rows


def _parse_legacy_lines(
    pages: List[str],
    statement_id: str,
    account_number: Optional[str],
    statement_date: Optional[str],
) -> List[Dict]:
    """
    Reader for the older built-in 'Connections Checking' layout, whose deposits, debits and checks are
    listed in separate sections.
    """
    rows: List[Dict] = []
    section = ""
    recent_section_lines: List[str] = []

    for page_number, page_text in enumerate(pages, start=1):
        lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
        for line_number, line in enumerate(lines, start=1):
            lower = line.lower()
            # Section headings decide the direction of everything below them.
            if "deposits & other credits account" in lower:
                section = "deposits"
                recent_section_lines.clear()
                continue
            if "atm withdrawals & debits account" in lower:
                section = "atm_debits"
                recent_section_lines.clear()
                continue
            if "checks paid account" in lower:
                section = "checks_paid"
                recent_section_lines.clear()
                continue
            if lower.startswith("total "):
                continue

            recent_section_lines.append(line)
            recent_section_lines = recent_section_lines[-3:]

            if section == "checks_paid":
                match = re.search(r"(\d{2}-\d{2})\s+(\d{3,6})\s+(\d[\d,]*\.\d{2})\s+(\d+)", line)
                if not match:
                    continue
                date_text, check_no, amount_text, _ = match.groups()
                amount = _to_amount(amount_text)
                rows.append(
                    {
                        "statement_id": statement_id,
                        "bank_format": "legacy_sectioned_statement",
                        "account_number": account_number,
                        "statement_date": statement_date,
                        "txn_date": _safe_date(date_text, statement_date),
                        "txn_date_raw": date_text,
                        "description": f"Check Paid #{check_no}",
                        "transaction_type": "check",
                        "direction": "debit",
                        "amount": amount,
                        "debit": amount,
                        "credit": None,
                        "running_balance": None,
                        "check_number": check_no,
                        "source_page": page_number,
                        "source_line": line_number,
                    }
                )
                continue

            if section in ("deposits", "atm_debits"):
                if not DATE_DASH_RE.search(line) or not AMOUNT_RE.search(line):
                    continue

                dates = DATE_DASH_RE.findall(line)
                amounts = AMOUNT_RE.findall(line)
                if not dates or not amounts:
                    continue

                date_text = dates[0]
                amount = _to_amount(amounts[-1])
                direction = "credit" if section == "deposits" else "debit"
                amount_pattern = re.escape(amounts[-1])
                desc_candidate = re.sub(amount_pattern, "", line)
                for dt in dates:
                    desc_candidate = desc_candidate.replace(dt, "")
                desc_candidate = re.sub(r"\b\d{6,}\b", "", desc_candidate)
                desc_candidate = re.sub(r"\s+", " ", desc_candidate).strip(" -")
                # A line with only a date and amount takes its description from the lines just above it.
                if len(desc_candidate) < 6 and recent_section_lines:
                    desc_candidate = " ".join(recent_section_lines).strip()

                rows.append(
                    {
                        "statement_id": statement_id,
                        "bank_format": "legacy_sectioned_statement",
                        "account_number": account_number,
                        "statement_date": statement_date,
                        "txn_date": _safe_date(date_text, statement_date),
                        "txn_date_raw": date_text,
                        "description": desc_candidate,
                        "transaction_type": "statement",
                        "direction": direction,
                        "amount": amount,
                        "debit": amount if direction == "debit" else None,
                        "credit": amount if direction == "credit" else None,
                        "running_balance": None,
                        "check_number": None,
                        "source_page": page_number,
                        "source_line": line_number,
                    }
                )

    return rows


def _custom_direction(description: str, template: Dict) -> str:
    """
    Direction for a saved bank's line: money in if a credit keyword appears, otherwise the bank's
    default direction.
    """
    text = (description or "").lower()
    credit_terms = template.get("credit_keywords", [])
    if any(term in text for term in credit_terms):
        return "credit"
    return template.get("default_direction", "debit")


def _parse_custom_lines(
    pages: List[str],
    statement_id: str,
    account_number: Optional[str],
    statement_date: Optional[str],
    template: Dict,
) -> List[Dict]:
    """
    Reader for saved banks that use one of the two line-based styles (most saved banks use the generic
    reader instead).
    """
    rows: List[Dict] = []
    parse_style = template.get("parse_style", "slash_leading_amount_balance")
    template_name = str(template.get("template_name", "custom_template")).strip() or "custom_template"

    for page_number, page_text in enumerate(pages, start=1):
        lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
        for line_number, line in enumerate(lines, start=1):
            amounts = AMOUNT_RE.findall(line)
            if not amounts:
                continue

            if parse_style == "slash_leading_amount_balance":
                if not DATE_SLASH_RE.match(line):
                    continue
                date_text = line[:10]
                body = line[10:].strip()
                body_amounts = AMOUNT_RE.findall(body)
                if not body_amounts:
                    continue
                amount = _to_amount(body_amounts[0])
                running_balance = _to_amount(body_amounts[1]) if len(body_amounts) > 1 else None
                description = body
                for amt in body_amounts:
                    description = description.replace(amt, "")
                description = re.sub(r"\s+", " ", description).strip(" -")

            elif parse_style == "date_dash_last_amount":
                date_hits = DATE_DASH_RE.findall(line)
                if not date_hits:
                    continue
                date_text = date_hits[0]
                amount = _to_amount(amounts[-1])
                running_balance = None
                description = line
                description = description.replace(amounts[-1], "")
                for date_hit in date_hits:
                    description = description.replace(date_hit, "")
                description = re.sub(r"\s+", " ", description).strip(" -")
            else:
                continue

            direction = _custom_direction(description, template)
            debit = amount if direction == "debit" else None
            credit = amount if direction == "credit" else None
            check_match = re.search(r"\b(\d{3,6})\b", description)

            rows.append(
                {
                    "statement_id": statement_id,
                    "bank_format": f"custom:{template_name}",
                    "account_number": account_number,
                    "statement_date": statement_date,
                    "txn_date": _safe_date(date_text, statement_date),
                    "txn_date_raw": date_text,
                    "description": description,
                    "transaction_type": "check" if "check" in description.lower() else "statement",
                    "direction": direction,
                    "amount": amount,
                    "debit": debit,
                    "credit": credit,
                    "running_balance": running_balance,
                    "check_number": check_match.group(1) if check_match else None,
                    "source_page": page_number,
                    "source_line": line_number,
                }
            )

    return rows


def _build_flags(df: pd.DataFrame, large_txn_threshold: float) -> pd.DataFrame:
    """
    Per-file flags for the Red Flags tab: duplicates, round amounts of $500 or more, large amounts,
    check-number gaps, and every medium- or high-risk transaction.
    """
    if df.empty:
        return pd.DataFrame(
            columns=["flag_type", "severity", "message", "txn_date", "amount", "description", "check_number"]
        )

    flags: List[Dict] = []
    # Exact duplicates: same date, amount and description.
    key_cols = ["txn_date_raw", "amount", "description"]
    dupes = df[df.duplicated(key_cols, keep=False)]
    for _, row in dupes.iterrows():
        flags.append(
            {
                "flag_type": "duplicate_transaction",
                "severity": "medium",
                "message": "Same date, amount, and description appears multiple times.",
                "txn_date": row["txn_date_raw"],
                "amount": row["amount"],
                "description": row["description"],
                "check_number": row["check_number"],
            }
        )

    # Small round amounts ($20 at an ATM) are everyday; only larger ones are worth a flag.
    rounded = df[(df["amount"].fillna(0) >= 500) & df["amount"].fillna(0).apply(lambda x: float(x).is_integer())]
    for _, row in rounded.iterrows():
        flags.append(
            {
                "flag_type": "round_dollar",
                "severity": "low",
                "message": "Transaction amount is a round-dollar value.",
                "txn_date": row["txn_date_raw"],
                "amount": row["amount"],
                "description": row["description"],
                "check_number": row["check_number"],
            }
        )

    # Above the "Flag transactions over" setting.
    large = df[df["amount"].fillna(0) >= large_txn_threshold]
    for _, row in large.iterrows():
        flags.append(
            {
                "flag_type": "large_transaction",
                "severity": "high",
                "message": f"Transaction exceeds configured threshold (${large_txn_threshold:,.0f}).",
                "txn_date": row["txn_date_raw"],
                "amount": row["amount"],
                "description": row["description"],
                "check_number": row["check_number"],
            }
        )

    # Missing check numbers between the lowest and highest check that cleared.
    checks = (
        df["check_number"]
        .dropna()
        .astype(str)
        .str.extract(r"(\d+)", expand=False)
        .dropna()
        .astype(int)
        .sort_values()
        .unique()
    )
    if len(checks) > 1:
        for previous, current in zip(checks[:-1], checks[1:]):
            if current - previous > 1:
                flags.append(
                    {
                        "flag_type": "check_sequence_gap",
                        "severity": "medium",
                        "message": f"Gap detected between check #{previous} and #{current}.",
                        "txn_date": "",
                        "amount": None,
                        "description": "Check numbering discontinuity",
                        "check_number": f"{previous}->{current}",
                    }
                )

    # Every medium- and high-risk transaction from the risk score.
    elevated = df[df["risk_level"].isin(["high", "medium"])].copy()
    for _, row in elevated.iterrows():
        flags.append(
            {
                "flag_type": "risk_model",
                "severity": "high" if row["risk_level"] == "high" else "medium",
                "message": f"Model risk score {int(row['risk_score'])} ({row['risk_level']}).",
                "txn_date": row["txn_date_raw"],
                "amount": row["amount"],
                "description": row["description"],
                "check_number": row["check_number"],
            }
        )

    flags_df = pd.DataFrame(flags).drop_duplicates()
    if flags_df.empty:
        return pd.DataFrame(
            columns=["flag_type", "severity", "message", "txn_date", "amount", "description", "check_number"]
        )
    return flags_df.sort_values(["severity", "flag_type"]).reset_index(drop=True)


@dataclass
class StatementAnalysis:
    """What the app learned from one uploaded statement, for the one-click template flow."""

    has_text: bool
    built_in_format: Optional[str]
    matched_template: Optional[str]
    bank_name: Optional[str]
    detection_keywords: List[str]
    confidence: str
    has_balance_column: bool
    balance_rows: int
    balance_verified_rows: int
    preview: pd.DataFrame


# How the older built-in layouts are named on screen.
BUILT_IN_FORMAT_NAMES = {
    "carson_bank_statement": "Carson Bank (built in)",
    "legacy_sectioned_statement": "Connections Checking (built in)",
}


def analyze_statement(file_name: str, file_bytes: bytes) -> StatementAnalysis:
    """Read a statement with the generic reader and suggest a template for it."""
    pages = _extract_pdf_pages(file_bytes)
    full_text = "\n".join(pages)
    meta = _parse_meta(full_text)
    fmt = _detect_format(full_text)
    matched = detect_template(full_text, load_templates())
    output = auto_parse(pages, file_name.rsplit(".", 1)[0], meta.get("account_number"), meta.get("statement_date"))
    preview = pd.DataFrame(output.rows)
    if not preview.empty:
        preview = preview[["txn_date", "description", "debit", "credit", "running_balance"]]
        preview["txn_date"] = pd.to_datetime(preview["txn_date"], errors="coerce").dt.date
        for money_col in ("debit", "credit", "running_balance"):
            preview[money_col] = pd.to_numeric(preview[money_col], errors="coerce")
    bank_name = output.bank_name or suggest_bank_name(full_text)
    return StatementAnalysis(
        has_text=bool(full_text.strip()),
        built_in_format=BUILT_IN_FORMAT_NAMES.get(fmt),
        matched_template=matched["template_name"] if matched else None,
        bank_name=bank_name,
        detection_keywords=output.detection_keywords or suggest_detection_keywords(full_text, bank_name),
        confidence=output.confidence,
        has_balance_column=output.has_balance_column,
        balance_rows=output.balance_rows,
        balance_verified_rows=output.balance_verified_rows,
        preview=preview,
    )


def parse_statement(file_name: str, file_bytes: bytes, large_txn_threshold: float = 1000.0, progress=None) -> ParseResult:
    """
    Parse one statement PDF. `progress(done, total)` reports OCR progress on scanned pages.

    `file_name` names the statement (without its extension) in every table and export;
    `large_txn_threshold` is the "Flag transactions over" setting.
    """
    # Text first, then facts about the whole statement: card or bank, printed opening and
    # closing balances, which reader to use.
    extracted = extract_pdf(file_bytes, progress)
    pages = extracted.pages
    full_text = "\n".join(pages)
    statement_kind = detect_statement_kind(full_text)
    opening_balance, closing_balance = summary_balances(full_text)
    fmt = _detect_format(full_text)
    templates = load_templates()
    matched_template = detect_template(full_text, templates)
    meta = _parse_meta(full_text)

    statement_id = file_name.rsplit(".", 1)[0]
    account_number = meta.get("account_number")
    statement_date = meta.get("statement_date")

    # Pick a reader: a saved bank first, then the older built-in layouts, then the generic reader.
    if matched_template and matched_template.get("parse_style") == "auto":
        rows = auto_parse(
            pages,
            statement_id,
            account_number,
            statement_date,
            bank_format=f"custom:{matched_template['template_name']}",
            default_direction=matched_template.get("default_direction", "debit"),
            credit_keywords=matched_template.get("credit_keywords") or None,
        ).rows
    elif matched_template:
        rows = _parse_custom_lines(pages, statement_id, account_number, statement_date, matched_template)
        if not rows:
            rows = auto_parse(pages, statement_id, account_number, statement_date).rows
    elif fmt == "carson_bank_statement":
        # The generic reader verifies each running balance, so it skips the summary and interest
        # tables that the line-based Carson parser misreads as transactions.
        rows = auto_parse(pages, statement_id, account_number, statement_date, bank_format=fmt).rows
        if not rows:
            rows = _parse_carson_lines(pages, statement_id, account_number, statement_date)
    elif fmt == "legacy_sectioned_statement":
        rows = _parse_legacy_lines(pages, statement_id, account_number, statement_date)
    else:
        # Unknown layout: read it generically instead of requiring a template first.
        rows = auto_parse(pages, statement_id, account_number, statement_date).rows
        if not rows:
            rows = _parse_carson_lines(pages, statement_id, account_number, statement_date)
            rows.extend(_parse_legacy_lines(pages, statement_id, account_number, statement_date))

    # Every reader's rows end up with the same columns, in this order.
    tx_columns = [
        "statement_id",
        "bank_format",
        "account_number",
        "statement_date",
        "txn_date",
        "txn_date_raw",
        "description",
        "transaction_type",
        "direction",
        "amount",
        "debit",
        "credit",
        "running_balance",
        "check_number",
        "source_page",
        "source_line",
        "txn_category",
        "risk_score",
        "risk_level",
        "risk_reasons",
        "redacted",
        "statement_kind",
        "statement_opening_balance",
        "statement_closing_balance",
        "control_credit_total",
        "control_credit_count",
        "control_debit_total",
        "control_debit_count",
        "section",
        "balance_check",
        "source_file",
        "source_sha256",
    ]
    file_sha256 = hashlib.sha256(file_bytes).hexdigest()
    transactions = pd.DataFrame(rows, columns=tx_columns)
    # Every row records which file it came from, by name and by fingerprint.
    transactions["source_file"] = file_name
    transactions["source_sha256"] = file_sha256
    # Statement-level facts on every row, so the reconciliation can use the printed summary balances.
    transactions["statement_kind"] = statement_kind
    transactions["statement_opening_balance"] = opening_balance
    transactions["statement_closing_balance"] = closing_balance
    transactions["redacted"] = transactions["redacted"].fillna(False).astype(bool)
    if not transactions.empty:
        # Proper types, then a category and a risk score for each row, then date order.
        transactions["txn_date"] = pd.to_datetime(transactions["txn_date"], errors="coerce")
        transactions["amount"] = pd.to_numeric(transactions["amount"], errors="coerce")
        transactions["debit"] = pd.to_numeric(transactions["debit"], errors="coerce")
        transactions["credit"] = pd.to_numeric(transactions["credit"], errors="coerce")
        transactions["running_balance"] = pd.to_numeric(transactions["running_balance"], errors="coerce")
        transactions["txn_category"] = transactions.apply(
            lambda row: _categorize_transaction(
                row.get("description", ""),
                row.get("direction", "debit"),
                row.get("transaction_type", "statement"),
                row.get("check_number"),
                statement_kind,
            ),
            axis=1,
        )
        risk_values = transactions.apply(
            lambda row: _score_transaction_risk(row, large_txn_threshold=large_txn_threshold),
            axis=1,
            result_type="expand",
        )
        risk_values.columns = ["risk_score", "risk_level", "risk_reasons"]
        transactions[["risk_score", "risk_level", "risk_reasons"]] = risk_values
        transactions = transactions.sort_values(["txn_date", "source_page", "source_line"]).reset_index(drop=True)

    flags = _build_flags(transactions, large_txn_threshold=large_txn_threshold)
    # The text of every page, for the optional Raw_Text sheet of the workpaper.
    raw_rows = []
    for idx, page_text in enumerate(pages, start=1):
        raw_rows.append({"statement_id": statement_id, "page": idx, "text": page_text})
    raw_text = pd.DataFrame(raw_rows)

    # Short remarks shown next to the file name: scanned, credit card, redacted, leaky redactions.
    notes: List[str] = []
    if extracted.ocr_pages:
        notes.append(f"Scanned: {extracted.ocr_pages} page{'s' if extracted.ocr_pages != 1 else ''} read with OCR")
    if extracted.unread_scanned_pages:
        notes.append(
            f"{extracted.unread_scanned_pages} scanned page{'s' if extracted.unread_scanned_pages != 1 else ''} "
            "couldn't be read: reading scans needs the version that runs on your computer"
        )
    if statement_kind == "credit_card":
        notes.append("Credit card statement")
    redacted_count = int(transactions["redacted"].sum()) if not transactions.empty else 0
    # Masked account numbers (XXXX1234) are normal; only blacked-out or "[REDACTED]" content counts.
    if redacted_count or extracted.image_redaction_boxes or re.search(r"redacted|█|■", full_text, re.IGNORECASE):
        notes.append(f"Redacted ({redacted_count} transactions affected)" if redacted_count else "Redacted")
    recovered = int(transactions["description"].str.contains("recovered from running balance", na=False).sum()) if not transactions.empty else 0
    if recovered:
        notes.append(f"{recovered} redacted amount{'s' if recovered != 1 else ''} recovered from the running balance")
    if extracted.has_leaky_redactions:
        notes.append(
            f"Black boxes on {extracted.hidden_lines} line{'s' if extracted.hidden_lines != 1 else ''} still had readable text "
            "underneath. The app hid it, but the PDF itself still contains it: don't share this file as redacted."
        )
    try:
        document_checks = check_document(file_bytes, transactions, full_text, extracted.ocr_pages)
    except Exception:  # the checks are advisory; never let them stop a statement from loading
        document_checks = []
    source = {"file": file_name, "bytes": len(file_bytes), "sha256": file_sha256, "pages": len(pages), "ocr_pages": extracted.ocr_pages}
    return ParseResult(transactions=transactions, flags=flags, raw_text=raw_text, notes=notes, document_checks=document_checks, source=source)
