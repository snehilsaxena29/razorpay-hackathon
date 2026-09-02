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

DEFAULT_MODEL = "llama-3.3-70b-versatile"
DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"


class GroqError(ProviderError):
    """A Groq API error, carrying the HTTP status so retry logic can use it."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


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
        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }

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
            raise GroqError(
                f"groq returned {response.status_code}: {response.text[:300]}",
                status_code=response.status_code,
            )

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderError(f"unexpected groq response shape: {exc}") from exc

        return parse_json_object(content)
