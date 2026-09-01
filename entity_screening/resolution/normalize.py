"""Name normalization: corporate suffixes, acronyms, transliteration.

Epic B acceptance criteria: fuzzy matching must handle abbreviation/acronym
variants, transliteration variants, and corporate-suffix normalization —
these three helpers are what the matcher builds on.
"""
from __future__ import annotations

import re
import unicodedata

CORPORATE_SUFFIXES = (
    "incorporated",
    "corporation",
    "company",
    "limited",
    "l l c",
    "l l p",
    "gmbh",
    "plc",
    "inc",
    "corp",
    "co",
    "ltd",
    "llc",
    "llp",
    "ag",
    "sa",
    "spa",
    "bv",
    "nv",
    "kk",
)

_SUFFIX_PATTERN = re.compile(
    r"[,\.]?\s*\b("
    + "|".join(re.escape(s) for s in sorted(CORPORATE_SUFFIXES, key=len, reverse=True))
    + r")\b\.?\s*$",
    re.IGNORECASE,
)

_NON_ALNUM = re.compile(r"[^a-z0-9 ]")

STOPWORDS = {"of", "the", "and", "for", "at", "in", "on"}


def strip_corporate_suffix(name: str) -> str:
    """Repeatedly strips trailing corporate-form suffixes (Inc., LLC, Ltd., ...)."""
    previous = None
    current = name.strip()
    while previous != current:
        previous = current
        current = _SUFFIX_PATTERN.sub("", current).strip()
    return current


def transliterate(name: str) -> str:
    """Folds accented characters down to their plain-ASCII base form."""
    normalized = unicodedata.normalize("NFKD", name)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def acronym(name: str) -> str:
    """Builds the acronym of a name's significant words (skips short stopwords)."""
    words = re.findall(r"[A-Za-z0-9]+", name)
    letters = [w[0] for w in words if w.lower() not in STOPWORDS]
    return "".join(letters).upper()


def normalize_for_matching(name: str) -> str:
    """Canonical form used as matcher input: transliterated, suffix-stripped,
    lowercased, alphanumeric-only, whitespace-collapsed."""
    text = transliterate(name)
    text = strip_corporate_suffix(text)
    text = text.lower()
    text = _NON_ALNUM.sub(" ", text)
    return " ".join(text.split())
