"""Retries and the circuit breaker.

These tests assert on the number of calls actually made, not only on what came
back. A breaker that returns the right verdict while still hammering a dead
provider is the bug this design exists to prevent: ten attacks times three
retries times a twenty-second timeout is a ten-minute hang.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from gauntlet.errors import ProviderError, ProviderTimeoutError, ProviderUnavailableError
from gauntlet.llm.client import (
    ChatMessage,
    NullClient,
    ResilientClient,
    parse_json_object,
)
from gauntlet.llm.groq import GroqError

MESSAGES = [ChatMessage(role="user", content="hello")]


class FakeClient:
    """A provider whose behaviour a test dictates, counting its own calls."""

    name = "fake"
    model = "fake-1"

    def __init__(self, *, responses: list[Any]) -> None:
        self.responses = responses
        self.calls = 0

    def complete_json(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        self.calls += 1
        item = self.responses[min(self.calls - 1, len(self.responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return dict(item)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backoff sleeps make the suite slow and prove nothing."""
    monkeypatch.setattr("gauntlet.llm.client.time.sleep", lambda _s: None)


def test_success_passes_through() -> None:
    inner = FakeClient(responses=[{"outcome": "WITHIN"}])
    client = ResilientClient(inner=inner)
    assert client.complete_json(MESSAGES) == {"outcome": "WITHIN"}
    assert inner.calls == 1


def test_transient_failure_is_retried_then_succeeds() -> None:
    inner = FakeClient(responses=[ProviderTimeoutError("slow"), {"outcome": "WITHIN"}])
    client = ResilientClient(inner=inner)
    assert client.complete_json(MESSAGES) == {"outcome": "WITHIN"}
    assert inner.calls == 2


def test_retries_are_bounded() -> None:
    inner = FakeClient(responses=[ProviderTimeoutError("slow")])
    client = ResilientClient(inner=inner, max_retries=3, breaker_threshold=99)
    with pytest.raises(ProviderError):
        client.complete_json(MESSAGES)
    assert inner.calls == 3


def test_non_retryable_status_is_not_retried() -> None:
    """A 401 will not become valid on the third attempt.

    Retrying it spends the run's time budget confirming what the first response
    already said.
    """
    inner = FakeClient(responses=[GroqError("bad key", status_code=401)])
    client = ResilientClient(inner=inner, max_retries=3, breaker_threshold=99)
    with pytest.raises(ProviderError):
        client.complete_json(MESSAGES)
    assert inner.calls == 1


def test_rate_limit_is_retried() -> None:
    inner = FakeClient(responses=[GroqError("slow down", status_code=429), {"ok": True}])
    client = ResilientClient(inner=inner)
    assert client.complete_json(MESSAGES) == {"ok": True}
    assert inner.calls == 2


def test_server_error_is_retried() -> None:
    inner = FakeClient(responses=[GroqError("boom", status_code=503), {"ok": True}])
    client = ResilientClient(inner=inner)
    assert client.complete_json(MESSAGES) == {"ok": True}
    assert inner.calls == 2


def test_breaker_opens_and_stops_calling_the_provider() -> None:
    """The point of the breaker: no further requests are made at all."""
    inner = FakeClient(responses=[ProviderTimeoutError("down")])
    client = ResilientClient(inner=inner, max_retries=2, breaker_threshold=1)

    with pytest.raises(ProviderError):
        client.complete_json(MESSAGES)
    calls_before = inner.calls
    assert client.is_open
    assert client.status == "DOWN"

    for _ in range(5):
        with pytest.raises(ProviderUnavailableError):
            client.complete_json(MESSAGES)

    assert inner.calls == calls_before, "breaker must stop calls, not just change the result"


def test_breaker_needs_consecutive_failures() -> None:
    """A single failure between successes must not trip it."""
    inner = FakeClient(
        responses=[ProviderTimeoutError("blip"), {"ok": True}, ProviderTimeoutError("blip")]
    )
    client = ResilientClient(inner=inner, max_retries=2, breaker_threshold=2)
    client.complete_json(MESSAGES)
    assert not client.is_open


def test_breaker_reports_the_last_failure() -> None:
    inner = FakeClient(responses=[ProviderTimeoutError("upstream gone")])
    client = ResilientClient(inner=inner, max_retries=1, breaker_threshold=1)
    with pytest.raises(ProviderError):
        client.complete_json(MESSAGES)
    with pytest.raises(ProviderUnavailableError, match="upstream gone"):
        client.complete_json(MESSAGES)


def test_null_client_always_raises() -> None:
    """A missing provider must surface, not return a default."""
    with pytest.raises(ProviderUnavailableError, match="no LLM provider"):
        NullClient().complete_json(MESSAGES)


# ---- response parsing ------------------------------------------------------


def test_parse_plain_json() -> None:
    assert parse_json_object('{"a": 1}') == {"a": 1}


def test_parse_fenced_json() -> None:
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_with_a_preamble() -> None:
    assert parse_json_object('Sure! Here you go:\n{"a": 1}') == {"a": 1}


@pytest.mark.parametrize("text", ["", "no json here", "[1, 2, 3]", "{not valid}"])
def test_unparseable_response_raises(text: str) -> None:
    """Never rescued into a default.

    A parser that works hard to salvage malformed output will eventually
    salvage the wrong thing, and put it in a safety report.
    """
    with pytest.raises(ProviderError):
        parse_json_object(text)
