"""
Builds statements/Statements_by_Account.xlsx: every Hartwell statement, read by the analyzer and laid out by account.

The workbook is what the app's "Statements by account" download gives for these files: an Accounts sheet (the
inventory) and a sheet per account with each statement's transactions and a running balance worked out by formula.
Here each account also carries its holder, from the inventory in make_case_pack.py.

Run from the repository root after make_demo_case.py and make_case_pack.py (needs the app's requirements):
    python demo/make_statements_workbook.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from accounts import account_inventory, statement_list, statements_workbook  # noqa: E402
from make_case_pack import INVENTORY, STATEMENTS  # noqa: E402
from reconciliation import build_reconciliation_table  # noqa: E402
from statement_parser import parse_statement  # noqa: E402

OUT = STATEMENTS / "Statements_by_Account.xlsx"


def main() -> None:
    """Read every statement in statements/, then write the workbook."""
    paths = sorted(STATEMENTS.glob("*/*.pdf"), key=lambda p: int(p.name.split("_")[0]))
    results = [parse_statement(p.name, p.read_bytes()) for p in paths]
    transactions = pd.concat([r.transactions for r in results if not r.transactions.empty], ignore_index=True)
    statements = statement_list(results, [p.name for p in paths], build_reconciliation_table(transactions))
    inventory = account_inventory(statements)
    # The holder isn't printed in a form the reader picks up, so it comes from the inventory, by folder.
    holder_of_folder = {folder: holder for folder, holder, *_ in INVENTORY}
    folder_of_file = {p.name: p.parent.name for p in paths}
    holders = {row["account"]: holder_of_folder.get(folder_of_file[row["file"]], "") for _, row in statements.iterrows()}
    OUT.write_bytes(statements_workbook(statements, inventory, transactions, holders, title="The Hartwell case: statements by account"))
    print(f"wrote {OUT.relative_to(ROOT)}: {len(inventory)} accounts, {len(statements)} statements, {len(transactions)} transactions")


if __name__ == "__main__":
    main()
