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
