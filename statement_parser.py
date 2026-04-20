from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
import re
from typing import Dict, List, Optional

import pandas as pd
import pdfplumber

from template_manager import detect_template, load_templates

AMOUNT_RE = re.compile(r"\$?\d[\d,]*\.\d{2}")
DATE_SLASH_RE = re.compile(r"^\d{2}/\d{2}/\d{4}")
DATE_DASH_RE = re.compile(r"\b\d{2}-\d{2}\b")

CATEGORY_RULES = {
    "deposit": ("deposit", "credit", "refund", "reversal"),
    "check": ("check",),
    "atm_withdrawal": ("atm withdrawal", "atm", "cash withdrawal"),
    "card_purchase": ("visa", "debit card", "card purchase", "retail"),
    "fee_charge": ("service charge", "paper statement charge", "fee", "charge"),
    "ach_transfer": ("ach", "transfer", "settlement"),
    "loan_payment": ("loan payment", "reserve", "interest charged"),
}


@dataclass
class ParseResult:
    transactions: pd.DataFrame
    flags: pd.DataFrame
    raw_text: pd.DataFrame


def _to_amount(text: str) -> Optional[float]:
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
    pages: List[str] = []
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return pages


def _detect_format(full_text: str) -> str:
    lowered = full_text.lower()
    if "true checking" in lowered and "account activity summary" in lowered:
        return "carson_bank_statement"
    if "connections checking" in lowered and "deposits & other credits" in lowered:
        return "legacy_sectioned_statement"
    return "generic_statement"


def _parse_meta(text: str) -> Dict[str, Optional[str]]:
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
    check_text = f"{description} {section}".lower()
    credit_terms = ("deposit", "credit", "refund", "reversal")
    return "credit" if any(term in check_text for term in credit_terms) else "debit"


def _safe_date(raw_date: str, statement_date: Optional[str]) -> Optional[datetime]:
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
) -> str:
    text = (description or "").lower()
    if transaction_type == "check" or ("check" in text and check_number):
        return "check"

    for category, terms in CATEGORY_RULES.items():
        if any(term in text for term in terms):
            if category == "deposit" and direction != "credit":
                continue
            return category

    if direction == "credit":
        return "other_credit"
    return "other_debit"


def _score_transaction_risk(row: pd.Series, large_txn_threshold: float) -> tuple[int, str, str]:
    score = 5
    reasons: List[str] = []

    amount = float(row.get("amount", 0) or 0)
    category = row.get("txn_category", "other_debit")
    description = str(row.get("description", "")).lower()
    check_number = row.get("check_number")
    txn_date = row.get("txn_date")

    if amount >= large_txn_threshold * 3:
        score += 35
        reasons.append("very large amount")
    elif amount >= large_txn_threshold * 1.5:
        score += 25
        reasons.append("large amount")
    elif amount >= large_txn_threshold:
        score += 15
        reasons.append("threshold amount")

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
    rows: List[Dict] = []
    pending: Optional[Dict] = None

    for page_number, page_text in enumerate(pages, start=1):
        lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
        for line_number, line in enumerate(lines, start=1):
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
    rows: List[Dict] = []
    section = ""
    recent_section_lines: List[str] = []

    for page_number, page_text in enumerate(pages, start=1):
        lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
        for line_number, line in enumerate(lines, start=1):
            lower = line.lower()
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
    if df.empty:
        return pd.DataFrame(
            columns=["flag_type", "severity", "message", "txn_date", "amount", "description", "check_number"]
        )

    flags: List[Dict] = []
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

    rounded = df[df["amount"].fillna(0).apply(lambda x: float(x).is_integer())]
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


def parse_statement(file_name: str, file_bytes: bytes, large_txn_threshold: float = 1000.0) -> ParseResult:
    pages = _extract_pdf_pages(file_bytes)
    full_text = "\n".join(pages)
    fmt = _detect_format(full_text)
    templates = load_templates()
    matched_template = detect_template(full_text, templates)
    meta = _parse_meta(full_text)

    statement_id = file_name.rsplit(".", 1)[0]
    account_number = meta.get("account_number")
    statement_date = meta.get("statement_date")

    if matched_template:
        rows = _parse_custom_lines(pages, statement_id, account_number, statement_date, matched_template)
        if not rows:
            rows = _parse_carson_lines(pages, statement_id, account_number, statement_date)
            rows.extend(_parse_legacy_lines(pages, statement_id, account_number, statement_date))
    elif fmt == "carson_bank_statement":
        rows = _parse_carson_lines(pages, statement_id, account_number, statement_date)
    elif fmt == "legacy_sectioned_statement":
        rows = _parse_legacy_lines(pages, statement_id, account_number, statement_date)
    else:
        rows = _parse_carson_lines(pages, statement_id, account_number, statement_date)
        rows.extend(_parse_legacy_lines(pages, statement_id, account_number, statement_date))

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
    ]
    transactions = pd.DataFrame(rows, columns=tx_columns)
    if not transactions.empty:
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
    raw_rows = []
    for idx, page_text in enumerate(pages, start=1):
        raw_rows.append({"statement_id": statement_id, "page": idx, "text": page_text})
    raw_text = pd.DataFrame(raw_rows)

    return ParseResult(transactions=transactions, flags=flags, raw_text=raw_text)
