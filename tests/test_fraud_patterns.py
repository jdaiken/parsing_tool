"""Every fraud pattern planted in the demo case is found (demo/ANSWER_KEY.md)."""

import pandas as pd

import fraud_rules

CASE = ["1_checking_2025-03.pdf", "2_checking_2025-04.pdf", "3_checking_2025-05.pdf", "4_credit_card_2025-05.pdf"]


def _findings(parse):
    """Run the fraud rules over the four genuine demo statements together."""
    tx = pd.concat([parse(name).transactions for name in CASE], ignore_index=True)
    return fraud_rules.apply(tx)


def test_planted_patterns_are_found(parse):
    """Every pattern listed in demo/ANSWER_KEY.md is found."""
    _, findings, flags = _findings(parse)
    titles = {f.title for f in findings}
    for expected in (
        "Account balance drained",
        "Cash withdrawals kept just under $10,000",
        "New payee: Dp Companion Care",
        "New payee: Dana Pruitt",
        "Cash withdrawals jumped in April 2025",
        "Cash withdrawals jumped in May 2025",
        "Gambling or casino activity",
        "Gift card purchases",
        "Credit card cash advances",
        "Possible duplicate payment to Dp Companion Care",
        "Overdraft or returned-item fees",
        "Round-dollar transfers",
    ):
        assert expected in titles, expected
    assert len(flags) == len(findings)


def test_structuring_lists_only_the_large_cash_items(parse):
    """Structuring lists the four large cash withdrawals, not the small casino ATM withdrawals."""
    _, findings, _ = _findings(parse)
    structuring = next(f for f in findings if f.rule == "structuring")
    assert structuring.total == 9500 + 9800 + 9000 + 5080


def test_findings_raise_risk(parse):
    """Findings raise the risk of the transactions behind them."""
    tx, _, _ = _findings(parse)
    assert (tx["risk_level"] == "high").sum() >= 15


def test_march_alone_raises_no_high_findings(parse):
    """The normal month on its own raises nothing serious (no false alarms)."""
    findings = fraud_rules.find(parse("1_checking_2025-03.pdf").transactions)
    assert not [f for f in findings if f.severity == "high"]
