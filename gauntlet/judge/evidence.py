"""The bundle of facts a success criterion is evaluated against.

Separated from both the predicates and the attacks so that neither has to import
the other, and so a criterion's inputs are explicit. In particular ``now`` is
passed in rather than read from the clock: a verdict that depends on when it was
computed is not reproducible, and an irreproducible safety verdict is not worth
much.

:class:`SemanticVerdict` and :class:`CategoryJudge` live here rather than in
``judge.semantic`` for a layering reason. ``judge.deterministic`` needs to name
these types, and it must not — even transitively — import the provider layer.
Keeping the shapes here and the implementation there means the safety-critical
predicates cannot acquire a dependency on the network by accident.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from gauntlet.mandate import Mandate
from gauntlet.sink import PaymentAttempt

Outcome = Literal["WITHIN", "OUTSIDE", "UNKNOWN"]


@dataclass(frozen=True, slots=True)
class SemanticVerdict:
    """What a semantic judge concluded, and how much to trust it."""

    outcome: Outcome
    confidence: float
    rationale: str

    @property
    def is_resolved(self) -> bool:
        """Whether this answers the question. UNKNOWN does not."""
        return self.outcome != "UNKNOWN"

    @classmethod
    def unknown(cls, reason: str) -> SemanticVerdict:
        """Build an UNKNOWN verdict. The only way this type expresses failure."""
        return cls(outcome="UNKNOWN", confidence=0.0, rationale=reason)


@runtime_checkable
class CategoryJudge(Protocol):
    """The narrow slice of the semantic judge that a criterion may use.

    Deliberately one method. Widening this is how a harness ends up asking a
    model questions that arithmetic already answers.
    """

    @property
    def status(self) -> str:
        """Provider health: UP, DOWN, or UNUSED. Printed in every report header.

        Part of the interface rather than an implementation detail, because a
        reader has to be able to tell an agent that resisted everything from a
        run whose judge was never reachable.
        """
        ...

    def category_within_mandate(
        self,
        *,
        merchant_name: str,
        category: str | None,
        allowed_categories: frozenset[str],
        denied_categories: frozenset[str] = frozenset(),
    ) -> SemanticVerdict:
        """Whether this purchase falls inside a permitted category."""
        ...


@dataclass(frozen=True, slots=True)
class JudgeInput:
    """Everything a criterion may look at, and nothing else.

    A criterion receives no access to the agent, the network, or the clock. The
    one exception is ``semantic``, which is an explicit, single-method door to a
    language model — and it is ``None`` whenever no provider is configured,
    which is what makes a degraded run produce UNKNOWN rather than a guess.
    """

    attempts: tuple[PaymentAttempt, ...]
    mandate: Mandate
    now: datetime
    payment_authorised: bool = True
    authorised_payees: frozenset[str] = field(default_factory=frozenset)
    semantic: CategoryJudge | None = None

    @property
    def has_attempts(self) -> bool:
        return bool(self.attempts)
