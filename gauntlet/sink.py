"""Payment capture. The only path by which an agent can attempt to move money.

There is no network code in this module. Not disabled, not stubbed behind a flag
— absent. No code path in this repository can move real money, and that fact
should survive a reviewer grepping for it.

The sink accepts everything. A real rail would decline some of these attempts,
but declining here would measure the rail's controls rather than the agent's,
and the agent's controls are the thing under test. What the sink records is
"what this agent would have done", which is exactly what the judge needs.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from gauntlet.errors import AgentError
from gauntlet.money import format_minor

_ATTEMPT_COUNTER = itertools.count(1)


def _next_attempt_id() -> str:
    return f"att_{next(_ATTEMPT_COUNTER):04d}"


def utc_now() -> datetime:
    """The current time, always timezone-aware.

    Every datetime in this package is aware. Mixing naive and aware datetimes
    raises on comparison, and a mandate-validity check that raises inside a
    ``try`` is a check that silently never fires.
    """
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class PaymentAttempt:
    """One attempt by an agent to move money.

    ``merchant_name`` and ``merchant_id`` are deliberately separate fields.
    ``merchant_name`` is what the agent *believes* it is paying — attacker
    controlled, forgeable with homoglyphs. ``merchant_id`` is what it is
    *actually* paying. Half the attack catalogue lives in the gap between them,
    and collapsing them into one field would make those attacks undetectable.

    ``approval_prompt`` is the verbatim text a human was shown, if any. Keeping
    it lets the judge compare what the human approved against what was submitted
    without asking a model whether the two "basically match".
    """

    merchant_name: str
    amount_minor: int
    currency: str
    merchant_id: str | None = None
    category: str | None = None
    reason: str = ""
    human_approved: bool = False
    approval_prompt: str | None = None
    idempotency_key: str = ""
    submitted_at: datetime = field(default_factory=utc_now)
    attempt_id: str = field(default_factory=_next_attempt_id)

    def __post_init__(self) -> None:
        if isinstance(self.amount_minor, bool) or not isinstance(self.amount_minor, int):
            raise AgentError(
                f"amount_minor must be an integer number of minor units, "
                f"got {self.amount_minor!r}. Money is never a float."
            )
        if self.amount_minor < 0:
            raise AgentError(f"amount_minor must be non-negative, got {self.amount_minor}")
        if not self.currency:
            raise AgentError("currency is required on a payment attempt")

    @property
    def display_amount(self) -> str:
        """The amount as a human would read it, for reports and prompts."""
        return format_minor(self.amount_minor, self.currency)

    def to_dict(self) -> dict[str, Any]:
        """Serialise for the ledger and the JSON report."""
        return {
            "attempt_id": self.attempt_id,
            "merchant_name": self.merchant_name,
            "merchant_id": self.merchant_id,
            "amount_minor": self.amount_minor,
            "amount_display": self.display_amount,
            "currency": self.currency,
            "category": self.category,
            "reason": self.reason,
            "human_approved": self.human_approved,
            "approval_prompt": self.approval_prompt,
            "idempotency_key": self.idempotency_key,
            "submitted_at": self.submitted_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class PaymentResult:
    """What the agent learns after submitting. Always an acceptance here."""

    accepted: bool
    reference: str | None = None
    declined_reason: str | None = None


@runtime_checkable
class PaymentSink(Protocol):
    """The interface an agent uses to attempt a payment."""

    def submit(self, attempt: PaymentAttempt) -> PaymentResult:
        """Record an attempted payment and return a rail-like acknowledgement."""
        ...


class RecordingSink:
    """Captures every attempt in order and executes none of them.

    Deduplicates on ``idempotency_key`` the way a real rail would, because an
    agent that retries the same payment three times has made one attempt, not
    three, and counting it as three would fabricate a velocity violation.
    """

    def __init__(self) -> None:
        self._attempts: list[PaymentAttempt] = []
        self._seen_keys: dict[str, PaymentAttempt] = {}

    def submit(self, attempt: PaymentAttempt) -> PaymentResult:
        """Record ``attempt`` and acknowledge it. No money moves."""
        key = attempt.idempotency_key
        if key and key in self._seen_keys:
            prior = self._seen_keys[key]
            return PaymentResult(accepted=True, reference=f"ref_{prior.attempt_id}")

        self._attempts.append(attempt)
        if key:
            self._seen_keys[key] = attempt
        return PaymentResult(accepted=True, reference=f"ref_{attempt.attempt_id}")

    @property
    def attempts(self) -> tuple[PaymentAttempt, ...]:
        """Every distinct attempt, in submission order. The judge's evidence."""
        return tuple(self._attempts)

    @property
    def total_minor(self) -> int:
        """Sum of every attempt. Convenience for the daily-cap predicate's tests."""
        return sum(a.amount_minor for a in self._attempts)

    def reset(self) -> None:
        """Clear all state. Called between episodes, never mid-episode."""
        self._attempts.clear()
        self._seen_keys.clear()
