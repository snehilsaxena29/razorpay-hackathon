"""The provider interface, and the resilience wrapped around it.

Two ideas, both about what happens when the provider is having a bad day:

**Bounded retries.** Three attempts, jittered backoff, and only for failures
that might resolve — a timeout, a 429, a 5xx. A 401 is retried zero times,
because the key will not become valid on the third attempt.

**A circuit breaker.** After a few consecutive failures the provider is marked
down for the rest of the run and every later call fails instantly. Without it,
ten attacks times three retries times a twenty-second timeout is a ten-minute
hang in the middle of a demo, and the outcome is the same either way.

The abstraction is deliberately thin. One protocol, one live provider, one
replay implementation. Adding a second provider is a forty-line file; building a
provider *framework* for a two-day project would be effort spent on the wrong
axis.
"""

from __future__ import annotations

import json
import logging
import random
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from gauntlet.errors import ProviderError, ProviderTimeoutError, ProviderUnavailableError

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 3
DEFAULT_BREAKER_THRESHOLD = 3
DEFAULT_TIMEOUT_S = 20


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One message in a completion request."""

    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@runtime_checkable
class LLMClient(Protocol):
    """A provider that returns a JSON object.

    Every call site in this package wants structured output — an agent's next
    action, or a judge's verdict — so the protocol requires JSON rather than
    free text. Prose from a model is something a caller then has to parse, and
    parsing prose is where safety tools acquire their subtle bugs.
    """

    @property
    def name(self) -> str:
        """Provider identifier, for the report header."""
        ...

    @property
    def model(self) -> str:
        """Model identifier, recorded so a run can be reproduced."""
        ...

    def complete_json(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Return the model's response parsed as a JSON object.

        Raises:
            ProviderError: on any provider failure, including unparseable output.
        """
        ...


@dataclass
class ResilientClient:
    """Wraps a provider with retries and a circuit breaker.

    The breaker is per-run and never resets. A provider that failed three times
    in a row during one run is not going to be trusted for the rest of it, and
    the alternative — probing it again for every remaining attack — costs
    minutes and produces the same answer.
    """

    inner: LLMClient
    max_retries: int = DEFAULT_MAX_RETRIES
    breaker_threshold: int = DEFAULT_BREAKER_THRESHOLD
    _consecutive_failures: int = 0
    _open: bool = False
    calls_attempted: int = 0
    """Counted so tests can assert the breaker actually stops calls being made,
    rather than merely changing what they return."""

    failures: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.inner.name

    @property
    def model(self) -> str:
        return self.inner.model

    @property
    def status(self) -> str:
        """``"UP"`` or ``"DOWN"``. Reported in every report header."""
        return "DOWN" if self._open else "UP"

    @property
    def is_open(self) -> bool:
        return self._open

    def complete_json(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Call the provider, retrying transient failures.

        Raises:
            ProviderUnavailableError: if the breaker is open. Raised without a
                request, so a downed provider costs one failure rather than one
                per remaining attack.
            ProviderError: if every attempt failed.
        """
        if self._open:
            raise ProviderUnavailableError(
                f"circuit breaker open after {self.breaker_threshold} consecutive failures; "
                f"last was: {self.failures[-1] if self.failures else 'unknown'}"
            )

        last: ProviderError | None = None
        for attempt in range(1, self.max_retries + 1):
            self.calls_attempted += 1
            try:
                result = self.inner.complete_json(
                    messages, max_tokens=max_tokens, temperature=temperature
                )
            except ProviderError as exc:  # isolation boundary — retried, then recorded
                last = exc
                self.failures.append(f"{type(exc).__name__}: {exc}")
                logger.warning(
                    "provider %s attempt %d/%d failed: %s",
                    self.inner.name,
                    attempt,
                    self.max_retries,
                    exc,
                )
                if not _is_retryable(exc) or attempt == self.max_retries:
                    break
                time.sleep(_backoff_seconds(attempt))
            else:
                self._consecutive_failures = 0
                return result

        self._consecutive_failures += 1
        if self._consecutive_failures >= self.breaker_threshold:
            self._open = True
            logger.warning(
                "provider %s marked DOWN for the rest of this run after %d consecutive "
                "failures; semantic checks will report UNKNOWN",
                self.inner.name,
                self._consecutive_failures,
            )
        raise last or ProviderError("provider failed for an unrecorded reason")


def _is_retryable(exc: ProviderError) -> bool:
    """Whether another attempt could plausibly succeed.

    A timeout or a rate limit might clear. A malformed key or a rejected request
    will not, and retrying it just spends the run's time budget confirming it.
    """
    if isinstance(exc, ProviderTimeoutError):
        return True
    status = getattr(exc, "status_code", None)
    return status is None or status == 429 or status >= 500


def _backoff_seconds(attempt: int) -> float:
    """Exponential backoff with jitter, capped so a run cannot stall on it."""
    return min(2.0**attempt * 0.25, 4.0) * (0.5 + random.random() / 2)


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a model's response into a JSON object.

    Tolerates the two things models reliably do to JSON — wrapping it in a
    ``` fence, and prefixing it with a sentence — but nothing beyond that. A
    parser that works hard to rescue malformed output is a parser that will
    eventually rescue the wrong thing.

    Raises:
        ProviderError: if the text does not contain a JSON object.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1] if "```" in cleaned[3:] else cleaned[3:]
        if cleaned.lstrip().startswith("json"):
            cleaned = cleaned.lstrip()[4:]

    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ProviderError(f"response contains no JSON object: {text[:200]!r}")

    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ProviderError(f"response is not valid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ProviderError(f"expected a JSON object, got {type(parsed).__name__}")
    return parsed


class NullClient:
    """A provider that is never available.

    Used when no key is configured. Raising immediately — rather than returning
    an empty or default answer — is what makes a missing provider surface as
    UNKNOWN in the report instead of a silently wrong verdict.
    """

    name = "null"
    model = "none"

    def complete_json(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        raise ProviderUnavailableError(
            "no LLM provider configured (set GROQ_API_KEY, or run in replay mode)"
        )
