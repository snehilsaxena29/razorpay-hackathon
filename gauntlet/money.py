"""Money as an integer count of minor units, and the only place it is formatted.

There is no ``float`` anywhere in the payment path. Currency amounts are ints
named ``*_minor`` (paise for INR, cents for USD) from the moment they enter the
system until the moment they are rendered for a human. Floating-point money in a
tool that decides whether a payment breached a cap is a defect waiting for a
rounding boundary.

This module owns two operations:

- :func:`format_minor` — minor units to a display string, for reports and prompts.
- :func:`extract_amounts` — display strings back to minor units, needed because
  the human-in-the-loop attacks turn on *what a human was shown* rather than what
  was submitted, and what they were shown is prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MINOR_UNITS_PER_MAJOR: dict[str, int] = {
    "INR": 100,
    "USD": 100,
    "EUR": 100,
    "GBP": 100,
    "JPY": 1,
}
"""Minor units per major unit. Not every currency is 100; JPY is here to keep
that fact visible rather than assumed."""

_CURRENCY_SYMBOLS: dict[str, str] = {
    "INR": "₹",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
}

_SYMBOL_TO_CODE: dict[str, str] = {
    "₹": "INR",
    "rs": "INR",
    "rs.": "INR",
    "inr": "INR",
    "rupee": "INR",
    "rupees": "INR",
    "$": "USD",
    "usd": "USD",
    "dollar": "USD",
    "dollars": "USD",
    "€": "EUR",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "£": "GBP",
    "gbp": "GBP",
    "pounds": "GBP",
    "¥": "JPY",
    "jpy": "JPY",
    "yen": "JPY",
}

_NUMBER = r"\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?"

# Derived from _SYMBOL_TO_CODE rather than written out, so a currency added to
# the table is matched by the patterns automatically. Hand-maintaining both
# would eventually let them drift, and a marker the regex matches but the table
# does not know is an amount silently dropped from an approval prompt.
_MARKERS = "|".join(re.escape(m) for m in sorted(_SYMBOL_TO_CODE, key=len, reverse=True))

_PREFIXED_AMOUNT = re.compile(rf"(?P<marker>{_MARKERS})\s*(?P<number>{_NUMBER})", re.IGNORECASE)

_SUFFIXED_AMOUNT = re.compile(
    rf"(?P<number>{_NUMBER})\s*(?P<marker>{_MARKERS})(?![a-z])", re.IGNORECASE
)
"""Suffix forms matter because agents write "58,500 rupees" as readily as "₹58,500",
and an approval prompt whose amount we fail to parse would produce the right
verdict for the wrong reason — see ``judge.deterministic.approval_divergence``."""


@dataclass(frozen=True, slots=True)
class ExtractedAmount:
    """A currency amount found in free text, with the currency it was marked with."""

    amount_minor: int
    currency: str
    raw: str
    start: int = -1
    """Character offset in the source text, so callers can look at what surrounds it."""
    end: int = -1


def minor_units_for(currency: str) -> int:
    """Return the number of minor units in one major unit of ``currency``.

    Unknown currencies default to 100 rather than raising: an unrecognised
    currency on an attempt is itself a mandate violation (see
    ``judge.deterministic.currency_mismatch``), and that check should be the one
    that fires, not a crash inside formatting.
    """
    return MINOR_UNITS_PER_MAJOR.get(currency.upper(), 100)


def format_minor(amount_minor: int, currency: str = "INR") -> str:
    """Render minor units for a human, e.g. ``500000`` INR to ``"₹5,000.00"``.

    Uses Indian digit grouping (lakh/crore) for INR because the audience is
    Indian and ``₹1,00,000`` reads correctly to them where ``₹100,000`` does not.
    """
    divisor = minor_units_for(currency)
    symbol = _CURRENCY_SYMBOLS.get(currency.upper(), f"{currency.upper()} ")

    sign = "-" if amount_minor < 0 else ""
    magnitude = abs(amount_minor)
    major, minor = divmod(magnitude, divisor)

    grouped = _group_indian(major) if currency.upper() == "INR" else f"{major:,}"

    if divisor == 1:
        return f"{sign}{symbol}{grouped}"
    width = len(str(divisor)) - 1
    return f"{sign}{symbol}{grouped}.{minor:0{width}d}"


def _group_indian(value: int) -> str:
    """Group digits in the Indian system: last three, then pairs (12,34,567)."""
    digits = str(value)
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts: list[str] = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join([*parts, tail])


def extract_amounts(text: str) -> tuple[ExtractedAmount, ...]:
    """Find every currency-marked amount in ``text``, in order of appearance.

    Only *marked* amounts count — a bare ``1850`` could be an order id, a SKU, or
    a year, and treating it as money would make the human-in-the-loop check fire
    on noise. An approval prompt that shows a human an amount always marks it.

    Returns an empty tuple when the text states no amount at all, which callers
    must handle explicitly rather than defaulting to zero.
    """
    found: list[tuple[int, ExtractedAmount]] = []
    claimed: list[tuple[int, int]] = []

    for pattern in (_PREFIXED_AMOUNT, _SUFFIXED_AMOUNT):
        for match in pattern.finditer(text):
            currency = _SYMBOL_TO_CODE[match.group("marker").lower()]
            span = match.span()
            # The prefix pass wins on overlap: "Rs 500" should not also be read
            # as a bare "500 rs" by the suffix pass on some other substring.
            if any(span[0] < end and start < span[1] for start, end in claimed):
                continue
            claimed.append(span)
            found.append(
                (
                    span[0],
                    ExtractedAmount(
                        amount_minor=_to_minor(match.group("number"), currency),
                        currency=currency,
                        raw=match.group(0),
                        start=span[0],
                        end=span[1],
                    ),
                )
            )

    return tuple(amount for _, amount in sorted(found, key=lambda pair: pair[0]))


def _to_minor(number: str, currency: str) -> int:
    """Convert a matched number string to minor units, without ever using a float."""
    digits = number.replace(",", "")
    divisor = minor_units_for(currency)
    if "." not in digits:
        return int(digits) * divisor
    major_part, minor_part = digits.split(".", 1)
    width = len(str(divisor)) - 1
    if width == 0:
        return int(major_part) * divisor
    minor_value = int(minor_part.ljust(width, "0")[:width])
    return int(major_part) * divisor + minor_value
