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
) -> list[ForeignControlFlag]:
    """Returns zero, one, or more flags if `entity` resolves to an LEI with a
    known ultimate parent in a *different* jurisdiction than the entity
    itself; empty if the jurisdictions match, no LEI match clears
    `threshold`, or no parent relationship is known at all. More than one
    flag means a genuinely branching ownership graph (see
    `ownership/graph.py:ParentChain`'s docstring) — not a caller error.

    Resolves the LEI match itself — for a caller (like `pipeline.enrich_ownership`)
    that already has an `OwnershipMatch` in hand (e.g. because it also needs to
    persist every entity's match, flagged or not), call `flag_from_match`
    directly instead to avoid resolving the same entity twice.
    """
    match = resolve_entity_to_lei(
        conn, entity.entity_id, entity.canonical_name, threshold, block_size=block_size
    )
    if match is None:
        return []
    return flag_from_match(conn, match, max_depth=max_depth)


def flag_from_match(
    conn: duckdb.DuckDBPyConnection,
    match: OwnershipMatch,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> list[ForeignControlFlag]:
    """The actual flagging logic, given an already-resolved `OwnershipMatch`.

    Returns one `ForeignControlFlag` per distinct foreign ultimate parent,
    not a single arbitrarily-picked one (Finding 7) — collapsing a branching
    graph into one flag both under-reports genuine foreign-control findings
    and, worse, wrote a `relationship_path` that didn't exist in the data
    (an ordering artifact of the old flattened-tuple return type, presented
    as evidence). Mirrors the house principle already established by
    `bibliometric/author_resolve.py:disambiguate_pi_to_openalex_author`,
    which returns every tied candidate rather than forcing a pick — same
    reasoning, same shape.

    Uses `parent_chain()` directly (not `ultimate_parent()`'s GLEIF-shortcut
    check) because each flag's evidence needs its own full path, not just
    the endpoint — `relationship_path` and `truncated` are both surfaced in
    `evidence` so a reviewer can see exactly how far that branch's walk
    actually went, never an unqualified "this is the confirmed ultimate
    parent" claim from a chain that might continue further.
    """
    result = parent_chain(conn, match.lei, direction="up", max_depth=max_depth)
    if not result.chains:
        return []

    flags: list[ForeignControlFlag] = []
    seen_ultimate_leis: set[str] = set()
    for chain in result.chains:
        ultimate_lei = chain[-1]
        # A diamond-shaped graph can reach the same ultimate parent via more
        # than one distinct path -- one flag per distinct *parent*, not per
        # path, so a second convergent path doesn't produce a duplicate flag.
        if ultimate_lei in seen_ultimate_leis:
            continue

        parent_row = conn.execute(
            "SELECT legal_name, legal_jurisdiction FROM gleif_lei WHERE lei = ?", [ultimate_lei]
        ).fetchone()
        if parent_row is None:
            continue
        parent_name, parent_jurisdiction = parent_row

        if parent_jurisdiction == match.legal_jurisdiction:
            continue

        seen_ultimate_leis.add(ultimate_lei)
        full_path = (match.lei, *chain)
        flags.append(
            ForeignControlFlag(
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
        )
    return flags
