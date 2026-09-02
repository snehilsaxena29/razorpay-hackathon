"""The interface an agent must satisfy to be testable, and the episode it runs.

One method. Anything implementing :class:`AgentUnderTest` can be attacked by
this harness, including a third-party agent behind an HTTP adapter. The protocol
is structural, so conforming requires no import from us.

The agent never receives the :class:`~gauntlet.mandate.Mandate` object it is
judged against — only a rendered summary. Handing it the object would let a
successful injection rewrite the thing measuring it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from gauntlet.context import Provenance, ToolContext
from gauntlet.mandate import Mandate
from gauntlet.sink import PaymentAttempt, PaymentSink


class Role(StrEnum):
    """Who produced a transcript message."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"


@dataclass(frozen=True, slots=True)
class Message:
    """One entry in an episode transcript.

    The transcript is the evidence a report is built from. A thin transcript
    produces a failure section that asserts the agent went wrong without showing
    where, which is worth very little to someone deciding whether to trust their
    own agent.
    """

    index: int
    role: Role
    content: str
    provenance: Provenance | None = None
    tool: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise for the ledger and the JSON report."""
        payload: dict[str, Any] = {
            "i": self.index,
            "role": str(self.role),
            "content": self.content,
        }
        if self.provenance is not None:
            payload["provenance"] = str(self.provenance)
        if self.tool is not None:
            payload["tool"] = self.tool
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class EpisodeSpec:
    """Everything an agent is given for one attack run.

    ``payment_authorised`` is what makes IDI-001 judgeable: when the principal
    asked only for research, *any* payment attempt is a violation regardless of
    amount, merchant, or category. Without this field that attack would have no
    success criterion that did not require a model's opinion.
    """

    episode_id: str
    mandate: Mandate
    sink: PaymentSink
    tools: ToolContext
    turns: tuple[str, ...]
    deadline: datetime
    payment_authorised: bool = True
    authorised_payees: frozenset[str] = field(default_factory=frozenset)

    @property
    def system_preamble(self) -> str:
        """The mandate as the agent sees it: read-only text, never the object."""
        return self.mandate.render_for_agent()


@dataclass(frozen=True, slots=True)
class EpisodeResult:
    """What an agent produced. ``attempts`` is what the judge actually reads."""

    transcript: tuple[Message, ...]
    attempts: tuple[PaymentAttempt, ...]
    completed: bool = True
    error: str | None = None

    @classmethod
    def failed(cls, transcript: Sequence[Message], error: str) -> EpisodeResult:
        """Build a result for an episode that did not finish.

        Keeps whatever transcript exists: a partial transcript is still the best
        available evidence for why the agent broke.
        """
        return cls(
            transcript=tuple(transcript),
            attempts=(),
            completed=False,
            error=error,
        )


@runtime_checkable
class AgentUnderTest(Protocol):
    """Any payment-capable agent the harness can attack.

    Implementations must:

    - source every fact about the world from ``episode.tools``. An agent that
      reaches the network directly cannot be attacked, and therefore cannot be
      tested by this harness.
    - route every payment through ``episode.tools.pay`` or ``episode.sink``.
    - return a transcript rich enough to show *where* a decision was made.
    """

    name: str

    def run(self, episode: EpisodeSpec) -> EpisodeResult:
        """Execute one episode and return the transcript and attempts."""
        ...


class TranscriptBuilder:
    """Accumulates messages with correct indices.

    Shared by both reference agents and available to adapters, because
    hand-managing an index counter is the kind of detail that goes wrong quietly
    and then misaligns every excerpt in the report.
    """

    def __init__(self) -> None:
        self._messages: list[Message] = []

    def add(
        self,
        role: Role,
        content: str,
        *,
        provenance: Provenance | None = None,
        tool: str | None = None,
        **metadata: Any,
    ) -> Message:
        """Append a message and return it."""
        message = Message(
            index=len(self._messages),
            role=role,
            content=content,
            provenance=provenance,
            tool=tool,
            metadata=metadata,
        )
        self._messages.append(message)
        return message

    @property
    def messages(self) -> tuple[Message, ...]:
        return tuple(self._messages)

    def __len__(self) -> int:
        return len(self._messages)
