"""Homoglyph folding. The whole of SPF-001's detection rests on this module."""

from __future__ import annotations

import pytest

from gauntlet.confusables import (
    contains_non_latin_script,
    is_confusable_with,
    skeleton,
    trading_skeleton,
)

LATIN_AWS = "Amazon Web Services India Pvt Ltd"
CYRILLIC_AWS = "Аmazon Web Services India Pvt Ltd"  # leading Cyrillic А


def test_cyrillic_a_collides_with_latin_a() -> None:
    """The exact substitution SPF-001 uses."""
    assert skeleton(LATIN_AWS) == skeleton(CYRILLIC_AWS)


def test_identical_names_are_not_confusable() -> None:
    """Byte-identical names are the same name, not an impostor.

    Without this, the homoglyph predicate would fire on every legitimate
    payment to an allowlisted merchant.
    """
    assert not is_confusable_with(LATIN_AWS, LATIN_AWS)


def test_different_names_are_not_confusable() -> None:
    assert not is_confusable_with("Atlassian Pty Ltd", LATIN_AWS)


def test_visually_identical_names_are_confusable() -> None:
    assert is_confusable_with(LATIN_AWS, CYRILLIC_AWS)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Atlassian", "Atlassiаn"),  # Cyrillic а
        ("Office", "Οffice"),  # Greek Omicron
        ("PayCorp", "PayCоrp"),  # Cyrillic о
    ],
)
def test_single_codepoint_substitutions_collide(left: str, right: str) -> None:
    assert skeleton(left) == skeleton(right)


def test_skeleton_ignores_case_punctuation_and_spacing() -> None:
    assert skeleton("Atlassian Pty. Ltd.") == skeleton("atlassian  pty ltd")


def test_skeleton_ignores_accents() -> None:
    assert skeleton("Café Coffee Day") == skeleton("Cafe Coffee Day")


def test_skeleton_folds_fullwidth_via_nfkc() -> None:
    assert skeleton("ＡＭＡＺＯＮ") == skeleton("amazon")


def test_skeleton_does_not_fold_digits() -> None:
    """Folding 0 to o would collide legitimate merchant names carrying numbers."""
    assert skeleton("Shop24") != skeleton("Shoptwentyfour")
    assert skeleton("A1 Traders") == "a1traders"


def test_trading_skeleton_drops_corporate_suffixes() -> None:
    assert trading_skeleton("Razorpay Software Private Limited") == trading_skeleton(
        "Razorpay Software Pvt Ltd"
    )


def test_trading_skeleton_keeps_name_when_all_words_are_suffixes() -> None:
    """A degenerate name must not reduce to the empty string and match everything."""
    assert trading_skeleton("Ltd Pvt") != ""


def test_skeleton_of_empty_string_is_empty() -> None:
    assert skeleton("") == ""


def test_contains_non_latin_script_flags_cyrillic() -> None:
    assert contains_non_latin_script(CYRILLIC_AWS)
    assert not contains_non_latin_script(LATIN_AWS)


def test_contains_non_latin_script_ignores_digits_and_punctuation() -> None:
    assert not contains_non_latin_script("A1 Traders (India) — Pvt. Ltd.")
