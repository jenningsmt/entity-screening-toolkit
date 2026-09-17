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
    """Builds the acronym of a name's significant words (skips short stopwords).

    Word-splits on `\\w+`, not the old ASCII-only `[A-Za-z0-9]+` (S9) --
    Python's `re` is Unicode-aware by default, so a letter outside the
    Latin-1 combining range (Turkish dotless i, Cyrillic, CJK, ...) no
    longer fragments a word into two, which used to build a wrong,
    shorter acronym (confirmed: "Akın Alptuna" used to acronym to "ANA",
    not "AA", because transliterate() does not fold "ı" away -- it's a
    distinct base letter, not an accented one)."""
    words = re.findall(r"\w+", name)
    letters = [w[0] for w in words if w.lower() not in STOPWORDS]
    return "".join(letters).upper()


def normalize_for_matching(name: str, *, strip_suffix: bool = True) -> str:
    """Canonical form used as matcher input: transliterated, optionally
    suffix-stripped, lowercased, alphanumeric-only, whitespace-collapsed.

    `strip_suffix=False` (S9) is for a person-aware caller: a person's
    surname can collide with a corporate-suffix token ("Co", "Sa", ...),
    and stripping it corrupts the comparison -- see
    `resolution/matcher.py:score_pair`'s `skip_org_heuristics`."""
    text = transliterate(name)
    if strip_suffix:
        text = strip_corporate_suffix(text)
    text = text.lower()
    text = _NON_ALNUM.sub(" ", text)
    return " ".join(text.split())


_LEADING_GOVERNANCE_AFFIX = re.compile(
    r"^\s*(the\s+)?(board of )?regents(,)?\s+(of\s+(the\s+)?)?", re.IGNORECASE
)
_LEADING_TRUSTEES_AFFIX = re.compile(r"^\s*trustees\s+of\s+(the\s+)?", re.IGNORECASE)
_LEADING_ARTICLE = re.compile(r"^\s*the\s+", re.IGNORECASE)
_TRAILING_BOARD_OF_TRUSTEES = re.compile(r"\s*,?\s*board of trustees\s*$", re.IGNORECASE)
_TRAILING_THE_PAREN = re.compile(r"\s*\(the\)\s*$", re.IGNORECASE)


_INSTITUTION_ABBREVIATIONS = {
    "univ": "university",
    "inst": "institute",
    "tech": "technology",
    "natl": "national",
    "sci": "science",
    "acad": "academy",
    "dept": "department",
    "lab": "laboratory",
    "labs": "laboratories",
    "intl": "international",
    "assoc": "association",
}
_PARENTHETICAL = re.compile(r"\([^)]*\)")


def expand_institution_abbreviations(name: str) -> str:
    """Expands the handful of institution-name abbreviations that otherwise
    sink a fuzzy match ('Zhejiang Univ' vs 'Zhejiang University' scores 0.81
    on token_sort; expanded, 1.0). Same domain-specific-normalization spirit
    as strip_institutional_governance_affix -- kept out of
    normalize_for_matching (used by every source) because it is only wanted
    where two independently-authored institution names are being compared."""
    parts = re.split(r"(\W+)", name)
    return "".join(_INSTITUTION_ABBREVIATIONS.get(p.lower(), p) for p in parts)


def normalize_institution_name(name: str) -> str:
    """Institution-name preparation for the HB 127 reconciliation matcher
    (entity_screening/reconciliation/match.py): drop a governing-board affix,
    drop a parenthetical campus qualifier ('... (Shenzhen)'), expand common
    abbreviations. Verified against real declared-vs-discovered name pairs --
    see docs/data_sources.md's reconciliation-threshold entry."""
    name = strip_institutional_governance_affix(name)
    name = _PARENTHETICAL.sub("", name)
    name = expand_institution_abbreviations(name)
    return " ".join(name.split())


def strip_institutional_governance_affix(name: str) -> str:
    """Strips higher-ed governing-board naming conventions.

    Section 117 cross-check use only (see entity_screening/screening/
    section_117.py's module docstring for why this isn't folded into
    normalize_for_matching, used by every other source): NSF award data often
    records a legal awardee name under its governing board ("Regents of the
    University of Idaho", "Trustees of Boston University", "The University of
    Central Florida Board of Trustees") where Section 117's `School Name`
    uses the common name ("University of Idaho", "Boston University",
    "University of Central Florida"). Verified against real pairs pulled from
    both sources (docs/plans/2026-09-01-section-117-foreign-gift-disclosure-
    cross-check.md): without this step these score 0.72-0.81 via
    resolution/matcher.py:score_pair and land in a different 3-character
    block; with it, 5 of 6 real pairs go to a clean 1.0 in the same block. A
    residual system-consortium "obo" naming style (e.g. "Board of Regents,
    NSHE, obo University of Nevada, Reno") stays a documented miss — see
    docs/methodology.md.
    """
    text = name
    text = _LEADING_GOVERNANCE_AFFIX.sub("", text)
    text = _LEADING_TRUSTEES_AFFIX.sub("", text)
    text = _LEADING_ARTICLE.sub("", text)
    text = _TRAILING_BOARD_OF_TRUSTEES.sub("", text)
    text = _TRAILING_THE_PAREN.sub("", text)
    return text.strip()
