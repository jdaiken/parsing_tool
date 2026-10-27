"""
Built-in directory of major US banks, credit unions and card issuers.

Used only to label a statement with its bank's name (when the name is printed
as text near the top of the statement) and to treat card-only issuers'
statements as credit card statements. It holds no layout rules: transactions
are read the same way for every bank.

Only the statement's header (before the first transaction) is searched, so a
bank named in a transaction ("Processed Check - CHASE") doesn't count.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

# name: display name; kind: "bank", "credit_union" or "card_issuer"; aliases: lowercase phrases
# that identify the institution on a statement (names, legal names, web addresses).
BANKS: List[Dict] = [
    {"name": "Chase", "kind": "bank", "aliases": ["jpmorgan chase", "chase.com", "chase bank", "chase sapphire", "chase freedom"]},
    {"name": "Bank of America", "kind": "bank", "aliases": ["bank of america", "bankofamerica.com"]},
    {"name": "Wells Fargo", "kind": "bank", "aliases": ["wells fargo", "wellsfargo.com"]},
    {"name": "Citibank", "kind": "bank", "aliases": ["citibank", "citi.com", "citicards", "citigroup"]},
    {"name": "U.S. Bank", "kind": "bank", "aliases": ["u.s. bank", "us bank national association", "usbank.com"]},
    {"name": "PNC Bank", "kind": "bank", "aliases": ["pnc bank", "pnc.com"]},
    {"name": "Truist", "kind": "bank", "aliases": ["truist", "suntrust", "bb&t"]},
    {"name": "Capital One", "kind": "bank", "aliases": ["capital one", "capitalone.com"]},
    {"name": "TD Bank", "kind": "bank", "aliases": ["td bank", "tdbank.com"]},
    {"name": "Fifth Third Bank", "kind": "bank", "aliases": ["fifth third", "53.com"]},
    {"name": "Citizens", "kind": "bank", "aliases": ["citizens bank", "citizensbank.com", "citizens financial"]},
    {"name": "KeyBank", "kind": "bank", "aliases": ["keybank", "key.com"]},
    {"name": "Huntington", "kind": "bank", "aliases": ["huntington national bank", "huntington.com"]},
    {"name": "M&T Bank", "kind": "bank", "aliases": ["m&t bank", "mtb.com", "manufacturers and traders"]},
    {"name": "Regions", "kind": "bank", "aliases": ["regions bank", "regions.com"]},
    {"name": "BMO", "kind": "bank", "aliases": ["bmo bank", "bmo harris", "bmo.com"]},
    {"name": "First Citizens Bank", "kind": "bank", "aliases": ["first citizens bank", "firstcitizens.com"]},
    {"name": "Santander", "kind": "bank", "aliases": ["santander bank", "santanderbank.com"]},
    {"name": "Comerica", "kind": "bank", "aliases": ["comerica"]},
    {"name": "Zions Bank", "kind": "bank", "aliases": ["zions bank", "zionsbank.com", "zions bancorporation"]},
    {"name": "Frost Bank", "kind": "bank", "aliases": ["frost bank", "frostbank.com"]},
    {"name": "Webster Bank", "kind": "bank", "aliases": ["webster bank", "websterbank.com"]},
    {"name": "Synovus", "kind": "bank", "aliases": ["synovus"]},
    {"name": "Associated Bank", "kind": "bank", "aliases": ["associated bank", "associatedbank.com"]},
    {"name": "Old National Bank", "kind": "bank", "aliases": ["old national bank", "oldnational.com"]},
    {"name": "Flagstar Bank", "kind": "bank", "aliases": ["flagstar bank", "flagstar.com"]},
    {"name": "East West Bank", "kind": "bank", "aliases": ["east west bank", "eastwestbank.com"]},
    {"name": "Cadence Bank", "kind": "bank", "aliases": ["cadence bank", "cadencebank.com"]},
    {"name": "Arvest Bank", "kind": "bank", "aliases": ["arvest bank", "arvest.com"]},
    {"name": "Commerce Bank", "kind": "bank", "aliases": ["commerce bank", "commercebank.com"]},
    {"name": "UMB Bank", "kind": "bank", "aliases": ["umb bank", "umb.com"]},
    {"name": "First Horizon", "kind": "bank", "aliases": ["first horizon", "firsthorizon.com"]},
    {"name": "Ally Bank", "kind": "bank", "aliases": ["ally bank", "ally.com"]},
    {"name": "Charles Schwab Bank", "kind": "bank", "aliases": ["charles schwab bank", "schwab bank", "schwab.com"]},
    {"name": "Discover", "kind": "bank", "aliases": ["discover bank", "discover card", "discover.com", "discover it"]},
    {"name": "Marcus by Goldman Sachs", "kind": "bank", "aliases": ["marcus by goldman sachs", "marcus.com"]},
    {"name": "SoFi", "kind": "bank", "aliases": ["sofi bank", "sofi.com"]},
    {"name": "Chime", "kind": "bank", "aliases": ["chime", "chime.com"]},
    {"name": "Varo Bank", "kind": "bank", "aliases": ["varo bank", "varomoney.com"]},
    {"name": "USAA", "kind": "bank", "aliases": ["usaa federal savings bank", "usaa.com"]},
    {"name": "Navy Federal Credit Union", "kind": "credit_union", "aliases": ["navy federal", "navyfederal.org"]},
    {"name": "PenFed Credit Union", "kind": "credit_union", "aliases": ["pentagon federal", "penfed"]},
    {"name": "BECU", "kind": "credit_union", "aliases": ["boeing employees credit union", "becu.org"]},
    {"name": "SchoolsFirst FCU", "kind": "credit_union", "aliases": ["schoolsfirst"]},
    {"name": "Golden 1 Credit Union", "kind": "credit_union", "aliases": ["golden 1 credit union", "golden1.com"]},
    {"name": "Alliant Credit Union", "kind": "credit_union", "aliases": ["alliant credit union", "alliantcreditunion.org"]},
    {"name": "America First Credit Union", "kind": "credit_union", "aliases": ["america first credit union", "americafirst.com"]},
    {"name": "Suncoast Credit Union", "kind": "credit_union", "aliases": ["suncoast credit union", "suncoastcreditunion.com"]},
    {"name": "Randolph-Brooks FCU", "kind": "credit_union", "aliases": ["randolph-brooks", "rbfcu.org"]},
    {"name": "Security Service FCU", "kind": "credit_union", "aliases": ["security service federal credit union", "ssfcu.org"]},
    {"name": "American Express", "kind": "card_issuer", "aliases": ["american express", "americanexpress.com", "amex"]},
    {"name": "Synchrony", "kind": "card_issuer", "aliases": ["synchrony bank", "synchrony.com", "mysynchrony"]},
    {"name": "Barclays", "kind": "card_issuer", "aliases": ["barclays bank delaware", "barclaysus.com", "barclays"]},
    {"name": "Apple Card", "kind": "card_issuer", "aliases": ["apple card", "goldman sachs bank usa"]},
    {"name": "Bread Financial", "kind": "card_issuer", "aliases": ["comenity", "bread financial"]},
    {"name": "Credit One Bank", "kind": "card_issuer", "aliases": ["credit one bank", "creditonebank.com"]},
    {"name": "First National Bank of Omaha", "kind": "card_issuer", "aliases": ["first national bank of omaha", "fnbo.com"]},
]

_KIND_LABELS = {"bank": "Bank", "credit_union": "Credit union", "card_issuer": "Credit cards"}

_FIRST_TRANSACTION = re.compile(r"^\s*\d{1,2}[/-]\d{1,2}\b.*\d\.\d{2}")


def _header(full_text: str, max_lines: int = 60) -> str:
    """The first page's lines before the first transaction line."""
    lines = []
    for line in full_text.splitlines()[:max_lines]:
        if _FIRST_TRANSACTION.match(line):
            break
        lines.append(line)
    return "\n".join(lines).lower()


def recognize_bank(full_text: str) -> Optional[Dict]:
    """The directory entry whose name appears in the statement header, preferring the longest match."""
    header = _header(full_text)
    best: Optional[Dict] = None
    best_length = 0
    for bank in BANKS:
        for alias in bank["aliases"]:
            if len(alias) > best_length and re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", header):
                best, best_length = bank, len(alias)
    return best


def directory_table() -> List[Dict]:
    """Rows for showing the directory in the app."""
    return [
        {"Bank": bank["name"], "Type": _KIND_LABELS[bank["kind"]]}
        for bank in sorted(BANKS, key=lambda b: b["name"])
    ]
