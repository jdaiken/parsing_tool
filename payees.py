"""
Who a transaction was paid to (or received from), as a short, consistent name.

"ZELLE PAYMENT TO DANA PRUITT JPM99A1X2F", "CHECK 2043 DP COMPANION CARE LLC" and
"WIRE TRANSFER OUT DP COMPANION CARE LLC REF 88213" become "Dana Pruitt",
"Dp Companion Care" and "Dp Companion Care", so payments to the same person or
business group together across checks, transfers and cards.
"""

from __future__ import annotations

import re
from typing import List

# Channel wording in front of the counterparty's name.
_LEADING = re.compile(
    r"^(?:"
    r"(?:quickpay\s+with\s+)?zelle\s+(?:payment\s+)?(?:to|from)|venmo\s+(?:payment\s+)?(?:to|from)?|cash\s*app\s+(?:to|from)?|"
    r"paypal\s+(?:inst\s+xfer\s+)?(?:to|from)?|online\s+(?:banking\s+)?transfer\s+(?:to|from)|transfer\s+(?:to|from)|"
    r"wire\s+transfer\s+(?:out|in)?\s*(?:to|from)?|outgoing\s+wire\s+(?:to)?|incoming\s+wire\s+(?:from)?|"
    r"(?:share\s+)?draft|check(?:\s*#|\s+no\.?)?\s*\d*|card\s+purchase(?:\s+with\s+pin)?|cardpurchase|pos\s+(?:debit|purchase)?|"
    r"checkcard\s+\d{4}|debit\s+card(?:\s+purchase)?|purchase\s+authorized\s+on|recurring\s+payment|ach\s+(?:debit|credit)?|"
    r"payment\s+(?:to|from)|processed\s+check\s*-?"
    r")\s*",
    re.IGNORECASE,
)
_NOISE = [
    r"\[redacted\]", r"\(amount[^)]*\)", r"\bref(?:erence)?\s*#?:?\s*\S+", r"\bconf(?:irmation)?#?:?\s*\S+",
    r"\b(?:jpm|trn|id|ppd|ccd|web)\s*\w*\d\w*", r"\b(?:des|indn|co id):\S*", r"#\s*\d+", r"\btype:.*$", r"\bdata:.*$",
    r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", r"\b\w*\d\w*\b", r"\b(?:llc|inc|co|corp|ltd|na|n\.a\.)\b\.?",
]
_STOP = {"card", "the", "of", "us", "usa", "chk", "pos"}


def counterparty(description: str, category: str = "") -> str:
    """A short name for who was paid or who paid; groups ATM, fee and unlabelled lines."""
    text = str(description or "").strip()
    if category == "fee_charge" or re.search(r"\bfee\b", text, re.IGNORECASE):
        return "Fees"
    if re.search(r"cash advance", text, re.IGNORECASE):
        name = _clean(re.sub(r".*cash advance", "", text, flags=re.IGNORECASE))
        return f"Cash advance: {name}" if name else "Cash advance"
    if category == "atm_withdrawal" or re.search(r"\batm\b|cash withdrawal", text, re.IGNORECASE):
        if re.search(r"\bbranch\b|teller", text, re.IGNORECASE):
            return "Cash: branch withdrawal"
        place = re.search(r"\b(?:atm withdrawal|withdrawal)\b\s+(?:\S*\d\S*\s+)?(.*)", text, re.IGNORECASE)
        name = _clean(place.group(1)) if place else ""
        return f"Cash: {name}" if name else "Cash / ATM"
    account = re.search(r"transfer\s+(to|from)\s+(?:[a-z]+\s+)*?\.*(\d{4,})", text, re.IGNORECASE)
    if account:
        return f"Transfer {account.group(1).lower()} account ...{account.group(2)[-4:]}"
    # Leading dates and redaction marks hide the channel wording; strip them, then the wording itself.
    text = re.sub(r"^(?:\s*(?:\[redacted\]|\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s*)+", "", text, flags=re.IGNORECASE)
    for _ in range(3):  # "Draft [redacted] Processed Check - ...", "Online Transfer To Chk ..." stack prefixes
        text = _LEADING.sub("", text)
        text = re.sub(r"^(?:\s*(?:\[redacted\]|\d{1,2}/\d{1,2}(?:/\d{2,4})?|-)\s*)+", "", text, flags=re.IGNORECASE)
    name = _clean(text)
    if not name:
        return "Checks (payee not shown)" if category == "check" or re.search(r"check|draft", str(description), re.I) else "Unlabelled"
    return name


def _clean(text: str) -> str:
    for pattern in _NOISE:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    words: List[str] = [w for w in re.split(r"[\s\-*/,.]+", text) if w.isalpha() and w.lower() not in _STOP]
    # Up to three words, stopping before a lone letter or a two-letter state code at the end.
    kept: List[str] = []
    for word in words[:3]:
        if len(word) == 1 or (kept and len(word) == 2 and word.isupper()):
            break
        kept.append(word)
    return " ".join(kept).title()
