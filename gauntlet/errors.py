"""The exception hierarchy and process exit codes.

Every exception this package raises descends from :class:`GauntletError`, so a
caller can distinguish "the harness broke" from "something else broke" without
resorting to a bare ``except``.

Names deliberately avoid shadowing builtins: ``EpisodeTimeoutError``, not
``TimeoutError``.
"""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """Process exit codes.

    Distinct codes for "the agent is unsafe" and "we could not tell" is the
    point of the whole tool: CI can gate on ``UNSAFE`` and alert on ``DEGRADED``
    without conflating a vulnerability with an outage.
    """

    CLEAN = 0
    """All attacks resolved, none succeeded against the agent."""

    UNSAFE = 1
    """At least one attack succeeded. Dominates DEGRADED when both apply."""

    DEGRADED = 2
    """Run completed, but some verdicts are UNKNOWN or ERROR. No failures."""

    CANNOT_START = 3
    """Bad configuration, unreadable mandate, unwritable output directory."""


class GauntletError(Exception):
    """Base class for every error raised by this package."""


class ConfigError(GauntletError):
    """Invalid CLI arguments, environment, or output location.

    Fatal: exits with :attr:`ExitCode.CANNOT_START`. Never downgraded into a
    partial run, because a misconfigured safety tool that appears to work is
    worse than one that refuses to start.
    """


class MandateError(GauntletError):
    """A mandate is missing, unparseable, or internally inconsistent.

    Fatal. The mandate is the ground truth every verdict is measured against;
    if it is wrong, every verdict is wrong.
    """


class AttackError(GauntletError):
    """An attack definition is malformed or its id is unknown."""


class AgentError(GauntletError):
    """The agent under test misbehaved in a way the harness must record.

    Recorded as verdict ERROR for that attack; the run continues.
    """


class EpisodeTimeoutError(AgentError):
    """The agent exceeded its wall-clock budget for a single episode."""


class ProviderError(GauntletError):
    """The LLM provider failed.

    Never fatal to a run. Semantic checks degrade to UNKNOWN; deterministic
    attacks are unaffected because they never touch a provider.
    """


class ProviderTimeoutError(ProviderError):
    """A provider request exceeded its timeout."""


class ProviderUnavailableError(ProviderError):
    """The circuit breaker is open, or no provider is configured.

    Raised without attempting a request, so a downed provider costs one
    failure rather than one failure per remaining attack.
    """


class LedgerError(GauntletError):
    """The append-only ledger could not be written or read.

    Fatal on write: a run with no audit trail is not a run.
    """
