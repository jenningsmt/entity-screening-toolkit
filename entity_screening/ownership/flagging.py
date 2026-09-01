"""Computes foreign-control flags: an entity whose ultimate parent (per GLEIF
Level 2 data) is registered in a different jurisdiction than the entity
itself (Epic C's specific acceptance criterion).
"""
from __future__ import annotations

import duckdb

from entity_screening.common.schema import (
    ForeignControlFlag,
    MatchStatus,
    OwnershipMatch,
    ResolvedEntity,
)
from entity_screening.ownership.graph import DEFAULT_MAX_DEPTH, parent_chain
from entity_screening.ownership.match import DEFAULT_BLOCK_SIZE, resolve_entity_to_lei
from entity_screening.resolution.matcher import DEFAULT_THRESHOLD


def compute_foreign_control_flag(
    conn: duckdb.DuckDBPyConnection,
    entity: ResolvedEntity,
    threshold: float = DEFAULT_THRESHOLD,
    max_depth: int = DEFAULT_MAX_DEPTH,
    block_size: int = DEFAULT_BLOCK_SIZE,
) -> ForeignControlFlag | None:
    """Returns a flag if `entity` resolves to an LEI with a known ultimate
    parent in a *different* jurisdiction; `None` if the jurisdictions match,
    no LEI match clears `threshold`, or no parent relationship is known at all.

    Resolves the LEI match itself — for a caller (like `pipeline.enrich_ownership`)
    that already has an `OwnershipMatch` in hand (e.g. because it also needs to
    persist every entity's match, flagged or not), call `flag_from_match`
    directly instead to avoid resolving the same entity twice.
    """
    match = resolve_entity_to_lei(
        conn, entity.entity_id, entity.canonical_name, threshold, block_size=block_size
    )
    if match is None:
        return None
    return flag_from_match(conn, match, max_depth=max_depth)


def flag_from_match(
    conn: duckdb.DuckDBPyConnection,
    match: OwnershipMatch,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> ForeignControlFlag | None:
    """The actual flagging logic, given an already-resolved `OwnershipMatch`.

    Uses `parent_chain()` directly (not `ultimate_parent()`'s GLEIF-shortcut
    check) because the flag's evidence needs the full path, not just the
    endpoint — `relationship_path` and `truncated` are both surfaced in
    `evidence` so a reviewer can see exactly how far the walk actually went,
    never an unqualified "this is the confirmed ultimate parent" claim from a
    chain that might continue further.
    """
    result = parent_chain(conn, match.lei, direction="up", max_depth=max_depth)
    if not result.chain:
        return None

    ultimate_lei = result.chain[-1]
    parent_row = conn.execute(
        "SELECT legal_name, legal_jurisdiction FROM gleif_lei WHERE lei = ?", [ultimate_lei]
    ).fetchone()
    if parent_row is None:
        return None
    parent_name, parent_jurisdiction = parent_row

    if parent_jurisdiction == match.legal_jurisdiction:
        return None

    full_path = (match.lei, *result.chain)
    return ForeignControlFlag(
        entity_id=match.entity_id,
        entity_lei=match.lei,
        entity_jurisdiction=match.legal_jurisdiction,
        ultimate_parent_lei=ultimate_lei,
        ultimate_parent_name=parent_name,
        ultimate_parent_jurisdiction=parent_jurisdiction,
        relationship_path=full_path,
        match_confidence=match.confidence,
        evidence={
            "lei_match_basis": match.match_basis,
            "relationship_path": list(full_path),
            "truncated": result.truncated,
        },
        status=MatchStatus.CANDIDATE_MATCH,
    )
