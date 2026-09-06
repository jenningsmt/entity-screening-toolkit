"""Institution-name matching for reconciliation.

Different problem from concern-list screening (screening/lists.py): there the
list is 1.2M rows and needs a blocking step; here a declared set is tens of
affiliations, so every discovered name is compared against every declared
one directly. Same scorer though -- resolution/matcher.py:score_pair -- with
an institution-name preparation step first (governing-board affix, campus
parentheticals, common abbreviations), mirroring how Section 117 prepares
names before its own two-stage match.

RECONCILIATION_THRESHOLD is 0.90, verified against real declared-vs-discovered
institution-name pairs (docs/data_sources.md's reconciliation-threshold
entry). The failure economics are asymmetric: a false *negative* on the
match generates a spurious omission finding an analyst dismisses in one
click; a false *positive* silently suppresses a real omission -- the
statutory test itself. So the threshold sits above the highest observed
score for a genuinely-distinct pair (University of Science and Technology of
China vs ...Beijing, 0.876), not at a midpoint. Near-matches between
PARTIAL_MATCH_FLOOR and the threshold are surfaced as
PARTIAL_MATCH_BELOW_THRESHOLD findings with the near-match shown, not as a
stark omission.
"""
from __future__ import annotations

from dataclasses import dataclass

from entity_screening.common.schema import DeclaredAffiliation
from entity_screening.resolution.matcher import score_pair
from entity_screening.resolution.normalize import normalize_institution_name

RECONCILIATION_THRESHOLD = 0.90
# Below the match threshold but close enough that a declared affiliation is
# plausibly the same one -- classified PARTIAL_MATCH_BELOW_THRESHOLD rather
# than a stark omission, with the near-match shown in `nearest_declared`.
# 0.85, not lower: two unrelated "<X> University" names share the "university"
# token and land around 0.74-0.82 on token-sort (Fudan vs Stanford, 0.74;
# Peking vs Tsinghua, 0.78), which is not a real near-match. `nearest_declared`
# is populated regardless of this band, so the analyst sees a weak match
# either way -- this only sets the row's headline classification. Provisional,
# same status as RECONCILIATION_THRESHOLD (docs/data_sources.md).
PARTIAL_MATCH_FLOOR = 0.85


@dataclass(frozen=True)
class NameMatch:
    declared: DeclaredAffiliation
    confidence: float
    match_basis: str
    cleared: bool


def best_declared_match(
    discovered_institution_name: str,
    declared_affiliations: list[DeclaredAffiliation],
    threshold: float = RECONCILIATION_THRESHOLD,
) -> NameMatch | None:
    """The best-scoring declared affiliation for a discovered institution
    name, or None if there are no declared affiliations. `cleared` is whether
    it reached `threshold` -- the caller still gets the near-miss when it did
    not, so a partial match is visible rather than silently dropped."""
    if not declared_affiliations:
        return None
    prepared_discovered = normalize_institution_name(discovered_institution_name)
    best: NameMatch | None = None
    for declared in declared_affiliations:
        candidate = score_pair(
            prepared_discovered, normalize_institution_name(declared.institution_name)
        )
        if best is None or candidate.confidence > best.confidence:
            best = NameMatch(
                declared=declared,
                confidence=candidate.confidence,
                match_basis=candidate.match_basis,
                cleared=candidate.confidence >= threshold,
            )
    return best


def ranked_declared_matches(
    discovered_institution_name: str,
    declared_affiliations: list[DeclaredAffiliation],
    limit: int = 3,
    threshold: float = RECONCILIATION_THRESHOLD,
) -> list[NameMatch]:
    """The top `limit` declared affiliations by confidence -- what a Finding's
    `nearest_declared` records so a near-miss is auditable."""
    prepared_discovered = normalize_institution_name(discovered_institution_name)
    scored: list[NameMatch] = []
    for declared in declared_affiliations:
        candidate = score_pair(
            prepared_discovered, normalize_institution_name(declared.institution_name)
        )
        scored.append(
            NameMatch(
                declared=declared,
                confidence=candidate.confidence,
                match_basis=candidate.match_basis,
                cleared=candidate.confidence >= threshold,
            )
        )
    scored.sort(key=lambda m: m.confidence, reverse=True)
    return scored[:limit]
