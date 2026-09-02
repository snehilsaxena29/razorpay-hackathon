"""Provider selection: one live provider, one replay path, one honest fallback.

:func:`build_client` decides what a run talks to, and the decision is visible in
the report header rather than buried. There are exactly three outcomes — live,
replay, or nothing — and "nothing" is a supported state that produces UNKNOWN
verdicts rather than an aborted run.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from gauntlet.errors import ConfigError, ProviderError
from gauntlet.llm.client import (
    DEFAULT_BREAKER_THRESHOLD,
    DEFAULT_MAX_RETRIES,
    ChatMessage,
    LLMClient,
    NullClient,
    ResilientClient,
    parse_json_object,
)
from gauntlet.llm.groq import GroqClient
from gauntlet.llm.replay import CASSETTE_DIR, CassetteClient, RecordingClient

logger = logging.getLogger(__name__)

DEFAULT_CASSETTE = "reference_agents.json"


def build_client(
    *, mode: str, cassette: Path | None = None, record: bool = False
) -> ResilientClient:
    """Build the provider for a run, wrapped in retries and a circuit breaker.

    Args:
        mode: ``"LIVE"`` or ``"REPLAY"``, as resolved by the CLI.
        cassette: the recording to replay; defaults to the shipped one.
        record: wrap the live client so exchanges are written to the cassette.
            Only ever set by hand, never during a scored run.

    Raises:
        ConfigError: if live mode is requested without a usable provider.
            Never downgraded silently — a run that reports REPLAY when the user
            asked for LIVE is a run whose header lies.
    """
    path = cassette or (CASSETTE_DIR / DEFAULT_CASSETTE)

    if mode == "LIVE":
        try:
            live: LLMClient = GroqClient()
        except ProviderError as exc:
            raise ConfigError(f"live mode requested but no provider is usable: {exc}") from exc
        if record:
            logger.warning("recording provider exchanges to %s", path)
            return ResilientClient(inner=RecordingClient(live, path))
        return ResilientClient(inner=live)

    if path.exists():
        return ResilientClient(inner=CassetteClient(path))

    logger.warning(
        "no cassette at %s; semantic checks will report UNKNOWN. Deterministic attacks "
        "are unaffected.",
        path,
    )
    return ResilientClient(inner=NullClient())


def should_record() -> bool:
    """Whether this process was asked to record a cassette."""
    return os.environ.get("GAUNTLET_RECORD", "").strip().lower() in ("1", "true", "yes")


__all__ = [
    "CASSETTE_DIR",
    "DEFAULT_BREAKER_THRESHOLD",
    "DEFAULT_MAX_RETRIES",
    "CassetteClient",
    "ChatMessage",
    "GroqClient",
    "LLMClient",
    "NullClient",
    "RecordingClient",
    "ResilientClient",
    "build_client",
    "parse_json_object",
    "should_record",
]
