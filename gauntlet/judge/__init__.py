"""Judging: deterministic predicates, one semantic judge, and the scoring rules.

The split between :mod:`gauntlet.judge.deterministic` and
:mod:`gauntlet.judge.semantic` is the load-bearing design decision of this
package. Arithmetic and set membership go in the former and always produce an
answer; the single question that genuinely needs a language model goes in the
latter and is allowed to answer UNKNOWN.
"""

from __future__ import annotations

from gauntlet.judge.evidence import JudgeInput
from gauntlet.judge.verdict import (
    SEVERITY_WEIGHTS,
    SafetyScore,
    Severity,
    Verdict,
    Violation,
    score_run,
)

__all__ = [
    "SEVERITY_WEIGHTS",
    "JudgeInput",
    "SafetyScore",
    "Severity",
    "Verdict",
    "Violation",
    "score_run",
]
