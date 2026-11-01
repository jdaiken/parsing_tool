"""The workpaper carries the evidence record, run details and case notes."""

import io
from datetime import datetime

import openpyxl
import pandas as pd

from workpaper_export import build_workpaper


def test_workpaper_has_evidence_and_run_details(parse):
    """
    The workpaper has the Evidence and Case_Log sheets, run details on the Summary, and source columns
    on every transaction.
    """
    result = parse("1_checking_2025-03.pdf")
    evidence = pd.DataFrame([{"File": "1_checking_2025-03.pdf", "SHA-256": result.source["sha256"]}])
    log = pd.DataFrame([{"time": "t", "event": "Statement added", "detail": "x"}])
    data = build_workpaper(
        result.transactions, result.flags, pd.DataFrame(), datetime.now().astimezone(), None, None,
        evidence, [("App version", "1.1.0"), ("Analyst", "J. Investigator")], log,
    )
    book = openpyxl.load_workbook(io.BytesIO(data))
    assert {"Summary", "Evidence", "Case_Log", "Transactions"} <= set(book.sheetnames)
    summary = {row[0].value: row[1].value for row in book["Summary"].iter_rows(min_row=2)}
    assert summary["App version"] == "1.1.0" and summary["Analyst"] == "J. Investigator"
    assert book["Evidence"]["B2"].value == result.source["sha256"]
    headers = [c.value for c in book["Transactions"][1]]
    assert {"source_file", "source_sha256", "source_page", "source_line"} <= set(headers)


def test_statements_by_account_workbook(parse):
    """The statements workbook has the inventory and a sheet per account, each statement opening and closing as printed."""
    from io import BytesIO

    from openpyxl import load_workbook

    from accounts import account_inventory, statement_list, statements_workbook

    names = ["1_checking_2025-03.pdf", "2_checking_2025-04.pdf", "4_credit_card_2025-05.pdf"]
    results = [parse(n) for n in names]
    tx = pd.concat([r.transactions for r in results], ignore_index=True)
    statements = statement_list(results, names)
    wb = load_workbook(BytesIO(statements_workbook(statements, account_inventory(statements), tx)))
    assert wb.sheetnames == ["Accounts", "1 Larkspur Checking 8701", "2 Larkspur Card 7731"]
    checking = wb["1 Larkspur Checking 8701"]
    labels = [row[1].value for row in checking.iter_rows(min_row=7)]
    assert labels.count("Opening balance (per statement)") == 2
    closing = [row for row in checking.iter_rows(min_row=7) if row[1].value == "Closing balance (per statement) and totals"]
    assert [row[5].value for row in closing] == [16760.41, 19083.16]
    # The running balance is a formula, so Excel recomputes it; the card's goes up with charges.
    assert str(checking["E9"].value).startswith("=IF(E8") and "+N(C9)-N(D9)" in checking["E9"].value
    assert "+N(D9)-N(C9)" in wb["2 Larkspur Card 7731"]["E9"].value
