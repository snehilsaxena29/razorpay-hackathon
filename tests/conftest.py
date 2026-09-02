"""Shared fixtures. No test in this suite is permitted to touch the network."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from gauntlet.mandate import Mandate, Merchant, VelocityLimit, load_mandate
from gauntlet.sink import PaymentAttempt

REPO_ROOT = Path(__file__).resolve().parents[1]

#: A fixed instant every time-dependent test is anchored to. Verdicts must not
#: depend on when the suite was run.
T0 = datetime(2026, 9, 4, 10, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any outbound HTTP call raise.

    A safety tool whose tests quietly reach a live provider gives results that
    depend on someone else's uptime. If a test needs a model it uses a cassette
    or a fake client; if this fixture fires, that rule was broken.
    """
    import httpx

    def _forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("network access attempted in a test; use a fake or a cassette")

    monkeypatch.setattr(httpx.Client, "request", _forbidden)
    monkeypatch.setattr(httpx.Client, "send", _forbidden)


@pytest.fixture
def ops_mandate() -> Mandate:
    """The real shipped mandate, loaded from disk.

    Used deliberately rather than an inline fixture: if `mandates/ops_default.toml`
    stops being valid, the suite should fail rather than pass against a copy.
    """
    return load_mandate(REPO_ROOT / "mandates" / "ops_default.toml")


@pytest.fixture
def simple_mandate() -> Mandate:
    """A minimal mandate for boundary tests: ₹5,000 per txn, ₹20,000 per day."""
    return Mandate(
        mandate_id="mnd_test",
        principal="test@example.com",
        currency="INR",
        per_transaction_cap_minor=500_000,
        daily_cap_minor=2_000_000,
        velocity=VelocityLimit(max_payments=3, window_seconds=3600),
        allowed_categories=frozenset({"cloud_compute", "saas_subscription"}),
        denied_categories=frozenset({"gift_cards", "crypto"}),
        allowed_merchants=(
            Merchant("mrc_aws_in", "Amazon Web Services India Pvt Ltd"),
            Merchant("mrc_atlassian", "Atlassian Pty Ltd"),
        ),
        denied_merchant_ids=frozenset({"mrc_quickcash"}),
        requires_human_approval_above_minor=200_000,
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        valid_until=datetime(2026, 12, 31, tzinfo=UTC),
    )


@pytest.fixture
def make_attempt() -> Callable[..., PaymentAttempt]:
    """Build a payment attempt with sensible defaults.

    Goes through the real constructor so validation is exercised on every
    fixture-built object, per CONVENTIONS.md §6.
    """

    def _make(
        *,
        amount_minor: int = 100_000,
        merchant_name: str = "Amazon Web Services India Pvt Ltd",
        merchant_id: str | None = "mrc_aws_in",
        currency: str = "INR",
        category: str | None = "cloud_compute",
        offset_seconds: int = 0,
        **kwargs: Any,
    ) -> PaymentAttempt:
        return PaymentAttempt(
            merchant_name=merchant_name,
            merchant_id=merchant_id,
            amount_minor=amount_minor,
            currency=currency,
            category=category,
            submitted_at=T0 + timedelta(seconds=offset_seconds),
            **kwargs,
        )

    return _make
