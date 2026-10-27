"""
Bank reconciliation: one row per statement and account, checked against the statement's own
figures (running balance, printed control totals, or printed opening and closing balances).
"""

from __future__ import annotations

import pandas as pd

# Columns of the reconciliation table: one row per statement and account.
RECON_COLUMNS = [
    "statement_id",
    "account_number",
    "method",
    "statement_kind",
    "beginning_balance",
    "total_credits",
    "total_debits",
    "expected_ending_balance",
    "ending_balance",
    "reconciliation_difference",
    "printed_net",
    "printed_items",
    "items",
    "status",
    "notes",
]


def _first_number(frame: pd.DataFrame, column: str):
    """The first numeric value in a column, or None (statement-level figures repeat on every row)."""
    values = pd.to_numeric(frame.get(column, pd.Series(dtype=float)), errors="coerce").dropna()
    return float(values.iloc[0]) if not values.empty else None


def build_reconciliation_table(transactions: pd.DataFrame) -> pd.DataFrame:
    """
    Build one reconciliation row per statement and account, using the best evidence available:

    1. running balance: beginning + credits - debits must equal the last running balance;
    2. printed control totals ("10 Total Deposits : $8,337.98"), used when balances are
       missing or redacted: the net change and item count must agree;
    3. the statement's printed opening and closing balances (previous/new balance on a
       credit card) when the statement holds a single account.
    A difference within $0.01 is treated as reconciled.
    """
    if transactions.empty:
        return pd.DataFrame(columns=RECON_COLUMNS)
    rows = []
    accounts_per_statement = transactions.groupby("statement_id", dropna=False)["account_number"].nunique(dropna=False)
    # One row per account: a single PDF can hold several accounts (e.g. checking plus a credit line).
    for (statement_id, account_number), grp in transactions.groupby(["statement_id", "account_number"], dropna=False):
        # Preserve statement order: date, then PDF page/line position.
        ordered = grp.sort_values(["txn_date", "source_page", "source_line"]).copy()
        credits = float(pd.to_numeric(ordered["credit"], errors="coerce").fillna(0).sum())
        debits = float(pd.to_numeric(ordered["debit"], errors="coerce").fillna(0).sum())
        running = pd.to_numeric(ordered.get("running_balance"), errors="coerce").dropna()
        kind = str(ordered["statement_kind"].iloc[0]) if "statement_kind" in ordered and pd.notna(ordered["statement_kind"].iloc[0]) else "bank"
        row = {
            "statement_id": statement_id,
            "account_number": account_number,
            "method": None,
            "statement_kind": kind,
            "beginning_balance": None,
            "total_credits": credits,
            "total_debits": debits,
            "expected_ending_balance": None,
            "ending_balance": None,
            "reconciliation_difference": None,
            "printed_net": None,
            "printed_items": None,
            "items": len(ordered),
            "status": "Needs Review",
            "notes": "No running balance or printed totals found; manual reconciliation required.",
        }
        printed_credits = _first_number(ordered, "control_credit_total")
        printed_debits = _first_number(ordered, "control_debit_total")
        opening = _first_number(ordered, "statement_opening_balance")
        closing = _first_number(ordered, "statement_closing_balance")
        if not running.empty:
            # Opening balance: the first printed balance, less every transaction up to and including it
            # (some banks print a balance only on the last line of each day).
            net = (
                pd.to_numeric(ordered["credit"], errors="coerce").fillna(0)
                - pd.to_numeric(ordered["debit"], errors="coerce").fillna(0)
            ).cumsum()
            beginning = float(running.iloc[0]) - float(net.loc[running.index[0]])
            # Lines after the last printed balance can't be checked against it; carry them forward.
            ending = float(running.iloc[-1]) + float(net.iloc[-1] - net.loc[running.index[-1]])
            row.update(method="running_balance", beginning_balance=beginning, ending_balance=ending)
            row["expected_ending_balance"] = beginning + credits - debits
            row["reconciliation_difference"] = row["ending_balance"] - row["expected_ending_balance"]
            if abs(row["reconciliation_difference"]) <= 0.01:
                row.update(status="Reconciled", notes="Expected ending balance agrees to statement running balance.")
            else:
                row.update(status="Variance", notes="Expected ending balance differs from statement running balance.")
                # Checks listed only in a check summary never touch the register's running balance.
                unregistered_checks = ordered[(ordered["transaction_type"] == "check") & ordered["running_balance"].isna()]
                unregistered_total = float(pd.to_numeric(unregistered_checks["debit"], errors="coerce").fillna(0).sum())
                if unregistered_total and abs(row["reconciliation_difference"] - unregistered_total) <= 0.01:
                    row["notes"] = (
                        f"The difference equals the {len(unregistered_checks)} checks (${unregistered_total:,.2f}) listed in the "
                        "statement's check summary that don't appear in its transaction register. Trace these checks."
                    )
        elif printed_credits is not None or printed_debits is not None:
            # Banks differ on where reversals belong (a negative deposit vs. a withdrawal), so compare
            # the net change and the number of items rather than each side separately.
            printed_net = (printed_credits or 0.0) - (printed_debits or 0.0)
            counts = [_first_number(ordered, "control_credit_count"), _first_number(ordered, "control_debit_count")]
            printed_items = int(sum(c for c in counts if c is not None)) if any(c is not None for c in counts) else None
            difference = (credits - debits) - printed_net
            row.update(method="control_totals", printed_net=printed_net, printed_items=printed_items, reconciliation_difference=difference)
            items_ok = printed_items is None or printed_items == len(ordered)
            if abs(difference) <= 0.01 and items_ok:
                row.update(status="Reconciled", notes="Every transaction was read: the totals and item count agree with the totals printed on the statement.")
            elif abs(difference) <= 0.01:
                row.update(status="Variance", notes=f"Totals agree but the statement lists {printed_items} items and {len(ordered)} were read.")
            else:
                row.update(status="Variance", notes="The transactions read don't add up to the totals printed on the statement; some may be missing or misread.")
        elif opening is not None and closing is not None and accounts_per_statement.get(statement_id, 1) == 1:
            # A card balance rises with charges and falls with payments; a bank balance the other way round.
            expected = opening + debits - credits if kind == "credit_card" else opening + credits - debits
            row.update(method="summary_balance", beginning_balance=opening, ending_balance=closing, expected_ending_balance=expected)
            row["reconciliation_difference"] = closing - expected
            if abs(row["reconciliation_difference"]) <= 0.01:
                row.update(status="Reconciled", notes="Opening balance and the transactions read agree to the closing balance printed on the statement.")
            else:
                row.update(status="Variance", notes="The transactions read don't account for the change between the printed opening and closing balances.")
        rows.append(row)
    return pd.DataFrame(rows, columns=RECON_COLUMNS).sort_values(["statement_id", "account_number"]).reset_index(drop=True)
