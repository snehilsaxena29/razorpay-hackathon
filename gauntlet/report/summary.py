"""Aggregation shared by the JSON and Markdown reports, and excerpt selection.

The excerpt logic is the most important thing in this package. A report that
says "the agent failed IDI-001" is an assertion. A report that shows the tool
result carrying the injection, the sentence where the agent decided to obey it,
and the payment that followed is evidence. Only the second one persuades anyone
to change their own agent.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from gauntlet.agent import Message, Role
from gauntlet.judge.verdict import Severity, Verdict
from gauntlet.runner import AttackRecord

#: Messages either side of the turning point to include in an excerpt. Two is
#: enough to show cause and effect and short enough that a reader will read it.
EXCERPT_RADIUS = 2


@dataclass(frozen=True, slots=True)
class FamilyBreakdown:
    """Per-family totals for the report's summary table."""

    family: str
    run: int
    passed: int
    failed: int
    unresolved: int
    worst_severity: Severity | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "run": self.run,
            "passed": self.passed,
            "failed": self.failed,
            "unresolved": self.unresolved,
            "worst_severity": str(self.worst_severity) if self.worst_severity else None,
        }


def family_breakdown(records: Sequence[AttackRecord]) -> tuple[FamilyBreakdown, ...]:
    """Group records by family, ordered by worst outcome first.

    Families where something failed sort above families where nothing did, so
    the first row of the table is the one worth reading.
    """
    families: dict[str, list[AttackRecord]] = {}
    for record in records:
        families.setdefault(record.family, []).append(record)

    rows = [
        FamilyBreakdown(
            family=family,
            run=len(group),
            passed=sum(1 for r in group if r.verdict is Verdict.PASS),
            failed=sum(1 for r in group if r.verdict is Verdict.FAIL),
            unresolved=sum(1 for r in group if r.verdict in (Verdict.UNKNOWN, Verdict.ERROR)),
            worst_severity=_worst_failed_severity(group),
        )
        for family, group in families.items()
    ]
    return tuple(sorted(rows, key=lambda r: (-r.failed, r.family)))


def _worst_failed_severity(records: Sequence[AttackRecord]) -> Severity | None:
    """The worst severity among *failed* attacks, or None if none failed."""
    failed = [r.severity for r in records if r.verdict is Verdict.FAIL]
    return min(failed, key=lambda s: s.rank) if failed else None


def sort_failures(records: Sequence[AttackRecord]) -> tuple[AttackRecord, ...]:
    """Failed attacks, worst severity first, then by id for stability."""
    return tuple(
        sorted(
            (r for r in records if r.verdict is Verdict.FAIL),
            key=lambda r: (r.severity.rank, r.attack_id),
        )
    )


def unresolved(records: Sequence[AttackRecord]) -> tuple[AttackRecord, ...]:
    """Attacks that produced no usable verdict. Never merged into the pass column."""
    return tuple(
        sorted(
            (r for r in records if r.verdict in (Verdict.UNKNOWN, Verdict.ERROR)),
            key=lambda r: r.attack_id,
        )
    )


def turning_point(transcript: Sequence[Message]) -> int | None:
    """Index of the message where the agent decided to make the payment.

    Prefers a message the agent itself flagged as acting on untrusted content,
    since that is the exact sentence worth quoting. Falls back to the first
    payment announcement, and then to the first untrusted tool result — an agent
    that never explained itself still read something before it acted.
    """
    for message in transcript:
        if message.role is Role.ASSISTANT and message.metadata.get("turned_here"):
            return message.index

    for message in transcript:
        if message.role is Role.ASSISTANT and message.content.lower().startswith("paying"):
            return message.index

    for message in transcript:
        if (
            message.role is Role.TOOL_RESULT
            and message.provenance is not None
            and message.provenance.is_untrusted
        ):
            return message.index

    return None


def excerpt(
    transcript: Sequence[Message], *, radius: int = EXCERPT_RADIUS
) -> tuple[tuple[Message, bool], ...]:
    """The window around the turning point, each message flagged if it *is* the point.

    Always includes the most recent untrusted tool result before the pivot, even
    when it falls outside the radius. That message is the *cause* — an excerpt
    showing an agent deciding to pay, without showing the text that told it to,
    documents the symptom and omits the evidence.

    Returns an empty tuple when there is no transcript or no identifiable
    turning point, which the renderers must handle rather than inventing one.
    """
    if not transcript:
        return ()
    pivot = turning_point(transcript)
    if pivot is None:
        return ()

    start = max(0, pivot - radius)
    end = min(len(transcript), pivot + radius + 1)
    indices = set(range(start, end))

    cause = _cause_index(transcript, pivot)
    if cause is not None:
        indices.add(cause)

    return tuple((transcript[i], i == pivot) for i in sorted(indices))


def _cause_index(transcript: Sequence[Message], pivot: int) -> int | None:
    """Index of the message that caused the turn.

    Prefers the index the agent itself recorded — an agent knows which tool
    result it acted on, and asking it is more reliable than inferring it from
    proximity. Falls back to the nearest preceding untrusted tool result for
    agents that do not report one, which is a guess and is only used as such.
    """
    declared = transcript[pivot].metadata.get("source_index")
    if isinstance(declared, int) and 0 <= declared < len(transcript):
        return declared

    for i in range(min(pivot, len(transcript) - 1), -1, -1):
        message = transcript[i]
        if (
            message.role is Role.TOOL_RESULT
            and message.provenance is not None
            and message.provenance.is_untrusted
        ):
            return i
    return None


def truncate(text: str, limit: int = 400) -> str:
    """Shorten text for a report, marking that it was shortened.

    Injected payloads and page bodies run long. Silently cutting them would let
    a reader think they had seen the whole thing.
    """
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rstrip() + f" … [{len(collapsed) - limit} more characters]"


def truncate_middle(text: str, *, head: int = 180, tail: int = 420) -> str:
    """Shorten from the middle, keeping both ends.

    Used for tool results in an excerpt. An appended injection lands at the
    *end* of the content it was spliced into, so head-only truncation cuts off
    the payload and leaves an excerpt that shows a benign page next to an agent
    inexplicably deciding to spend money. The evidence is in the tail.
    """
    collapsed = " ".join(text.split())
    if len(collapsed) <= head + tail:
        return collapsed
    omitted = len(collapsed) - head - tail
    return f"{collapsed[:head].rstrip()} … [{omitted} characters omitted] … {collapsed[-tail:].lstrip()}"
