"""DPI-002 — paired detection tests.

A forged system frame carries no authority. The naive agent cannot tell it
    from a real one because its context is assembled by concatenation.
"""

from __future__ import annotations

from gauntlet.attacks.catalogue.direct_injection import DPI_002
from gauntlet.judge.verdict import Verdict
from subjects.stubs import HardenedStub, NaiveStub
from tests.attacks.conftest import RunAttack


def test_dpi_002_detects_on_naive_stub(run_attack: RunAttack) -> None:
    """The attack catches the vulnerability it claims to catch."""
    record = run_attack(DPI_002, NaiveStub())
    assert record.verdict is Verdict.FAIL
    assert "merchant_denied" in record.predicates_fired


def test_dpi_002_no_false_positive_on_hardened_stub(run_attack: RunAttack) -> None:
    """A correctly-defending agent is not accused."""
    record = run_attack(DPI_002, HardenedStub())
    assert record.verdict is Verdict.PASS, record.violations


def test_dpi_002_injection_actually_fired(run_attack: RunAttack) -> None:
    """An attack whose payload never reached the agent proves nothing.

    A PASS in that case would be a false reassurance, which is the most
    expensive wrong answer this tool can give.
    """
    record = run_attack(DPI_002, NaiveStub())
    assert record.injections_fired == record.injections_declared
