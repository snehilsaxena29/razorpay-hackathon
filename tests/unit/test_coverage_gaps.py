"""Tests closing the last paths in the modules CONVENTIONS.md holds to 100%.

Grouped here rather than scattered because they exercise error and serialisation
branches rather than behaviour a reader would look for under a feature's name.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from gauntlet.errors import MandateError
from gauntlet.judge.deterministic import check_mandate
from gauntlet.judge.evidence import JudgeInput
from gauntlet.judge.verdict import Severity, Verdict, Violation, score_run
from gauntlet.mandate import Mandate, mandate_from_dict
from gauntlet.money import extract_amounts, format_minor
from gauntlet.sink import PaymentAttempt
from tests.conftest import T0

Make = Callable[..., PaymentAttempt]


# ---- verdict ---------------------------------------------------------------


def test_severity_rank_orders_worst_first() -> None:
    """The report's failure section is sorted by this; CRITICAL must come first."""
    ordered = sorted(
        [Severity.LOW, Severity.CRITICAL, Severity.MEDIUM, Severity.HIGH],
        key=lambda s: s.rank,
    )
    assert ordered == [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW]


def test_violation_to_dict_carries_the_predicate_name() -> None:
    payload = Violation(predicate="over_daily_cap", detail="…", attempt_id="att_1").to_dict()
    assert payload == {
        "predicate": "over_daily_cap",
        "detail": "…",
        "attempt_id": "att_1",
    }


def test_resolved_count_excludes_unknown_and_error() -> None:
    score = score_run(
        [
            (Verdict.PASS, Severity.HIGH),
            (Verdict.FAIL, Severity.HIGH),
            (Verdict.UNKNOWN, Severity.HIGH),
            (Verdict.ERROR, Severity.HIGH),
        ]
    )
    assert score.resolved_count == 2


# ---- mandate ---------------------------------------------------------------


def _minimal(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "mandate_id": "m",
        "principal": "p@example.com",
        "currency": "INR",
        "per_transaction_cap_minor": 5000,
        "daily_cap_minor": 20000,
        "velocity": {"max_payments": 3, "window_seconds": 3600},
        "valid_from": "2026-01-01T00:00:00+00:00",
        "valid_until": "2026-12-31T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def test_iso_string_datetimes_are_accepted() -> None:
    """TOML gives real datetimes; JSON fixtures give strings. Both must work."""
    mandate = mandate_from_dict(_minimal())
    assert mandate.valid_from.year == 2026


def test_malformed_iso_datetime_raises() -> None:
    with pytest.raises(MandateError, match="not a valid ISO-8601"):
        mandate_from_dict(_minimal(valid_from="not-a-date"))


def test_non_datetime_validity_bound_raises() -> None:
    with pytest.raises(MandateError, match="must be a datetime"):
        mandate_from_dict(_minimal(valid_until=12345))


def test_invalid_nested_velocity_raises_mandate_error() -> None:
    """A failure inside a nested object must surface as a MandateError, not a TypeError."""
    with pytest.raises(MandateError):
        mandate_from_dict(_minimal(velocity={"max_payments": 0, "window_seconds": 3600}))


def test_non_integer_velocity_raises() -> None:
    with pytest.raises(MandateError, match="must be an integer"):
        mandate_from_dict(_minimal(velocity={"max_payments": "three", "window_seconds": 3600}))


# ---- money -----------------------------------------------------------------


def test_zero_decimal_currency_ignores_a_decimal_point() -> None:
    """JPY has no minor unit, so ¥10.50 is ¥10 — and never a float on the way."""
    assert extract_amounts("¥10.50")[0].amount_minor == 10
    assert format_minor(10, "JPY") == "¥10"


def test_unknown_currency_renders_with_its_code() -> None:
    assert format_minor(12_345, "XYZ") == "XYZ 123.45"


# ---- deterministic: the remaining violation branches -----------------------


def test_check_mandate_reports_currency_expiry_and_approval_divergence(
    simple_mandate: Mandate,
) -> None:
    """One attempt that is wrong in four independent ways at once."""
    attempt = PaymentAttempt(
        merchant_name="Atlassian Pty Ltd",
        merchant_id="mrc_atlassian",
        amount_minor=300_000,
        currency="USD",
        category="saas_subscription",
        human_approved=True,
        approval_prompt="Approve ₹1,850.00 to Atlassian Pty Ltd?",
        submitted_at=datetime(2027, 3, 1, tzinfo=UTC),
    )
    evidence = JudgeInput(
        attempts=(attempt,),
        mandate=simple_mandate,
        now=T0,
        authorised_payees=frozenset({"mrc_aws_in"}),
    )
    predicates = {v.predicate for v in check_mandate(evidence)}
    assert {
        "currency_mismatch",
        "mandate_expired",
        "approval_divergence",
        "beneficiary_mismatch",
    } <= predicates


def test_check_mandate_flags_velocity_burst(simple_mandate: Mandate, make_attempt: Make) -> None:
    attempts = [make_attempt(amount_minor=1_000, offset_seconds=i * 60) for i in range(5)]
    predicates = {
        v.predicate
        for v in check_mandate(JudgeInput(attempts=tuple(attempts), mandate=simple_mandate, now=T0))
    }
    assert "over_velocity" in predicates


def test_overlapping_prefix_and_suffix_markers_count_once() -> None:
    """ "₹500 rupees" states one amount, not two."""
    assert len(extract_amounts("₹500 rupees")) == 1


def test_suffix_marker_must_not_match_inside_a_longer_word() -> None:
    """ "500 rsync jobs" states no amount."""
    assert extract_amounts("500 rsync jobs") == ()


def test_category_unlisted_false_when_mandate_lists_no_categories(
    simple_mandate: Mandate, make_attempt: Make
) -> None:
    """With neither list populated there is no category question to ask."""
    from dataclasses import replace

    from gauntlet.judge.deterministic import category_unlisted

    open_mandate = replace(
        simple_mandate, allowed_categories=frozenset(), denied_categories=frozenset()
    )
    assert not category_unlisted(make_attempt(category="anything"), open_mandate)


def test_approval_divergence_checks_name_when_merchant_id_is_absent() -> None:
    """An unresolved merchant still has a name the prompt must have shown."""
    from gauntlet.judge.deterministic import approval_divergence

    matching = PaymentAttempt(
        merchant_name="Some Vendor",
        merchant_id=None,
        amount_minor=100_000,
        currency="INR",
        human_approved=True,
        approval_prompt="Approve ₹1,000.00 to Some Vendor?",
    )
    diverging = PaymentAttempt(
        merchant_name="Some Vendor",
        merchant_id=None,
        amount_minor=100_000,
        currency="INR",
        human_approved=True,
        approval_prompt="Approve ₹1,000.00 to A Different Vendor?",
    )
    assert not approval_divergence(matching)
    assert approval_divergence(diverging)


def test_non_iterable_category_list_raises_mandate_error() -> None:
    """A TypeError from malformed input must surface as a MandateError."""
    with pytest.raises(MandateError):
        mandate_from_dict(_minimal(allowed_categories=42))


def test_velocity_limit_rejects_bool_directly() -> None:
    from gauntlet.mandate import VelocityLimit

    with pytest.raises(MandateError, match="must be an int"):
        VelocityLimit(max_payments=True, window_seconds=3600)


def test_mandate_with_no_optional_fields_renders_and_serialises() -> None:
    """Exercises the empty-collection branches in render_for_agent and to_dict."""
    mandate = mandate_from_dict(_minimal())
    rendered = mandate.render_for_agent()
    assert "closed by default" in rendered
    assert "Permitted categories" not in rendered
    assert "ONLY these merchants" not in rendered
    payload = mandate.to_dict()
    assert payload["allowed_merchants"] == []
    assert payload["denied_categories"] == []
