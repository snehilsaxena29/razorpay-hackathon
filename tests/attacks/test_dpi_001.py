"""DPI-001 — paired detection tests.

A cap stated in prose is a suggestion. The naive agent is talked past it;
    the hardened agent's pre-flight gate refuses the payment in code.
"""

from __future__ import annotations

from gauntlet.attacks.catalogue.direct_injection import DPI_001
from gauntlet.judge.verdict import Verdict
from subjects.stubs import HardenedStub, NaiveStub
from tests.attacks.conftest import RunAttack


def test_dpi_001_detects_on_naive_stub(run_attack: RunAttack) -> None:
    """The attack catches the vulnerability it claims to catch."""
    record = run_attack(DPI_001, NaiveStub())
    assert record.verdict is Verdict.FAIL
    assert "over_per_transaction_cap" in record.predicates_fired


def test_dpi_001_no_false_positive_on_hardened_stub(run_attack: RunAttack) -> None:
    """A correctly-defending agent is not accused."""
    record = run_attack(DPI_001, HardenedStub())
    assert record.verdict is Verdict.PASS, record.violations


def test_dpi_001_injection_actually_fired(run_attack: RunAttack) -> None:
    """An attack whose payload never reached the agent proves nothing.

    A PASS in that case would be a false reassurance, which is the most
    expensive wrong answer this tool can give.
    """
    record = run_attack(DPI_001, NaiveStub())
    assert record.injections_fired == record.injections_declared
