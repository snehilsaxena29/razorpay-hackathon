"""The one live provider. The only module in this package permitted to import ``httpx``.

Talks to Groq's OpenAI-compatible endpoint over plain HTTP rather than through a
vendor SDK. One POST does not justify a client library, and the absence of one
is what makes a second provider a short file instead of an adapter layer.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

import httpx

from gauntlet.errors import ProviderError, ProviderTimeoutError, ProviderUnavailableError
from gauntlet.llm.client import (
    DEFAULT_TIMEOUT_S,
    ChatMessage,
    parse_json_object,
)

DEFAULT_MODEL = "qwen/qwen3.8-27b"
"""Verified against a live account on 2026-09-03.

Model ids get retired: the id this project was specified against was
withdrawn before the first live run, which is why `scripts/smoke_groq.py`
exists and is the first thing to run.

Chosen over `openai/gpt-oss-120b`, which is a stronger model but was not
usable for a full run on a free tier: its reasoning tokens make each step
several times more expensive, so a ten-attack run against two agents spent
most of its time rate-limited, and its JSON mode returned empty completions
on the longest prompts. Set GAUNTLET_MODEL to use it on a paid tier."""
DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"

#: Models that emit reasoning tokens before their answer. Those tokens count
#: against ``max_tokens``, so an ordinary-looking budget can be consumed before
#: the model writes a single character of JSON — the provider then rejects the
#: empty completion as invalid JSON, which reads like a harness bug and is not
#: one. Capping the reasoning effort is the fix; raising the budget alone only
#: moves the cliff.
_REASONING_MODEL_MARKERS = ("gpt-oss", "o1", "o3", "deepseek-r1", "qwq")

DEFAULT_REASONING_EFFORT = "low"
"""Low because this is a classification and tool-selection loop, not a task that
rewards deliberation, and because a smaller reasoning budget makes runs faster,
cheaper and less likely to meet a rate limit."""


class GroqError(ProviderError):
    """A Groq API error, carrying the HTTP status so retry logic can use it."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after_s: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after_s = retry_after_s


class GroqClient:
    """A minimal JSON-mode chat client.

    Raises:
        ProviderUnavailableError: at construction if no API key is available.
            Failing here rather than on first use means a misconfigured run
            stops before it has produced half a report.
    """

    name = "groq"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: int | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        key = api_key or os.environ.get("GROQ_API_KEY")
        if not key:
            raise ProviderUnavailableError("GROQ_API_KEY is not set")
        self._key = key
        self.model = model or os.environ.get("GAUNTLET_MODEL", DEFAULT_MODEL)
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s or int(
            os.environ.get("GAUNTLET_LLM_TIMEOUT_S", DEFAULT_TIMEOUT_S)
        )
        self._reasoning_effort = reasoning_effort or os.environ.get(
            "GAUNTLET_REASONING_EFFORT", DEFAULT_REASONING_EFFORT
        )

    @property
    def is_reasoning_model(self) -> bool:
        """Whether this model spends tokens thinking before it answers."""
        lowered = self.model.lower()
        return any(marker in lowered for marker in _REASONING_MODEL_MARKERS)

    def complete_json(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """POST a chat completion in JSON mode and return the parsed object.

        ``temperature`` defaults to 0. A safety harness whose results shift
        between runs is a harness nobody can act on, and the residual
        non-determinism of a hosted model is already more than we would like.

        Raises:
            ProviderTimeoutError: if the request exceeds its timeout.
            GroqError: on a transport error or a non-2xx response.
            ProviderError: if the response body is not usable JSON.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        if self.is_reasoning_model:
            payload["reasoning_effort"] = self._reasoning_effort

        try:
            with httpx.Client(timeout=self._timeout_s) as client:
                response = client.post(
                    f"{self._base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"groq request timed out after {self._timeout_s}s") from exc
        except httpx.HTTPError as exc:
            raise GroqError(f"groq transport error: {exc}") from exc

        if response.status_code >= 400:
            # Providers say how long to wait; guessing is worse than asking.
            retry_after = response.headers.get("retry-after")
            raise GroqError(
                f"groq returned {response.status_code}: {response.text[:300]}",
                status_code=response.status_code,
                retry_after_s=_parse_retry_after(retry_after),
            )

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderError(f"unexpected groq response shape: {exc}") from exc

        return parse_json_object(content)


def _parse_retry_after(value: str | None) -> float | None:
    """Read a ``Retry-After`` header, ignoring anything unparseable.

    Capped: a provider asking for a five-minute wait is telling us this run is
    not going to finish, and blocking for it would turn a rate limit into a
    hang. Beyond the cap the breaker should open instead.
    """
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return min(seconds, 30.0) if seconds > 0 else None
