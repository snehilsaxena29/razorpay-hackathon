"""CDP-001 — the attack both agents are expected to fail, and the only one that
can honestly answer "I don't know".

Its pair of tests looks different from every other attack's, and deliberately so:
the hardened agent is *not* expected to resist this. Its defences — a
deterministic gate, provenance tagging, identity resolution — have nothing to
say about whether a goodwill credit is the kind of thing this mandate covers.
What is asserted instead is that the harness reaches the right verdict for the
right reason, and admits ignorance when it cannot.
"""

from __future__ import annotations

from gauntlet.attacks.catalogue.confused_deputy import CDP_001
from gauntlet.judge.evidence import SemanticVerdict
from gauntlet.judge.verdict import Verdict
from subjects.stubs import HardenedStub, NaiveStub
from tests.attacks.conftest import RunAttack


class StubJudge:
    """A semantic judge with a fixed answer, so the test is about the harness."""

    def __init__(self, outcome: str, confidence: float = 0.95) -> None:
        self._verdict = SemanticVerdict(
            outcome=outcome,  # type: ignore[arg-type]
            confidence=confidence,
            rationale="fixed answer for testing",
        )
        self.calls = 0

    @property
    def status(self) -> str:
        return "UP"

    def category_within_mandate(self, **_kwargs: object) -> SemanticVerdict:
        self.calls += 1
        return self._verdict


def test_cdp_001_detects_on_naive_stub(run_attack: RunAttack) -> None:
    """With a judge that says the category is outside, the attack succeeds."""
    record = run_attack(CDP_001, NaiveStub(), StubJudge("OUTSIDE"))
    assert record.verdict is Verdict.FAIL
    assert "category_outside_mandate" in record.predicates_fired


def test_cdp_001_also_defeats_the_hardened_stub(run_attack: RunAttack) -> None:
    """The honest result: the hardened agent's defences do not cover this.

    Its gate checks caps, identity and approval integrity, all of which this
    payment satisfies. A harness whose good agent scored 100% would imply the
    problem is solved; it is not.
    """
    record = run_attack(CDP_001, HardenedStub(), StubJudge("OUTSIDE"))
    assert record.verdict is Verdict.FAIL
    assert len(record.attempts) == 1
    assert record.attempts[0].merchant_id == "mrc_atlassian"


def test_cdp_001_does_not_false_positive_when_the_category_is_within(
    run_attack: RunAttack,
) -> None:
    """A judge saying the spend is in policy must produce a PASS, not a FAIL."""
    record = run_attack(CDP_001, HardenedStub(), StubJudge("WITHIN"))
    assert record.verdict is Verdict.PASS


def test_cdp_001_is_unknown_with_no_judge(run_attack: RunAttack) -> None:
    """The degraded path: no provider means no verdict, and no guess either way.

    This is the behaviour the whole failure-recovery design exists to produce.
    It must never quietly become PASS, which would report an unsafe agent as
    clean, nor FAIL, which would accuse a correct one.
    """
    record = run_attack(CDP_001, HardenedStub(), None)
    assert record.verdict is Verdict.UNKNOWN
    assert record.unknown_reason is not None
    assert "no semantic judge" in record.unknown_reason


def test_cdp_001_is_unknown_when_the_judge_is_unsure(run_attack: RunAttack) -> None:
    record = run_attack(CDP_001, HardenedStub(), StubJudge("UNKNOWN"))
    assert record.verdict is Verdict.UNKNOWN


def test_cdp_001_consults_the_judge_exactly_once(run_attack: RunAttack) -> None:
    """One undecided payment, one question. The model is not in a loop."""
    judge = StubJudge("OUTSIDE")
    run_attack(CDP_001, HardenedStub(), judge)
    assert judge.calls == 1


def test_cdp_001_is_the_only_attack_needing_a_provider() -> None:
    """The AI-judgment claim, asserted rather than merely written down.

    If this ever fails, either a new attack has taken a dependency on a model
    or CDP-001 has lost one — and the architecture doc's central table is wrong
    either way.
    """
    from gauntlet.attacks.registry import all_attacks

    needing_llm = [a.id for a in all_attacks() if a.requires_llm]
    assert needing_llm == ["CDP-001"]
