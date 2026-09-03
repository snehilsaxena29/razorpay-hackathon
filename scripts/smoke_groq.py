"""Confirm the provider works, before anything depends on it.

Model ids get retired. Keys expire. Both fail in ways that look like a bug in
the harness if you meet them for the first time halfway through a run, so this
is a thirty-second check that answers "is the provider usable right now" and
nothing else.

    python scripts/smoke_groq.py

Prints the model it reached and one completion, or an explanation and a non-zero
exit code.
"""

from __future__ import annotations

import os
import sys

from gauntlet.errors import GauntletError
from gauntlet.llm.client import ChatMessage
from gauntlet.llm.groq import GroqClient
from gauntlet.report.console import ensure_utf8_streams


def main() -> int:
    ensure_utf8_streams()
    if not os.environ.get("GROQ_API_KEY"):
        print("GROQ_API_KEY is not set. The harness still runs — deterministic")
        print("attacks are unaffected and `make demo` needs no key — but the")
        print("LLM-backed reference agents and the semantic judge will not.")
        return 1

    try:
        client = GroqClient()
    except GauntletError as exc:
        print(f"could not build a client: {exc}")
        return 1

    print(f"provider: {client.name}")
    print(f"model:    {client.model}")

    try:
        reply = client.complete_json(
            [
                ChatMessage(
                    role="system",
                    content='Reply with JSON only: {"ok": true, "note": "<five words>"}',
                ),
                ChatMessage(role="user", content="Say the provider is reachable."),
            ],
            max_tokens=60,
        )
    except GauntletError as exc:
        print(f"\ncall failed: {exc}")
        print("\nIf this is a 404 on the model, the id was probably retired. List")
        print("what is available:")
        print('  curl -H "Authorization: Bearer $GROQ_API_KEY" \\')
        print("       https://api.groq.com/openai/v1/models")
        print("then set GAUNTLET_MODEL to one of them.")
        return 1

    print(f"response: {reply}")
    print("\nProvider is usable. You can now run:")
    print("  gauntlet compare --agents naive,hardened      # live")
    print("  make record                                   # capture cassettes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
