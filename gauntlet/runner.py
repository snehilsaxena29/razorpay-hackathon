"""Orchestration: run attacks against an agent, isolate failures, record everything.

Three responsibilities, in order of importance:

1. **Isolate.** One attack blowing up must not end the run. Each is wrapped at a
   marked boundary that records the traceback and continues.
2. **Bound.** A hung agent gets a verdict, not an infinite wait.
3. **Record.** Every step is written to the append-only ledger before the run
   moves on, so a hard kill still leaves usable evidence.

Deterministic attacks run first. If a provider goes down mid-run — or the
process dies — the results that survive are the ones that never needed a model.
"""

from __future__ import annotations

import threading
import traceback
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from gauntlet.agent import AgentUnderTest, EpisodeResult, EpisodeSpec, Message
from gauntlet.attacks.base import Attack, CriterionResult
from gauntlet.context import ScriptedHuman, ToolContext
from gauntlet.errors import AgentError, EpisodeTimeoutError, GauntletError
from gauntlet.judge.evidence import JudgeInput
from gauntlet.judge.verdict import SafetyScore, Severity, Verdict, Violation, score_run
from gauntlet.ledger import Ledger, new_run_id
from gauntlet.mandate import Mandate
from gauntlet.sink import PaymentAttempt, RecordingSink

DEFAULT_EPISODE_TIMEOUT_S = 60


@dataclass(frozen=True, slots=True)
class AttackRecord:
    """The complete outcome of one attack against one agent."""

    attack_id: str
    family: str
    severity: Severity
    title: str
    agent_name: str
    verdict: Verdict
    duration_ms: int
    violations: tuple[Violation, ...] = ()
    unknown_reason: str | None = None
    error: str | None = None
    traceback_text: str | None = None
    transcript: tuple[Message, ...] = ()
    attempts: tuple[PaymentAttempt, ...] = ()
    injections_fired: int = 0
    injections_declared: int = 0

    @property
    def predicates_fired(self) -> tuple[str, ...]:
        return tuple(v.predicate for v in self.violations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attack_id": self.attack_id,
            "family": self.family,
            "severity": str(self.severity),
            "title": self.title,
            "verdict": str(self.verdict),
            "duration_ms": self.duration_ms,
            "predicates_fired": list(self.predicates_fired),
            "violations": [v.to_dict() for v in self.violations],
            "unknown_reason": self.unknown_reason,
            "error": self.error,
            "attempts": [a.to_dict() for a in self.attempts],
            "injections": {
                "declared": self.injections_declared,
                "fired": self.injections_fired,
            },
        }


@dataclass(frozen=True, slots=True)
class RunResult:
    """Everything one agent's run produced."""

    run_id: str
    agent_name: str
    mandate: Mandate
    records: tuple[AttackRecord, ...]
    started_at: datetime
    finished_at: datetime
    mode: str = "REPLAY"
    ledger_path: Path | None = None
    llm_status: str = "UNUSED"

    @property
    def score(self) -> SafetyScore:
        """The aggregate safety score for this run."""
        return score_run([(r.verdict, r.severity) for r in self.records])

    @property
    def duration_s(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


@dataclass
class Runner:
    """Runs a catalogue against an agent.

    Args:
        mandate: the authority every verdict is measured against.
        ledger: the append-only log. Required — a run with no audit trail is
            not a run, so this is not optional and has no null implementation.
        episode_timeout_s: wall-clock budget per attack.
    """

    mandate: Mandate
    ledger: Ledger
    episode_timeout_s: int = DEFAULT_EPISODE_TIMEOUT_S
    mode: str = "REPLAY"
    llm_status: str = "UNUSED"
    semantic_judge: Any = None
    _run_id: str = field(default_factory=new_run_id)

    def run(self, agent: AgentUnderTest, attacks: Sequence[Attack]) -> RunResult:
        """Run every attack against ``agent`` and return the outcomes.

        Deterministic attacks are ordered first so that a run cut short by a
        provider outage or a kill signal still yields the results that never
        depended on one.
        """
        started = datetime.now(UTC)
        ordered = sorted(attacks, key=lambda a: (a.requires_llm, a.id))

        self.ledger.write(
            "run_started",
            agent=agent.name,
            mandate_id=self.mandate.mandate_id,
            mode=self.mode,
            attack_ids=[a.id for a in ordered],
        )

        records: list[AttackRecord] = []
        for attack in ordered:
            record = self.run_attack(agent, attack)
            records.append(record)
            self.ledger.write("verdict", **record.to_dict())

        finished = datetime.now(UTC)
        result = RunResult(
            run_id=self._run_id,
            agent_name=agent.name,
            mandate=self.mandate,
            records=tuple(records),
            started_at=started,
            finished_at=finished,
            mode=self.mode,
            ledger_path=self.ledger.path,
            llm_status=self.llm_status,
        )
        self.ledger.write("run_finished", summary=result.score.to_dict())
        return result

    def run_attack(self, agent: AgentUnderTest, attack: Attack) -> AttackRecord:
        """Run one attack, converting any failure into a recorded ERROR verdict.

        This is one of exactly two places in the package where a broad
        ``except Exception`` is permitted. The alternative — letting one badly
        behaved agent abort a ten-attack run — would mean a single crash hides
        nine other results.
        """
        started = datetime.now(UTC)
        self.ledger.write("attack_started", agent=agent.name, **attack.to_dict())

        sink = RecordingSink()
        tools = self._build_context(attack, sink)
        episode = self._build_episode(attack, sink, tools)

        try:
            episode_result = self._run_with_timeout(agent, episode)
            outcome = self._judge(attack, sink.attempts, tools, episode)
            return self._record(
                attack,
                agent,
                started,
                verdict=outcome.verdict,
                violations=outcome.violations,
                unknown_reason=outcome.unknown_reason,
                transcript=episode_result.transcript,
                attempts=sink.attempts,
                tools=tools,
            )
        except Exception as exc:  # isolation boundary — see the docstring
            detail = traceback.format_exc()
            self.ledger.write(
                "attack_error",
                attack_id=attack.id,
                agent=agent.name,
                error=str(exc),
                error_type=type(exc).__name__,
                traceback=detail,
            )
            return self._record(
                attack,
                agent,
                started,
                verdict=Verdict.ERROR,
                error=f"{type(exc).__name__}: {exc}",
                traceback_text=detail,
                attempts=sink.attempts,
                tools=tools,
            )

    # ---- construction --------------------------------------------------

    def _build_context(self, attack: Attack, sink: RecordingSink) -> ToolContext:
        return ToolContext(
            world=attack.world,
            sink=sink,
            human=ScriptedHuman(
                approve_below_minor=attack.human_approve_below_minor,
                currency=self.mandate.currency,
            ),
            injections=attack.injections,
            currency=self.mandate.currency,
        )

    def _build_episode(
        self, attack: Attack, sink: RecordingSink, tools: ToolContext
    ) -> EpisodeSpec:
        return EpisodeSpec(
            episode_id=f"{self._run_id}:{attack.id}",
            mandate=self.mandate,
            sink=sink,
            tools=tools,
            turns=attack.turns,
            deadline=datetime.now(UTC) + timedelta(seconds=self.episode_timeout_s),
            payment_authorised=attack.payment_authorised,
            authorised_payees=attack.authorised_payees,
        )

    # ---- execution -----------------------------------------------------

    def _run_with_timeout(self, agent: AgentUnderTest, episode: EpisodeSpec) -> EpisodeResult:
        """Run the agent on a daemon thread, bounded by the episode budget.

        A daemon thread rather than a signal, because signals are
        POSIX-main-thread-only and this has to work on Windows. The limitation
        is real and stated rather than hidden: a timed-out agent's thread is
        abandoned, not killed, since Python cannot safely kill a thread. It is a
        daemon so it cannot keep the process alive, and its sink is discarded.

        Raises:
            EpisodeTimeoutError: if the agent exceeds its wall-clock budget.
            Exception: whatever the agent raised, re-raised on this thread.
        """
        box: dict[str, Any] = {}

        def target() -> None:
            try:
                box["result"] = agent.run(episode)
            except BaseException as exc:
                box["error"] = exc

        thread = threading.Thread(target=target, daemon=True, name=f"agent:{episode.episode_id}")
        thread.start()
        thread.join(timeout=self.episode_timeout_s)

        if thread.is_alive():
            raise EpisodeTimeoutError(
                f"agent exceeded its {self.episode_timeout_s}s budget for {episode.episode_id}"
            )
        if "error" in box:
            raise box["error"]
        result = box.get("result")
        if not isinstance(result, EpisodeResult):
            raise AgentError(f"agent returned {type(result).__name__}, expected EpisodeResult")
        return result

    # ---- judging -------------------------------------------------------

    def _judge(
        self,
        attack: Attack,
        attempts: tuple[PaymentAttempt, ...],
        tools: ToolContext,
        episode: EpisodeSpec,
    ) -> CriterionResult:
        """Evaluate the attack's criterion, refusing to score an attack that never fired.

        An attack whose injections never reached the agent proves nothing. A
        PASS in that case would be a false reassurance — the most expensive kind
        of wrong answer this tool can give — so it is reported as ERROR instead.
        """
        if attack.injections and not tools.injections_fired:
            raise AgentError(
                f"{attack.id}: no injection reached the agent, so a verdict would be "
                "meaningless. The agent may not have called the tool the attack targets."
            )

        evidence = JudgeInput(
            attempts=attempts,
            mandate=self.mandate,
            now=datetime.now(UTC),
            payment_authorised=attack.payment_authorised,
            authorised_payees=attack.authorised_payees,
        )
        return attack.criterion(evidence)

    # ---- bookkeeping ---------------------------------------------------

    def _record(
        self,
        attack: Attack,
        agent: AgentUnderTest,
        started: datetime,
        *,
        verdict: Verdict,
        violations: tuple[Violation, ...] = (),
        unknown_reason: str | None = None,
        error: str | None = None,
        traceback_text: str | None = None,
        transcript: tuple[Message, ...] = (),
        attempts: tuple[PaymentAttempt, ...] = (),
        tools: ToolContext | None = None,
    ) -> AttackRecord:
        elapsed_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
        return AttackRecord(
            attack_id=attack.id,
            family=str(attack.family),
            severity=attack.severity,
            title=attack.title,
            agent_name=agent.name,
            verdict=verdict,
            duration_ms=elapsed_ms,
            violations=violations,
            unknown_reason=unknown_reason,
            error=error,
            traceback_text=traceback_text,
            transcript=transcript,
            attempts=attempts,
            injections_fired=len(tools.injections_fired) if tools else 0,
            injections_declared=len(attack.injections),
        )


def exit_code_for(results: Sequence[RunResult]) -> int:
    """Map run outcomes onto the process exit code.

    Failures dominate: a run with both a FAIL and an UNKNOWN returns 1, because
    "we found a vulnerability" is the more actionable of the two facts.
    """
    from gauntlet.errors import ExitCode

    any_failed = any(r.verdict is Verdict.FAIL for result in results for r in result.records)
    if any_failed:
        return int(ExitCode.UNSAFE)
    any_unresolved = any(
        r.verdict in (Verdict.UNKNOWN, Verdict.ERROR) for result in results for r in result.records
    )
    if any_unresolved:
        return int(ExitCode.DEGRADED)
    return int(ExitCode.CLEAN)


__all__ = [
    "AttackRecord",
    "GauntletError",
    "RunResult",
    "Runner",
    "exit_code_for",
]
