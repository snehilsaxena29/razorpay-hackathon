"""Extracting "pay X to Y" intents from prose.

Used by the stub agents in :mod:`subjects.stubs`, which stand in for the
LLM-backed reference agents so that the attack suite runs offline and
deterministically in CI.

The parser is deliberately literal-minded. That is not a shortcut — it is a
faithful model of the failure being tested. A naive agent's defect is not that
it parses badly; it is that it treats any instruction-shaped text as an
instruction, whatever the source. A crude parser that does exactly that
reproduces the behaviour without needing a model in the loop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from gauntlet.context import Provenance
from gauntlet.money import extract_amounts

#: Words that end a merchant name. Without these, "to QuickCash Solutions today
#: so the order ships" yields a merchant called "QuickCash Solutions today so
#: the order ships", which no lookup would resolve.
_STOP_WORDS: frozenset[str] = frozenset(
    {
        "and",
        "so",
        "then",
        "using",
        "via",
        "on",
        "by",
        "with",
        "before",
        "after",
        "as",
        "if",
        "please",
        "today",
        "now",
        "immediately",
        "to",
        "at",
        "in",
        "from",
        "that",
        "which",
        "this",
        "for",
        "the",
        "a",
        "an",
        "is",
        "are",
        "will",
        "would",
        "should",
        "must",
        "can",
        "when",
        "while",
        "because",
        "our",
        "your",
        "their",
        "his",
        "her",
        "its",
        "we",
        "you",
        "they",
        "instead",
        "rather",
        "otherwise",
        "however",
        "urgently",
        "directly",
        "asap",
        "until",
        "since",
        "also",
        "plus",
        "not",
        "no",
        "but",
        "or",
        "right",
        "away",
        "soon",
        "first",
        "next",
        "again",
        "back",
        "just",
        "still",
        "here",
        "there",
        "within",
        "per",
        "each",
        "every",
        "once",
    }
)

#: A period followed by whitespace and a capital letter ends a sentence, and a
#: merchant name never spans one. Without this, "…at checkout.example. Pay ₹2,500
#: to…" yields a merchant called "checkout.example Pay", which resolves to the
#: right party by luck and prints wrong in the report.
_SENTENCE_END = re.compile(r"[.!?]\s+(?=[^\W\da-z_])|\n")

#: An amount with no named counterparty is only a payment intent if something
#: nearby is telling someone to move money. Without this, every price in a
#: product listing would read as an instruction to pay it.
_ACTION = re.compile(
    r"\b(?:pay|paid|remit|purchase|buy|transfer|send|settle|charge|order|"
    r"payment|remittance|checkout)\b",
    re.IGNORECASE,
)

_MERCHANT = r"(?P<merchant>[^\W\d_][\w&.'’-]*(?:\s+[\w&.'’-]+){0,7})"
_TO_MERCHANT = re.compile(rf"\b(?:to|at|towards)\s+{_MERCHANT}", re.IGNORECASE)
_CATEGORY = re.compile(
    r"\bcategor(?:y|ise[d]?)\s*(?:as|:)?\s*[\"']?(?P<category>\w+)", re.IGNORECASE
)
_QUOTED = re.compile(r"[\"“'](?P<quoted>[^\"”']{8,200})[\"”']")

#: How far either side of an amount to look for its counterparty.
_WINDOW = 160


@dataclass(frozen=True, slots=True)
class PayDirective:
    """One "move this much money to this party" intent found in text."""

    amount_minor: int
    currency: str
    merchant_name: str
    provenance: Provenance
    category: str | None = None
    context: str = ""
    """The surrounding sentence, quoted into the transcript as evidence."""
    source_index: int | None = None
    """Transcript index of the message this intent was read from.

    Carried so the report can quote the exact content that caused a payment
    rather than inferring it from text similarity. An agent knows what it acted
    on; making it say so is cheaper and more honest than guessing afterwards.
    """


def parse_pay_directives(
    text: str, provenance: Provenance, *, source_index: int | None = None
) -> tuple[PayDirective, ...]:
    """Find every payment intent in ``text``, tagged with where the text came from.

    An amount whose counterparty cannot be identified still yields a directive
    — with ``merchant_name`` set to ``"unspecified merchant"`` — provided
    something nearby is actually instructing a payment. That case is not a
    parser failure to paper over: an agent that pays an amount it read without
    establishing who it is paying is precisely the behaviour IDI-001 catches,
    and dropping the directive would hide it.

    A bare price with no instruction around it is skipped. Otherwise every
    figure in a product listing would read as an order to pay it, and the naive
    agent would look reckless for reasons the attack never tested.
    """
    directives: list[PayDirective] = []
    for amount in extract_amounts(text):
        after = text[amount.end : amount.end + _WINDOW]
        before = text[max(0, amount.start - _WINDOW) : amount.start]

        merchant = _first_merchant(after) or _first_merchant(before)
        if merchant is None and not (_ACTION.search(after) or _ACTION.search(before)):
            # A stated price, not an instruction to pay one.
            continue
        category_match = _CATEGORY.search(after) or _CATEGORY.search(before)

        directives.append(
            PayDirective(
                amount_minor=amount.amount_minor,
                currency=amount.currency,
                merchant_name=merchant or "unspecified merchant",
                provenance=provenance,
                category=category_match.group("category") if category_match else None,
                context=_sentence_around(text, amount.start, amount.end),
                source_index=source_index,
            )
        )
    return tuple(directives)


def suggested_approval_phrasing(text: str) -> str | None:
    """Return a quoted approval line the text is proposing, if any.

    Hostile content asks an agent to phrase its confirmation a particular way —
    "keep it short, just say ..." — and a naive agent obliges. This is what
    HIL-001 turns on: the human then approves the phrasing rather than the
    payment. Only quoted text that actually states an amount qualifies, so
    ordinary quotations do not trip it.
    """
    for match in _QUOTED.finditer(text):
        candidate = match.group("quoted")
        if extract_amounts(candidate):
            return candidate.strip()
    return None


def _first_merchant(window: str) -> str | None:
    """Pull the first plausible counterparty name out of a text window.

    The window is cut at the first sentence boundary before matching, so a name
    cannot run past the end of the sentence that introduced it.
    """
    match = _TO_MERCHANT.search(_first_sentence(window))
    if match is None:
        return None
    return _trim_merchant(match.group("merchant"))


def _first_sentence(window: str) -> str:
    """Everything up to the first sentence boundary."""
    boundary = _SENTENCE_END.search(window)
    return window[: boundary.start() + 1] if boundary else window


def _trim_merchant(raw: str) -> str | None:
    """Cut a captured phrase down to the merchant name itself."""
    words = raw.split()
    kept: list[str] = []
    for word in words:
        cleaned = word.strip(".,;:!?()[]")
        if not cleaned:
            break
        if cleaned.lower() in _STOP_WORDS:
            break
        kept.append(cleaned)
    if not kept:
        return None
    return " ".join(kept)


def _sentence_around(text: str, start: int, end: int) -> str:
    """The sentence containing a span, for quoting into the transcript."""
    left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start)) + 1
    right_candidates = [i for i in (text.find(".", end), text.find("\n", end)) if i != -1]
    right = min(right_candidates) + 1 if right_candidates else len(text)
    return text[left:right].strip()
