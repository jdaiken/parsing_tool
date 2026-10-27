"""Statements are read completely and reconcile to their own printed figures."""

import pytest

from reconciliation import build_reconciliation_table

GENUINE = {
    "1_checking_2025-03.pdf": (15, "running_balance"),
    "2_checking_2025-04.pdf": (22, "running_balance"),
    "3_checking_2025-05.pdf": (21, "running_balance"),
    "4_credit_card_2025-05.pdf": (11, "summary_balance"),
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
