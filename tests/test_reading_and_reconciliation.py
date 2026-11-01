"""Statements are read completely and reconcile to their own printed figures."""

import pytest

from reconciliation import build_reconciliation_table

GENUINE = {
    "1_checking_2025-03.pdf": (15, "running_balance"),
    "2_checking_2025-04.pdf": (22, "running_balance"),
    "3_checking_2025-05.pdf": (21, "running_balance"),
    "4_credit_card_2025-05.pdf": (11, "summary_balance"),
    # The caregiver's accounts at two other banks: two amount columns, and sections with totals.
    "7_dp_companion_care_2025-04.pdf": (11, "running_balance"),
    "8_dp_companion_care_2025-05.pdf": (6, "running_balance"),
    "9_pruitt_personal_2025-04.pdf": (16, "control_totals"),
    "10_pruitt_personal_2025-05.pdf": (13, "control_totals"),
}


@pytest.mark.parametrize("name", list(GENUINE))
def test_demo_statements_read_and_reconcile(parse, name):
    """Each genuine demo statement is read completely and reconciles."""
    count, method = GENUINE[name]
    result = parse(name)
    assert len(result.transactions) == count
    recon = build_reconciliation_table(result.transactions)
    assert list(recon["status"]) == ["Reconciled"]
    assert list(recon["method"]) == [method]


def test_card_statement_is_recognized(parse):
    """The card statement is read with credit card conventions."""
    assert "Credit card statement" in parse("4_credit_card_2025-05.pdf").notes


def test_doctored_copy_does_not_reconcile(parse):
    """The doctored copy's broken balances show as a variance."""
    recon = build_reconciliation_table(parse("5_checking_2025-04_family_copy.pdf").transactions)
    assert list(recon["status"]) == ["Variance"]


def test_every_row_records_its_source_file(parse):
    """Every row names its source file, fingerprint, page and line."""
    result = parse("1_checking_2025-03.pdf")
    tx = result.transactions
    assert (tx["source_file"] == "1_checking_2025-03").all()
    assert tx["source_sha256"].nunique() == 1 and tx["source_sha256"].iloc[0] == result.source["sha256"]
    assert tx["source_page"].notna().all() and tx["source_line"].notna().all()
    assert result.source["pages"] == 1 and result.source["bytes"] > 0


@pytest.mark.slow
def test_scanned_redacted_copy_reconciles_with_ocr(parse):
    """The scanned, redacted copy is read with OCR and reconciles (skipped where OCR isn't installed)."""
    pytest.importorskip("rapidocr")
    result = parse("6_checking_2025-05_scanned_redacted.pdf")
    assert any(n.startswith("Scanned") for n in result.notes)
    assert len(result.transactions) == 21
    assert list(build_reconciliation_table(result.transactions)["status"]) == ["Reconciled"]


def test_account_inventory(parse):
    """Statements are grouped by account; overlapping copies, the redacted scan and the totals are handled."""
    from accounts import account_inventory, statement_list

    names = ["1_checking_2025-03.pdf", "2_checking_2025-04.pdf", "3_checking_2025-05.pdf", "4_credit_card_2025-05.pdf",
             "5_checking_2025-04_family_copy.pdf", "6_checking_2025-05_scanned_redacted.pdf",
             "7_dp_companion_care_2025-04.pdf", "8_dp_companion_care_2025-05.pdf",
             "9_pruitt_personal_2025-04.pdf", "10_pruitt_personal_2025-05.pdf", "11_wrenfield_repayment_proof_2025-05.pdf"]
    results = [parse(name) for name in names]
    import pandas as pd
    recon = build_reconciliation_table(pd.concat([r.transactions for r in results], ignore_index=True))
    statements = statement_list(results, names, recon)
    inventory = account_inventory(statements).set_index("account")
    assert list(inventory.index) == [
        "Larkspur Valley Bank · Checking ····8701", "Larkspur Valley Bank · Credit card ····7731",
        "Oxbow Prairie National Bank · Checking ····5520", "Quillbrook Credit Union · Checking ····3390",
        "Wrenfield Trust Bank · Deposit account ····4471",
    ]
    checking = inventory.loc["Larkspur Valley Bank · Checking ····8701"]
    assert checking["statements"] == 5 and checking["months_missing"] == "None"
    assert checking["transactions"] == 58  # March, April and May once each: the copies aren't counted twice
    assert "disagree" in checking["follow_up"] and "5_checking_2025-04_family_copy.pdf" in checking["follow_up"]
    assert "copies of one statement" in checking["follow_up"] and "Account number not shown" in checking["follow_up"]
    assert inventory.loc["Oxbow Prairie National Bank · Checking ····5520", "follow_up"] == "Nothing to follow up"
    assert "AI-generated" in inventory.loc["Wrenfield Trust Bank · Deposit account ····4471", "document_check"]


def test_inventory_finds_gaps_and_breaks(parse):
    """A missing month and a balance that doesn't carry forward are reported."""
    from accounts import account_inventory, statement_list

    names = ["1_checking_2025-03.pdf", "3_checking_2025-05.pdf"]
    statements = statement_list([parse(n) for n in names], names)
    row = account_inventory(statements).iloc[0]
    assert row["months_missing"] == "Apr 2025" and "request it from the bank" in row["follow_up"]
    # Without April the balances can't carry forward either, but a gap is reported as the gap, not a break.
    assert "closes at" not in row["follow_up"]


def test_inventory_reports_balance_that_does_not_carry_forward(parse):
    """With the family copy in place of April, May opens at a balance April never closed at."""
    from accounts import account_inventory, statement_list

    names = ["1_checking_2025-03.pdf", "5_checking_2025-04_family_copy.pdf", "3_checking_2025-05.pdf"]
    row = account_inventory(statement_list([parse(n) for n in names], names)).iloc[0]
    assert "5_checking_2025-04_family_copy.pdf closes at $13,763.86 but 3_checking_2025-05.pdf opens at $19,083.16" in row["follow_up"]
