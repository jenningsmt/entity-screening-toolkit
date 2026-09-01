"""SQL-blocked, Python-scored resolution of a canonical entity name to a GLEIF LEI.

Mirrors `screening/lists.py:EntityOfConcernList.candidates_for()`'s blocking
philosophy — narrow candidates cheaply, then score with the real matcher —
but backed by a SQL WHERE clause against the bulk-loaded `gleif_lei` table
instead of an in-memory Python block index, because GLEIF's ~3.3M rows make
full in-memory blocking disproportionate at this scale (see the V2 plan).
"""
from __future__ import annotations

import duckdb

from entity_screening.common.schema import MatchStatus, OwnershipMatch
from entity_screening.resolution.matcher import DEFAULT_THRESHOLD, score_pair
from entity_screening.resolution.normalize import normalize_for_matching

DEFAULT_BLOCK_SIZE = 3


def resolve_entity_to_lei(
    conn: duckdb.DuckDBPyConnection,
    entity_id: str,
    canonical_name: str,
    threshold: float = DEFAULT_THRESHOLD,
    block_size: int = DEFAULT_BLOCK_SIZE,
) -> OwnershipMatch | None:
    """Resolves a name to the best-matching ACTIVE GLEIF LEI record above
    `threshold`, or None. `block_size` is a parameter, not a hardcoded
    literal copied from OpenSanctions' scale — the V2 plan's acceptance
    criteria call for a real timing pass against the full ~3.3M-row GLEIF
    file before trusting 3 chars is wide enough; widening it is meant to be
    a one-line change if that measurement says otherwise.

    Never returns a bare LEI string — this fuzzy match is the foundation
    every other ownership-graph result inherits uncertainty from, so it
    always carries a confidence score and a MatchStatus, exactly like every
    other match in this codebase.
    """
    prefix = normalize_for_matching(canonical_name)[:block_size]
    if not prefix:
        return None

    candidates = conn.execute(
        "SELECT lei, legal_name, legal_jurisdiction FROM gleif_lei "
        "WHERE normalized_name_prefix = ? AND entity_status = 'ACTIVE'",
        [prefix],
    ).fetchall()

    best_candidate = None
    best_lei = None
    best_jurisdiction = None
    for lei, legal_name, legal_jurisdiction in candidates:
        candidate = score_pair(canonical_name, legal_name)
        if best_candidate is None or candidate.confidence > best_candidate.confidence:
            best_candidate = candidate
            best_lei = lei
            best_jurisdiction = legal_jurisdiction

    if best_candidate is None or best_candidate.confidence < threshold:
        return None

    return OwnershipMatch(
        entity_id=entity_id,
        lei=best_lei,
        legal_name=best_candidate.right_name,
        legal_jurisdiction=best_jurisdiction or "",
        confidence=best_candidate.confidence,
        match_basis=best_candidate.match_basis,
        status=MatchStatus.CANDIDATE_MATCH,
    )
