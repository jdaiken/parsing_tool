"""The doctored family copy shows every planted sign of editing; genuine statements show none."""

import pytest

from authenticity import WARN, verdict


@pytest.mark.parametrize("name", ["1_checking_2025-03.pdf", "2_checking_2025-04.pdf", "3_checking_2025-05.pdf", "4_credit_card_2025-05.pdf"])
def test_genuine_statements_are_clean(parse, name):
    """The genuine demo statements raise no warnings."""
    checks = parse(name).document_checks
    assert verdict(checks)[0] == "clean", [c.name for c in checks if c.status == WARN]


def test_family_copy_shows_all_nine_planted_edits(parse):
    """Exactly the nine edits planted in the family copy are reported, with the lines involved."""
    checks = parse("5_checking_2025-04_family_copy.pdf").document_checks
    warned = {c.name for c in checks if c.status == WARN}
    assert warned == {
        "Software that made the PDF",
        "Saved again after it was created",
        "Fonts on transaction lines",
        "Dates inside the statement period",
        "Transactions in date order",
        "Descriptions match money in and out",
        "Running balances add up",
        "Summary agrees with the transactions",
        "Amounts formatted consistently",
    }
    assert verdict(checks)[0] == "altered"
    examples = " ".join(e for c in checks for e in c.examples)
    assert "ZELLE PAYMENT FROM DANA PRUITT" in examples and "05/02" in examples


@pytest.mark.parametrize("name", ["7_dp_companion_care_2025-04.pdf", "8_dp_companion_care_2025-05.pdf",
                                  "9_pruitt_personal_2025-04.pdf", "10_pruitt_personal_2025-05.pdf"])
def test_other_banks_statements_are_clean(parse, name):
    """The subpoenaed statements from the two other banks raise no warnings, including the sectioned layout."""
    checks = parse(name).document_checks
    assert verdict(checks)[0] == "clean", [c.name for c in checks if c.status == WARN]


def test_ai_generated_statement_is_reported(parse):
    """The Wrenfield "proof of repayment" is reported as possibly AI-generated, with each planted sign."""
    checks = parse("11_wrenfield_repayment_proof_2025-05.pdf").document_checks
    level, headline = verdict(checks)
    assert level == "generated" and "AI-generated" in headline
    fabricated = {c.name for c in checks if c.status == WARN and c.fabrication}
    assert fabricated == {"Software that made the PDF", "Text left by an AI tool", "Dates that exist", "Routing number"}
    warned = {c.name for c in checks if c.status == WARN}
    assert {"Page numbers match the file", "Running balances add up"} <= warned
    examples = " ".join(e for c in checks for e in c.examples)
    assert "06/31/2025" in examples and "**Account Summary**" in examples


def test_fabrication_helpers():
    """Impossible dates and routing check digits, on their own."""
    from authenticity import _impossible_dates, _valid_routing

    assert _impossible_dates("Statement Date: 06/31/2025, posted 02/29/2025, April 31, 2025") == ["06/31/2025", "02/29/2025", "April 31, 2025"]
    assert _impossible_dates("02/29/2024 and 24/7 service and 12/31") == []
    assert _impossible_dates("31/04/2025 and 04/31/2025") == []  # day-first statements are left to the date checks
    assert _valid_routing("011000015") and not _valid_routing("073905528") and not _valid_routing("111111111")
