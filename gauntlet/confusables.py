"""Unicode confusable folding, for deciding whether two merchant names collide.

"Аmazon Web Services" with a Cyrillic А (U+0410) and "Amazon Web Services" with
a Latin A are different strings, identical pixels. Every agent framework we
looked at matches merchants by display name, and every one of them is defeated
by a single substituted codepoint.

:func:`skeleton` reduces a name to a form where visually identical strings
compare equal. It is arithmetic and table lookup — no model, no network, no
judgement. This is the kind of check that should never have been sent to an LLM
in the first place.

The table is a working subset of the Unicode confusables data, not the whole of
it. Vendoring the full file would add a megabyte to a repository whose point is
that the important checks are small enough to read.
"""

from __future__ import annotations

import re
import unicodedata

_CONFUSABLES: dict[str, str] = {
    # Cyrillic lowercase that render as Latin
    "а": "a",
    "в": "b",
    "с": "c",
    "е": "e",
    "һ": "h",
    "і": "i",
    "ј": "j",
    "к": "k",
    "м": "m",
    "н": "h",
    "о": "o",
    "р": "p",
    "ԛ": "q",
    "г": "r",
    "ѕ": "s",
    "т": "t",
    "у": "y",
    "х": "x",
    "ѵ": "v",
    "ԁ": "d",
    "ӏ": "l",
    # Cyrillic uppercase
    "А": "a",
    "В": "b",
    "С": "c",
    "Е": "e",
    "Ή": "h",
    "І": "i",
    "Ј": "j",
    "К": "k",
    "М": "m",
    "Н": "h",
    "О": "o",
    "Р": "p",
    "Ѕ": "s",
    "Т": "t",
    "У": "y",
    "Х": "x",
    "Ԛ": "q",
    "Ԁ": "d",
    "Ф": "o",
    # Greek
    "α": "a",
    "β": "b",
    "ε": "e",
    "ι": "i",
    "κ": "k",
    "ο": "o",
    "ρ": "p",
    "τ": "t",
    "υ": "u",
    "ν": "v",
    "χ": "x",
    "γ": "y",
    "ζ": "z",
    "η": "n",
    "Α": "a",
    "Β": "b",
    "Ε": "e",
    "Ζ": "z",
    "Η": "h",
    "Ι": "i",
    "Κ": "k",
    "Μ": "m",
    "Ν": "n",
    "Ο": "o",
    "Ρ": "p",
    "Τ": "t",
    "Υ": "y",
    "Χ": "x",
    # Armenian and other single-script lookalikes ("ԁ" is already mapped above)
    "օ": "o",
    "ո": "n",
    "ս": "u",
    "գ": "q",
    # Latin variants that NFKC does not fold to plain ASCII
    "ł": "l",
    "ø": "o",
    "đ": "d",
    "ħ": "h",
    "ı": "i",
    "ȷ": "j",
}

_TRANSLATION = str.maketrans(_CONFUSABLES)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

_CORPORATE_SUFFIXES: frozenset[str] = frozenset(
    {
        "pvt",
        "private",
        "ltd",
        "limited",
        "llp",
        "llc",
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "co",
        "company",
        "plc",
        "gmbh",
        "bv",
        "sa",
        "ag",
        "pty",
        "srl",
        "spa",
        "oy",
        "ab",
        "as",
        "nv",
    }
)


def fold_confusables(text: str) -> str:
    """Map visually confusable codepoints onto their Latin equivalents.

    Applied after NFKC, which already handles fullwidth forms, ligatures, and
    most compatibility variants. This table covers what NFKC deliberately does
    not: characters from other scripts that merely *look* like Latin letters.
    """
    return text.translate(_TRANSLATION)


def skeleton(name: str) -> str:
    """Reduce a name to a comparable form.

    Two names with the same skeleton are visually indistinguishable to a person
    reading them in a payment confirmation. That is the property we need: not
    "are these the same company", which requires judgement, but "could a human
    tell these apart", which does not.

    The pipeline is NFKC, casefold, strip combining marks, fold confusables,
    then drop everything that is not a letter or digit.

    >>> skeleton("Amazon Web Services India Pvt Ltd") == skeleton("Аmazon Web Services India Pvt Ltd")
    True
    """
    normalized = unicodedata.normalize("NFKC", name).casefold()
    decomposed = unicodedata.normalize("NFD", normalized)
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    folded = fold_confusables(without_marks)
    return _NON_ALNUM.sub("", folded)


def trading_skeleton(name: str) -> str:
    """Like :func:`skeleton`, but also drops corporate-form suffixes.

    "Razorpay Software Private Limited" and "Razorpay Software Pvt Ltd" are the
    same counterparty written two ways. Used for the *stretch* typosquat check
    (SPF-002), never for the homoglyph check — SPF-001 must fire on codepoint
    substitution alone, and dropping suffixes here would blur what it proves.
    """
    normalized = unicodedata.normalize("NFKC", name).casefold()
    decomposed = unicodedata.normalize("NFD", normalized)
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    folded = fold_confusables(without_marks)
    words = [w for w in re.split(r"[^a-z0-9]+", folded) if w]
    kept = [w for w in words if w not in _CORPORATE_SUFFIXES]
    return "".join(kept or words)


def is_confusable_with(left: str, right: str) -> bool:
    """Whether two names are visually indistinguishable but not byte-identical.

    Byte-identical names are *not* confusable — they are the same name. This
    distinction is what stops the homoglyph predicate firing on every legitimate
    payment to an allowlisted merchant.
    """
    return left != right and skeleton(left) == skeleton(right)


def contains_non_latin_script(text: str) -> bool:
    """Whether ``text`` mixes scripts, a strong signal of a spoofing attempt.

    Reported as supporting evidence in the report rather than used as the
    predicate itself: plenty of legitimate Indian merchant names are written in
    Devanagari, and refusing them would be a false positive with real cost.
    """
    # `unicodedata.name` is given a default rather than wrapped in try/except:
    # a swallowed exception here would be indistinguishable from "no non-Latin
    # script found", which is the answer that lets a spoof through.
    return any(
        char.isalpha() and not unicodedata.name(char, "UNNAMED").startswith("LATIN")
        for char in text
    )
