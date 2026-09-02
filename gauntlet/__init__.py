"""gauntlet — an adversarial test harness for payment-capable AI agents.

Points at any agent that can spend money, runs a catalogue of attacks against
it, and reports which ones caused a payment attempt that violated the agent's
declared mandate. No money moves: every attempt is captured by a recording sink
with no network code in it.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
