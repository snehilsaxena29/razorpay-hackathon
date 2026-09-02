"""The bundle of facts a success criterion is evaluated against.

Separated from both the predicates and the attacks so that neither has to import
the other, and so a criterion's inputs are explicit. In particular ``now`` is
passed in rather than read from the clock: a verdict that depends on when it was
computed is not reproducible, and an irreproducible safety verdict is not worth
much.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from gauntlet.mandate import Mandate
from gauntlet.sink import PaymentAttempt


@dataclass(frozen=True, slots=True)
class JudgeInput:
    """Everything a criterion may look at, and nothing else.

    A criterion receives no access to the agent, the network, or the clock. It
    is a pure function of the evidence, which is what makes every verdict in
    this tool reproducible from the ledger alone.
    """

    attempts: tuple[PaymentAttempt, ...]
    mandate: Mandate
    now: datetime
    payment_authorised: bool = True
    authorised_payees: frozenset[str] = field(default_factory=frozenset)

    @property
    def has_attempts(self) -> bool:
        return bool(self.attempts)
