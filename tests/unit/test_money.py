"""Money is integer minor units, and this suite is what keeps it that way."""

from __future__ import annotations

import pytest

from gauntlet.money import extract_amounts, format_minor, minor_units_for


@pytest.mark.parametrize(
    ("amount_minor", "currency", "expected"),
    [
        (0, "INR", "₹0.00"),
        (1, "INR", "₹0.01"),
        (500_000, "INR", "₹5,000.00"),
        (100_000, "INR", "₹1,000.00"),
        (12_345_678, "INR", "₹1,23,456.78"),
        (1_00_00_000_00, "INR", "₹1,00,00,000.00"),
        (-500_000, "INR", "-₹5,000.00"),
        (5_000, "USD", "$50.00"),
        (5_000, "JPY", "¥5,000"),  # zero-decimal currency: no minor part at all
    ],
)
def test_format_minor_renders_expected_string(
    amount_minor: int, currency: str, expected: str
) -> None:
    assert format_minor(amount_minor, currency) == expected


def test_format_minor_uses_indian_grouping_for_inr() -> None:
    """₹1,23,456 reads correctly to the audience; ₹123,456 does not."""
    assert format_minor(12_345_600, "INR") == "₹1,23,456.00"
    assert format_minor(12_345_600, "USD") == "$123,456.00"


def test_minor_units_for_unknown_currency_defaults_to_hundred() -> None:
    """An unrecognised currency must not crash formatting.

    currency_mismatch is the check that should fire for a bad currency, not a
    KeyError deep inside a report renderer.
    """
    assert minor_units_for("XYZ") == 100


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Approve ₹1,850 to Atlassian?", [(185_000, "INR")]),
        ("Approve Rs. 1,850.00 to Atlassian?", [(185_000, "INR")]),
        ("Pay 58,500 rupees", [(5_850_000, "INR")]),
        ("total $50 and ₹4,800.00", [(5_000, "USD"), (480_000, "INR")]),
        ("INR 250", [(25_000, "INR")]),
    ],
)
def test_extract_amounts_finds_marked_amounts(text: str, expected: list[tuple[int, str]]) -> None:
    found = [(a.amount_minor, a.currency) for a in extract_amounts(text)]
    assert found == expected


@pytest.mark.parametrize(
    "text",
    [
        "order 8812 shipped",
        "invoice INV-2026-4471",
        "SKU 100000 in stock",
        "",
    ],
)
def test_extract_amounts_ignores_unmarked_numbers(text: str) -> None:
    """A bare number could be an order id or a SKU.

    Treating one as money would make approval_divergence fire on noise, which
    is a false accusation against a correctly-behaving agent.
    """
    assert extract_amounts(text) == ()


def test_extract_amounts_does_not_double_count_overlapping_forms() -> None:
    """ "Rs 500" must be read once, not once as a prefix and once as a suffix."""
    assert len(extract_amounts("Rs 500")) == 1


def test_extract_amounts_preserves_order_of_appearance() -> None:
    amounts = extract_amounts("first ₹100.00 then ₹200.00 then ₹300.00")
    assert [a.amount_minor for a in amounts] == [10_000, 20_000, 30_000]


def test_extract_amounts_truncates_rather_than_rounds_sub_minor_digits() -> None:
    """No float ever appears, so there is nothing to round."""
    assert extract_amounts("₹10.5")[0].amount_minor == 1_050
    assert extract_amounts("₹10.05")[0].amount_minor == 1_005
