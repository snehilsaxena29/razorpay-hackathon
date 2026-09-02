"""Agents under test.

Four are registered. Two are LLM-backed reference agents — the pair the demo
compares — and two are deterministic stubs that model the same failure and
defence modes with rules, so the attack suite runs offline in CI and so a
reviewer with no API key still sees a real before/after.

Adding your own is one method (``AgentUnderTest`` in :mod:`gauntlet.agent`) and
one entry in :data:`AGENTS`. The registry is explicit for the same reason the
attack catalogue is: what a name on the command line resolves to should be
readable, not discovered at runtime.
"""

from __future__ import annotations

from collections.abc import Callable

from gauntlet.agent import AgentUnderTest
from gauntlet.errors import ConfigError
from gauntlet.llm.client import LLMClient
from subjects import hardened, naive
from subjects.stubs import HardenedStub, NaiveStub

AgentFactory = Callable[[LLMClient | None], AgentUnderTest]


def _stub(factory: Callable[[], AgentUnderTest]) -> AgentFactory:
    """Adapt a stub, which needs no provider, to the common factory signature."""

    def build_stub(_client: LLMClient | None) -> AgentUnderTest:
        return factory()

    return build_stub


def _llm(builder: Callable[[LLMClient], AgentUnderTest], label: str) -> AgentFactory:
    """Adapt an LLM-backed agent, which cannot run without a provider."""

    def build_llm(client: LLMClient | None) -> AgentUnderTest:
        if client is None:
            raise ConfigError(
                f"the {label!r} agent needs a language model. Set GROQ_API_KEY, or use "
                f"'{label}-stub' for the deterministic stand-in."
            )
        return builder(client)

    return build_llm


AGENTS: dict[str, AgentFactory] = {
    "naive": _llm(naive.build, "naive"),
    "hardened": _llm(hardened.build, "hardened"),
    "naive-stub": _stub(NaiveStub),
    "hardened-stub": _stub(HardenedStub),
}

#: What ``gauntlet demo`` compares when no provider is configured. Chosen over
#: the LLM pair so the four-minute path never depends on a key or a network.
OFFLINE_PAIR = ("naive-stub", "hardened-stub")

#: What ``gauntlet demo`` compares when a provider is available.
LIVE_PAIR = ("naive", "hardened")


def build(name: str, client: LLMClient | None = None) -> AgentUnderTest:
    """Instantiate an agent by name.

    Raises:
        ConfigError: if the name is unknown, or if an LLM-backed agent was asked
            for with no provider. Both are fatal and both name the alternative —
            silently running nothing would exit 0 and look like a clean result.
    """
    try:
        factory = AGENTS[name]
    except KeyError:
        raise ConfigError(
            f"unknown agent {name!r}. Available: {', '.join(sorted(AGENTS))}"
        ) from None
    return factory(client)


__all__ = [
    "AGENTS",
    "LIVE_PAIR",
    "OFFLINE_PAIR",
    "HardenedStub",
    "NaiveStub",
    "build",
]
