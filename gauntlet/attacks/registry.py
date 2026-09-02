"""The catalogue: every attack that exists, listed explicitly.

No filesystem scanning, no import magic, no entry points. One file you can read
top to bottom and know the entire catalogue. In a tool whose output is a safety
score, "which checks actually ran" must never be a question that requires
running the thing to answer.

Registration is validated at import: duplicate ids and unknown families fail
immediately rather than producing a catalogue that silently omits an attack and
reports a score computed over fewer checks than the reader believes.
"""

from __future__ import annotations

from collections.abc import Sequence

from gauntlet.attacks.base import Attack, Family
from gauntlet.attacks.catalogue import (
    confused_deputy,
    direct_injection,
    hitl_deception,
    indirect_injection,
    merchant_spoof,
    salami,
)
from gauntlet.errors import AttackError

_MODULES = (
    direct_injection,
    indirect_injection,
    merchant_spoof,
    salami,
    hitl_deception,
    confused_deputy,
)


def _build() -> dict[str, Attack]:
    catalogue: dict[str, Attack] = {}
    for module in _MODULES:
        for attack in module.ATTACKS:
            if attack.id in catalogue:
                raise AttackError(
                    f"duplicate attack id {attack.id} in {module.__name__}; "
                    "one of the two would never run"
                )
            catalogue[attack.id] = attack
    return catalogue


CATALOGUE: dict[str, Attack] = _build()


def all_attacks() -> tuple[Attack, ...]:
    """Every attack, ordered by id so runs and reports are stable."""
    return tuple(CATALOGUE[key] for key in sorted(CATALOGUE))


def get(attack_id: str) -> Attack:
    """Look up one attack by id.

    Raises:
        AttackError: if no such attack exists. Naming the available ids matters
            here — a typo silently selecting nothing would report a clean run.
    """
    try:
        return CATALOGUE[attack_id.upper()]
    except KeyError:
        raise AttackError(
            f"unknown attack {attack_id!r}. Available: {', '.join(sorted(CATALOGUE))}"
        ) from None


def by_family(family: Family | str) -> tuple[Attack, ...]:
    """Every attack in one family, ordered by id.

    Raises:
        AttackError: if the family name is not recognised or has no attacks.
    """
    try:
        wanted = Family(family)
    except ValueError:
        raise AttackError(
            f"unknown family {family!r}. Available: {', '.join(sorted(f.value for f in Family))}"
        ) from None
    found = tuple(a for a in all_attacks() if a.family is wanted)
    if not found:
        raise AttackError(f"family {wanted.value!r} has no attacks in the catalogue")
    return found


def select(*, attack_ids: Sequence[str] = (), family: str | None = None) -> tuple[Attack, ...]:
    """Resolve CLI selectors to a set of attacks.

    Raises:
        AttackError: if a selector matches nothing. Running zero attacks and
            exiting 0 would look exactly like a clean run.
    """
    if attack_ids and family:
        raise AttackError("select by attack id or by family, not both")
    if attack_ids:
        return tuple(get(a) for a in attack_ids)
    if family:
        return by_family(family)
    return all_attacks()


def total_weight(attacks: Sequence[Attack] | None = None) -> int:
    """Sum of severity weights, the denominator a perfect score is measured against."""
    return sum(a.severity.weight for a in (attacks if attacks is not None else all_attacks()))
