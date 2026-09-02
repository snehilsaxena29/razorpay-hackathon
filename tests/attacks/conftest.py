"""Harness for the paired attack tests.

Every attack ships with two tests (CONVENTIONS.md §7): one proving it detects
the vulnerability on the naive stub, one proving it does not accuse the hardened
stub. Both run against deterministic stubs, offline — CI has no API key, and an
attack whose detection cannot be demonstrated without a live model cannot be
regression-tested at all.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from gauntlet.agent import AgentUnderTest
from gauntlet.attacks.base import Attack
from gauntlet.judge.evidence import CategoryJudge
from gauntlet.ledger import Ledger, new_run_id
from gauntlet.mandate import Mandate
from gauntlet.runner import AttackRecord, Runner

RunAttack = Callable[..., AttackRecord]


@pytest.fixture
def run_attack(tmp_path: Path, ops_mandate: Mandate) -> RunAttack:
    """Run one attack against one agent and return the record.

    Uses the real shipped mandate rather than a fixture copy: an attack that
    only fires against a mandate written to suit it is not evidence of anything.
    """

    def _run(
        attack: Attack, agent: AgentUnderTest, judge: CategoryJudge | None = None
    ) -> AttackRecord:
        run_id = new_run_id()
        with Ledger(tmp_path / f"{run_id}.jsonl", run_id=run_id) as ledger:
            runner = Runner(
                mandate=ops_mandate,
                ledger=ledger,
                episode_timeout_s=15,
                semantic_judge=judge,
            )
            return runner.run_attack(agent, attack)

    return _run
