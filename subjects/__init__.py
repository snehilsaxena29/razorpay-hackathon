"""Agents under test.

Two reference agents, plus deterministic stubs that stand in for them offline.

Adding your own is one method — see ``AgentUnderTest`` in :mod:`gauntlet.agent`
— and one entry in :data:`AGENTS`. The registry is explicit for the same reason
the attack catalogue is: what an agent named on the command line resolves to
should be readable, not discovered at runtime.
"""

from __future__ import annotations

from collections.abc import Callable

from gauntlet.agent import AgentUnderTest
from gauntlet.errors import ConfigError
from subjects.stubs import HardenedStub, NaiveStub

AGENTS: dict[str, Callable[[], AgentUnderTest]] = {
    "naive-stub": NaiveStub,
    "hardened-stub": HardenedStub,
}


def build(name: str) -> AgentUnderTest:
    """Instantiate an agent by name.

    Raises:
        ConfigError: if the name is unknown. Fatal, and it names the available
            agents — silently running nothing would exit 0 and look clean.
    """
    try:
        factory = AGENTS[name]
    except KeyError:
        raise ConfigError(
            f"unknown agent {name!r}. Available: {', '.join(sorted(AGENTS))}"
        ) from None
    return factory()


__all__ = ["AGENTS", "HardenedStub", "NaiveStub", "build"]
