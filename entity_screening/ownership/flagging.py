"""Computes foreign-control flags: an entity whose ultimate parent (per GLEIF
Level 2 data) is registered in a different jurisdiction than the entity
itself (Epic C's specific acceptance criterion).
"""
from __future__ import annotations

import duckdb

from entity_screening.common.attribution import attribution_for
from entity_screening.common.schema import ForeignControlFlag, MatchStatus, OwnershipMatch
from entity_screening.ownership.graph import DEFAULT_MAX_DEPTH, parent_chain


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
                    # Section 10's licence NFR: attribution reaches every
                    # output, not just a README. A ForeignControlFlag is now
                    # a first-class evidence payload on an HB 127 Finding
                    # (use-case-01), exported in the investigative file --
                    # GLEIF's attribution rides in the evidence the same way
                    # a ScreeningHit's source_attribution does.
                    "source_attribution": attribution_for("gleif_golden_copy"),
                },
                status=MatchStatus.CANDIDATE_MATCH,
            )
        )
    return flags
