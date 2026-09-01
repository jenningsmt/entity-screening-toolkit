"""Fuzzy name matching: every comparison returns a scored MatchCandidate,
never a bare boolean (Epic B acceptance criterion)."""
from __future__ import annotations

from rapidfuzz import fuzz

from entity_screening.common.schema import MatchCandidate
from entity_screening.resolution.normalize import acronym, normalize_for_matching, strip_corporate_suffix, transliterate

DEFAULT_THRESHOLD = 0.80


def score_pair(left_name: str, right_name: str) -> MatchCandidate:
    """Returns the best-scoring MatchCandidate across several match strategies,
    tried in order of specificity: normalized-exact, acronym, fuzzy token-sort."""
    left_norm = normalize_for_matching(left_name)
    right_norm = normalize_for_matching(right_name)

    if left_norm and left_norm == right_norm:
        return MatchCandidate(
            left_name=left_name,
            right_name=right_name,
            confidence=1.0,
            match_basis="normalized_exact",
        )

    # Acronyms are built from the corporate-suffix-stripped name — otherwise
    # "International Business Machines Corporation" acronyms to "IBMC", not
    # "IBM", and never matches the real-world acronym.
    left_acronym = acronym(strip_corporate_suffix(transliterate(left_name))).lower()
    right_acronym = acronym(strip_corporate_suffix(transliterate(right_name))).lower()
    right_norm_compact = right_norm.replace(" ", "")
    left_norm_compact = left_norm.replace(" ", "")
    if left_acronym and len(left_acronym) > 1 and left_acronym == right_norm_compact:
        return MatchCandidate(
            left_name=left_name, right_name=right_name, confidence=0.9, match_basis="acronym"
        )
    if right_acronym and len(right_acronym) > 1 and right_acronym == left_norm_compact:
        return MatchCandidate(
            left_name=left_name, right_name=right_name, confidence=0.9, match_basis="acronym"
        )

    fuzzy_score = fuzz.token_sort_ratio(left_norm, right_norm) / 100.0
    return MatchCandidate(
        left_name=left_name,
        right_name=right_name,
        confidence=fuzzy_score,
        match_basis="fuzzy_token_sort",
    )


def is_candidate_match(candidate: MatchCandidate, threshold: float = DEFAULT_THRESHOLD) -> bool:
    """Whether a MatchCandidate clears the confidence bar to be treated as a hit.

    Internal routing/filtering only — callers must keep the full MatchCandidate
    (with its score) alongside this boolean, never surface the boolean alone.
    """
    return candidate.confidence >= threshold
