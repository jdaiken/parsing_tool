"""
Fraud-pattern rules run over all uploaded statements together.

Each rule looks for a pattern forensic accountants and elder-financial-exploitation
investigators commonly review, explains in plain English what it found, and tags the
transactions involved so they rise in the risk score. A finding is a reason to look
closer, not a conclusion that fraud happened.

Patterns: gambling, cash just under the $10,000 reporting threshold (structuring),
money in and straight back out (pass-through), new payees receiving large amounts,
gift-card purchases, sudden jumps in cash withdrawals, a draining balance, overdraft
and returned-item fees, duplicate payments, round-dollar transfers and card cash advances.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import pandas as pd

from payees import counterparty

GAMBLING_RE = re.compile(
    r"casino|gaming|poker|lotter|lotto|sportsbook|draftkings|fanduel|betmgm|caesars|slots?\b|racetrack|\bbingo\b|\bkeno\b",
    re.IGNORECASE,
)
GIFT_CARD_RE = re.compile(
    r"gift\s*cards?|giftcard|vanilla|green\s*dot|google\s*\*?play|itunes|apple\.com/bill gift|steam\s*games|prepaid\s*card",
    re.IGNORECASE,
)
CASH_RE = re.compile(r"\batm\b|cash withdrawal|withdrawal.*branch|teller|cash advance", re.IGNORECASE)
CASH_DEPOSIT_RE = re.compile(r"cash deposit|atm cash deposit|deposit.*cash", re.IGNORECASE)
TRANSFER_RE = re.compile(r"zelle|venmo|cash\s*app|paypal|wire|transfer|quickpay", re.IGNORECASE)
OVERDRAFT_RE = re.compile(r"overdraft|\bnsf\b|insufficient funds|returned item", re.IGNORECASE)
SEVERITY_POINTS = {"high": 35, "medium": 20, "low": 8}
NOT_A_PAYEE = ("Fees", "Unlabelled", "Checks (payee not shown)")


@dataclass
class Finding:
    rule: str
    severity: str  # high | medium | low
    title: str
    detail: str
    account: str
    rows: List[int] = field(default_factory=list)  # indexes into the transactions table
    total: float = 0.0


def _money(value: float) -> str:
    return f"-${-value:,.2f}" if value < 0 else f"${value:,.2f}"


def _when(ts) -> str:
    return ts.strftime("%m/%d/%Y") if pd.notna(ts) else "undated"


def _prepare(transactions: pd.DataFrame) -> pd.DataFrame:
    df = transactions.copy()
    df["date"] = pd.to_datetime(df["txn_date"], errors="coerce")
    df["out"] = pd.to_numeric(df["debit"], errors="coerce").fillna(0.0)
    df["in"] = pd.to_numeric(df["credit"], errors="coerce").fillna(0.0)
    df["desc"] = df["description"].fillna("").astype(str)
    df["payee"] = [counterparty(d, c) for d, c in zip(df["desc"], df["txn_category"].fillna(""))]
    # One series per real account across monthly files: the account number when known.
    base = df["statement_id"].astype(str).str.split(" · ").str[0]
    df["series"] = df["account_number"].where(df["account_number"].notna() & (df["account_number"].astype(str) != ""), base).astype(str)
    df["is_cash_out"] = (df["out"] > 0) & (df["txn_category"].eq("atm_withdrawal") | df["desc"].str.contains(CASH_RE))
    df["is_cash_in"] = (df["in"] > 0) & df["desc"].str.contains(CASH_DEPOSIT_RE)
    return df


def find(transactions: pd.DataFrame) -> List[Finding]:
    """Run every rule; findings are sorted most severe first."""
    if transactions.empty:
        return []
    df = _prepare(transactions)
    findings: List[Finding] = []
    for series, grp in df.groupby("series", sort=False):
        grp = grp.sort_values(["date", "source_page", "source_line"])
        for rule in (_gambling, _structuring, _pass_through, _new_payees, _gift_cards, _cash_spike, _balance_drain,
                     _overdrafts, _duplicates, _round_transfers, _cash_advances):
            findings.extend(rule(grp, series))
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(findings, key=lambda f: (order[f.severity], -f.total))


def _gambling(g: pd.DataFrame, series: str) -> List[Finding]:
    hits = g[g["desc"].str.contains(GAMBLING_RE) & ((g["out"] > 0) | (g["in"] > 0))]
    if hits.empty:
        return []
    total = float(hits["out"].sum())
    weekend = int((hits["date"].dt.day_of_week >= 5).sum())
    places = ", ".join(sorted(set(hits["payee"].str.replace(r"^Cash(?: advance)?: ", "", regex=True))))
    detail = (f"{len(hits)} transactions totalling {_money(total)} at {places} between {_when(hits['date'].min())} and "
              f"{_when(hits['date'].max())}" + (f"; {weekend} on a weekend." if weekend else "."))
    return [Finding("gambling", "high" if total >= 1000 else "medium", "Gambling or casino activity", detail, series, list(hits.index), total)]


def _structuring(g: pd.DataFrame, series: str) -> List[Finding]:
    out: List[Finding] = []
    for kind, mask, column in (("withdrawals", g["is_cash_out"], "out"), ("deposits", g["is_cash_in"], "in")):
        cash = g[mask & (g[column] < 10000)]
        near = cash[cash[column] >= 8000]
        rows = set(near.index)
        # Several sizeable cash items within a week that add up to $10,000 or more, each under it
        # (small ATM withdrawals are left out so they don't pad the list).
        dated = cash[cash[column] >= 2000].dropna(subset=["date"])
        for i, row in dated.iterrows():
            window = dated[(dated["date"] >= row["date"]) & (dated["date"] <= row["date"] + pd.Timedelta(days=7))]
            if len(window) >= 2 and window[column].sum() >= 10000:
                rows.update(window.index)
        if rows:
            hit = g.loc[sorted(rows)]
            amounts = ", ".join(f"{_money(v)} on {_when(d)}" for v, d in zip(hit[column], hit["date"]))
            out.append(Finding(
                "structuring", "high", f"Cash {kind} kept just under $10,000",
                f"Cash {kind} of {amounts}. Banks report cash over $10,000; amounts kept just below it, or split across "
                f"days, are a classic sign of avoiding that report (structuring).",
                series, list(hit.index), float(hit[column].sum()),
            ))
    return out


def _pass_through(g: pd.DataFrame, series: str) -> List[Finding]:
    out: List[Finding] = []
    dated = g.dropna(subset=["date"])
    for i, row in dated[dated["in"] >= 5000].iterrows():
        later = dated[(dated["date"] >= row["date"]) & (dated["date"] <= row["date"] + pd.Timedelta(days=3)) & (dated["out"] > 0)]
        moved = float(later["out"].sum())
        if moved >= 0.5 * row["in"]:
            big = later.nlargest(3, "out")
            where = "; ".join(f"{_money(v)} to {p}" for v, p in zip(big["out"], big["payee"]))
            out.append(Finding(
                "pass_through", "high", "Money in and straight back out",
                f"{_money(row['in'])} arrived on {_when(row['date'])} ({row['desc'][:60]}) and {_money(moved)} "
                f"({moved / row['in']:.0%}) left within 3 days: {where}.",
                series, [i] + list(later.index), moved,
            ))
    return out


def _new_payees(g: pd.DataFrame, series: str) -> List[Finding]:
    dated = g.dropna(subset=["date"])
    if dated.empty or (dated["date"].max() - dated["date"].min()).days < 45:
        return []  # needs at least a month of history to know what is "new"
    baseline_end = dated["date"].min() + pd.Timedelta(days=30)
    out: List[Finding] = []
    paid = dated[(dated["out"] > 0) & ~dated["payee"].isin(NOT_A_PAYEE) & ~dated["payee"].str.startswith("Cash")]
    for payee, rows in paid.groupby("payee"):
        first = rows["date"].min()
        total = float(rows["out"].sum())
        if first > baseline_end and (total >= 1000 or len(rows) >= 3):
            channels = sorted({("check" if re.search(r"check|draft", d, re.I) else "Zelle" if re.search("zelle", d, re.I)
                               else "wire" if re.search("wire", d, re.I) else "card" if re.search("card|pos", d, re.I) else "transfer")
                              for d in rows["desc"]})
            out.append(Finding(
                "new_payee", "high" if total >= 2500 else "medium", f"New payee: {payee}",
                f"First paid on {_when(first)}, after the first month of history; {len(rows)} payments totalling "
                f"{_money(total)} by {', '.join(channels)}.",
                series, list(rows.index), total,
            ))
    return out


def _gift_cards(g: pd.DataFrame, series: str) -> List[Finding]:
    hits = g[g["desc"].str.contains(GIFT_CARD_RE) & (g["out"] > 0)]
    if hits.empty:
        return []
    total = float(hits["out"].sum())
    return [Finding(
        "gift_cards", "high" if total >= 500 else "medium", "Gift card purchases",
        f"{len(hits)} gift card purchases totalling {_money(total)} ({', '.join(sorted(set(hits['payee'])))}). "
        f"Scammers often have victims pay with gift cards.",
        series, list(hits.index), total,
    )]


def _cash_spike(g: pd.DataFrame, series: str) -> List[Finding]:
    dated = g.dropna(subset=["date"])
    if dated.empty:
        return []
    monthly = dated[dated["is_cash_out"]].groupby(dated["date"].dt.to_period("M"))["out"].sum()
    months = dated["date"].dt.to_period("M").drop_duplicates().sort_values()
    if len(months) < 2:
        return []
    first_month = months.iloc[0]
    baseline = float(monthly.get(first_month, 0.0))
    out: List[Finding] = []
    for month in months.iloc[1:]:
        amount = float(monthly.get(month, 0.0))
        if amount >= max(1000.0, 3 * baseline):
            rows = dated[dated["is_cash_out"] & (dated["date"].dt.to_period("M") == month)]
            out.append(Finding(
                "cash_spike", "high", f"Cash withdrawals jumped in {month.strftime('%B %Y')}",
                f"{_money(amount)} in cash withdrawals ({len(rows)} items), against {_money(baseline)} in "
                f"{first_month.strftime('%B %Y')}.",
                series, list(rows.index), amount,
            ))
    return out


def _balance_drain(g: pd.DataFrame, series: str) -> List[Finding]:
    balances = g.dropna(subset=["date"]).assign(balance=pd.to_numeric(g["running_balance"], errors="coerce")).dropna(subset=["balance"])
    if len(balances) < 4:
        return []
    start, end = float(balances["balance"].iloc[0]), float(balances["balance"].iloc[-1])
    peak = float(balances["balance"].max())
    if peak >= 1000 and end <= 0.5 * peak:
        when = balances["date"].iloc[balances["balance"].values.argmax()]
        return [Finding(
            "balance_drain", "high", "Account balance drained",
            f"The balance went from {_money(start)} to a high of {_money(peak)} on {_when(when)}, then fell to "
            f"{_money(end)} by {_when(balances['date'].iloc[-1])} ({(peak - end) / peak:.0%} of the peak).",
            series, [], peak - end,
        )]
    return []


def _overdrafts(g: pd.DataFrame, series: str) -> List[Finding]:
    hits = g[g["desc"].str.contains(OVERDRAFT_RE)]
    if hits.empty:
        return []
    return [Finding(
        "overdrafts", "medium", "Overdraft or returned-item fees",
        f"{len(hits)} overdraft / insufficient-funds fees totalling {_money(float(hits['out'].sum()))}, starting "
        f"{_when(hits['date'].min())}. New overdrafts on a previously healthy account are a common sign it is being drained.",
        series, list(hits.index), float(hits["out"].sum()),
    )]


def _duplicates(g: pd.DataFrame, series: str) -> List[Finding]:
    out: List[Finding] = []
    # Cash is left out: two same-size ATM withdrawals are normal, two same-size checks to one payee are not.
    paid = g[(g["out"] >= 100) & ~g["payee"].isin(NOT_A_PAYEE) & ~g["is_cash_out"]].dropna(subset=["date"])
    seen = set()
    for (payee, amount), rows in paid.groupby(["payee", "out"]):
        rows = rows.sort_values("date")
        for a, b in zip(rows.index[:-1], rows.index[1:]):
            if (rows.loc[b, "date"] - rows.loc[a, "date"]).days <= 3 and (a, b) not in seen:
                seen.add((a, b))
                out.append(Finding(
                    "duplicate_payment", "medium", f"Possible duplicate payment to {payee}",
                    f"{_money(amount)} paid on {_when(rows.loc[a, 'date'])} and again on {_when(rows.loc[b, 'date'])}.",
                    series, [a, b], float(amount),
                ))
    return out


def _round_transfers(g: pd.DataFrame, series: str) -> List[Finding]:
    hits = g[(g["out"] >= 500) & (g["out"] % 100 == 0) & g["desc"].str.contains(TRANSFER_RE)]
    if len(hits) < 2:
        return []
    who = ", ".join(sorted(set(hits["payee"])))
    return [Finding(
        "round_transfers", "low", "Round-dollar transfers",
        f"{len(hits)} transfers in exact hundreds totalling {_money(float(hits['out'].sum()))} ({who}).",
        series, list(hits.index), float(hits["out"].sum()),
    )]


def _cash_advances(g: pd.DataFrame, series: str) -> List[Finding]:
    hits = g[g["desc"].str.contains("cash advance", case=False) & (g["out"] > 0) & ~g["desc"].str.contains(r"\bfee\b", case=False)]
    if hits.empty:
        return []
    return [Finding(
        "cash_advances", "medium", "Credit card cash advances",
        f"{len(hits)} cash advances totalling {_money(float(hits['out'].sum()))}. Cash advances carry fees and "
        f"interest from day one and are unusual for most cardholders.",
        series, list(hits.index), float(hits["out"].sum()),
    )]


def apply(transactions: pd.DataFrame) -> Tuple[pd.DataFrame, List[Finding], pd.DataFrame]:
    """
    Run the rules and fold them into the transactions' risk scores and reasons.
    Returns (transactions, findings, flags) where flags uses the workpaper's flag columns.
    """
    findings = find(transactions)
    tx = transactions.copy()
    if tx.empty:
        return tx, findings, pd.DataFrame(columns=["flag_type", "severity", "message", "txn_date", "amount", "description", "check_number"])
    points: Dict[int, int] = {}
    reasons: Dict[int, List[str]] = {}
    for finding in findings:
        for row in finding.rows:
            points[row] = max(points.get(row, 0), 0) + SEVERITY_POINTS[finding.severity]
            reasons.setdefault(row, []).append(finding.title.split(":")[0].lower())
    for row, extra in points.items():
        score = min(100, int(tx.at[row, "risk_score"] or 0) + extra)
        tx.at[row, "risk_score"] = score
        tx.at[row, "risk_level"] = "high" if score >= 70 else "medium" if score >= 40 else "low"
        existing = [] if tx.at[row, "risk_reasons"] in (None, "baseline profile") else str(tx.at[row, "risk_reasons"]).split("; ")
        tx.at[row, "risk_reasons"] = "; ".join(dict.fromkeys(reasons[row] + existing))
    flags = pd.DataFrame(
        [
            {
                "flag_type": f.rule,
                "severity": f.severity,
                "message": f"{f.title}: {f.detail}",
                "txn_date": _when(transactions.loc[f.rows[0], "txn_date"]) if f.rows else "",
                "amount": f.total,
                "description": transactions.loc[f.rows[0], "description"] if f.rows else "",
                "check_number": None,
            }
            for f in findings
        ],
        columns=["flag_type", "severity", "message", "txn_date", "amount", "description", "check_number"],
    )
    return tx, findings, flags
