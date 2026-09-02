"""Cassettes: record a live run once, replay it forever.

This is what makes ``make demo`` work on a clean clone with no API key and no
network, which is the single most important property the repository has for
someone with four minutes. It is also the fallback when the provider is down on
the day of a demo.

**Honesty rule.** A replayed run is never presented as a live one. The mode
appears in the console output, in the report header, and in the JSON. What is
replayed is a *recording of real model behaviour* — the agent genuinely did
this, once, against a live provider — but it was not re-derived now, and the
difference is stated rather than glossed.

A cassette miss raises rather than falling back to a plausible answer. An
invented response would be a fabricated result in a safety report, which is the
one thing this tool must never produce.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from gauntlet.errors import ProviderError, ProviderUnavailableError
from gauntlet.llm.client import ChatMessage, LLMClient

CASSETTE_DIR = Path("fixtures/cassettes")


def request_key(model: str, messages: Sequence[ChatMessage], temperature: float) -> str:
    """A stable content hash of a request.

    Keyed on the full message list so a changed prompt misses rather than
    silently replaying a recording made for different input — which would look
    like a working run and mean nothing.
    """
    payload = json.dumps(
        {
            "model": model,
            "temperature": temperature,
            "messages": [m.to_dict() for m in messages],
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


class CassetteClient:
    """Replays recorded provider responses.

    Raises:
        ProviderUnavailableError: on a cassette miss. Deliberate: the caller
            converts it to UNKNOWN, and an honest "we have no recording for
            this" beats a fabricated verdict.
    """

    name = "cassette"

    def __init__(self, path: Path, *, model: str = "replay") -> None:
        self.path = path
        self.model = model
        self._entries: dict[str, Any] = {}
        self.hits = 0
        self.misses = 0

        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ProviderError(f"cannot read cassette {path}: {exc}") from exc
            self.model = data.get("model", model)
            self._entries = data.get("entries", {})

    def complete_json(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        key = request_key(self.model, messages, temperature)
        if key not in self._entries:
            self.misses += 1
            raise ProviderUnavailableError(
                f"no recorded response for this request in {self.path.name} "
                f"(key {key}). Re-record with GROQ_API_KEY set and "
                "GAUNTLET_RECORD=1, or accept UNKNOWN for this check."
            )
        self.hits += 1
        result = self._entries[key]
        if not isinstance(result, dict):
            raise ProviderError(f"cassette entry {key} is not a JSON object")
        return result


class RecordingClient:
    """Wraps a live client and writes every exchange to a cassette.

    Used once, by hand, to produce the fixtures the demo replays. Not part of
    any normal run: recording during a scored run would mean the cassette
    contains whatever happened to be produced, including a failure.
    """

    def __init__(self, inner: LLMClient, path: Path) -> None:
        self.inner = inner
        self.path = path
        self._entries: dict[str, Any] = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            self._entries = data.get("entries", {})

    @property
    def name(self) -> str:
        return f"recording:{self.inner.name}"

    @property
    def model(self) -> str:
        return self.inner.model

    def complete_json(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        result = self.inner.complete_json(messages, max_tokens=max_tokens, temperature=temperature)
        self._entries[request_key(self.model, messages, temperature)] = result
        self.flush()
        return result

    def flush(self) -> None:
        """Write the cassette to disk.

        Called after every exchange rather than at the end, so an interrupted
        recording session keeps what it already captured.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {"model": self.model, "entries": self._entries},
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
