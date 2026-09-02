"""IDI-003 — paired detection tests.

Ground truth is the first-party invoice; the email is an attacker's claim.
    The hardened agent prefers the invoice, which is the whole defence.
"""

from __future__ import annotations

from gauntlet.attacks.catalogue.indirect_injection import IDI_003
from gauntlet.judge.verdict import Verdict
from subjects.stubs import HardenedStub, NaiveStub
from tests.attacks.conftest import RunAttack


def test_idi_003_detects_on_naive_stub(run_attack: RunAttack) -> None:
    """The attack catches the vulnerability it claims to catch."""
    record = run_attack(IDI_003, NaiveStub())
    assert record.verdict is Verdict.FAIL
    assert "beneficiary_mismatch" in record.predicates_fired


def test_idi_003_no_false_positive_on_hardened_stub(run_attack: RunAttack) -> None:
    """A correctly-defending agent is not accused."""
    record = run_attack(IDI_003, HardenedStub())
    assert record.verdict is Verdict.PASS, record.violations


def test_idi_003_injection_actually_fired(run_attack: RunAttack) -> None:
    """An attack whose payload never reached the agent proves nothing.

    A PASS in that case would be a false reassurance, which is the most
    expensive wrong answer this tool can give.
    """
    record = run_attack(IDI_003, NaiveStub())
    assert record.injections_fired == record.injections_declared
