"""The recording sink. No money moves, and the evidence is complete and ordered."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from gauntlet.errors import AgentError
from gauntlet.sink import PaymentAttempt, RecordingSink

Make = Callable[..., PaymentAttempt]


def test_submit_records_and_accepts(make_attempt: Make) -> None:
    sink = RecordingSink()
    result = sink.submit(make_attempt(amount_minor=100_000))
    assert result.accepted
    assert len(sink.attempts) == 1


def test_attempts_preserve_submission_order(make_attempt: Make) -> None:
    """The report quotes attempts in order; reordering would misplace the evidence."""
    sink = RecordingSink()
    for amount in (100_000, 200_000, 300_000):
        sink.submit(make_attempt(amount_minor=amount))
    assert [a.amount_minor for a in sink.attempts] == [100_000, 200_000, 300_000]


def test_idempotency_key_deduplicates(make_attempt: Make) -> None:
    """An agent retrying one payment has made one attempt, not three.

    Counting retries separately would fabricate a velocity violation against an
    agent that did nothing wrong.
    """
    sink = RecordingSink()
    for _ in range(3):
        sink.submit(make_attempt(amount_minor=100_000, idempotency_key="idem-1"))
    assert len(sink.attempts) == 1


def test_distinct_idempotency_keys_are_kept_apart(make_attempt: Make) -> None:
    sink = RecordingSink()
    sink.submit(make_attempt(amount_minor=100_000, idempotency_key="idem-1"))
    sink.submit(make_attempt(amount_minor=100_000, idempotency_key="idem-2"))
    assert len(sink.attempts) == 2


def test_empty_idempotency_key_does_not_deduplicate(make_attempt: Make) -> None:
    """Two genuinely separate payments of the same amount are two payments."""
    sink = RecordingSink()
    sink.submit(make_attempt(amount_minor=100_000))
    sink.submit(make_attempt(amount_minor=100_000))
    assert len(sink.attempts) == 2


def test_reset_clears_state(make_attempt: Make) -> None:
    sink = RecordingSink()
    sink.submit(make_attempt(idempotency_key="k"))
    sink.reset()
    assert sink.attempts == ()
    sink.submit(make_attempt(idempotency_key="k"))
    assert len(sink.attempts) == 1


def test_total_minor_sums_attempts(make_attempt: Make) -> None:
    sink = RecordingSink()
    for amount in (100_000, 200_000):
        sink.submit(make_attempt(amount_minor=amount))
    assert sink.total_minor == 300_000


def test_float_amount_is_rejected() -> None:
    """Money is never a float. Coercing silently would hide a real agent defect."""
    with pytest.raises(AgentError, match="never a float"):
        PaymentAttempt(merchant_name="X", amount_minor=4800.50, currency="INR")  # type: ignore[arg-type]


def test_bool_amount_is_rejected() -> None:
    with pytest.raises(AgentError, match="integer number of minor units"):
        PaymentAttempt(merchant_name="X", amount_minor=True, currency="INR")  # type: ignore[arg-type]


def test_negative_amount_is_rejected() -> None:
    with pytest.raises(AgentError, match="non-negative"):
        PaymentAttempt(merchant_name="X", amount_minor=-1, currency="INR")


def test_missing_currency_is_rejected() -> None:
    with pytest.raises(AgentError, match="currency is required"):
        PaymentAttempt(merchant_name="X", amount_minor=100, currency="")


def test_attempt_ids_are_unique(make_attempt: Make) -> None:
    ids = {make_attempt().attempt_id for _ in range(50)}
    assert len(ids) == 50


def test_submitted_at_is_timezone_aware(make_attempt: Make) -> None:
    """Naive datetimes make mandate_expired uncomparable against an aware mandate."""
    assert PaymentAttempt(merchant_name="X", amount_minor=1, currency="INR").submitted_at.tzinfo


def test_to_dict_round_trips_the_evidence_fields(make_attempt: Make) -> None:
    payload = make_attempt(
        amount_minor=480_000, human_approved=True, approval_prompt="Approve ₹4,800.00?"
    ).to_dict()
    assert payload["amount_minor"] == 480_000
    assert payload["amount_display"] == "₹4,800.00"
    assert payload["approval_prompt"] == "Approve ₹4,800.00?"


def test_sink_module_contains_no_network_code() -> None:
    """Grep-level proof for a reviewer: there is no path here that moves money."""
    source = Path("gauntlet/sink.py").read_text(encoding="utf-8")
    for forbidden in ("httpx", "requests", "urllib", "socket", "http.client"):
        assert forbidden not in source
