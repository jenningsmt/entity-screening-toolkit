"""Ownership-graph traversal over the GLEIF Level 2 relationship data.

DuckDB's `WITH RECURSIVE` CTE support (verify against the installed version
at implementation time) does the actual graph walk — docs/requirements.md
Section 7 already decided parent/subsidiary traversal is a SQL join pattern
DuckDB handles natively, no separate graph database needed.
"""
from __future__ import annotations

from dataclasses import dataclass

import duckdb

DEFAULT_MAX_DEPTH = 10


@dataclass(frozen=True)
class ParentChain:
    """`truncated=True` means the walk found a real link beyond `max_depth` —
    the caller must not treat `chain[-1]` as a confirmed final node when this
    is True. This is deliberately not left for a caller to infer from
    `len(chain) == max_depth`: that comparison can't tell "the chain is
    exactly this long and complete" apart from "there's more we didn't look
    at" (see the V2 plan's acceptance criteria) — `parent_chain()` below
    peeks one hop past `max_depth` specifically so `truncated` is a fact, not
    a guess.
    """

    chain: tuple[str, ...]
    truncated: bool


def parent_chain(
    conn: duckdb.DuckDBPyConnection,
    lei: str,
    direction: str = "up",
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> ParentChain:
    """Walks `IS_DIRECTLY_CONSOLIDATED_BY` edges from `lei`, toward parents
    (`direction="up"`) or subsidiaries (`direction="down"`), returning up to
    `max_depth` hops. Epic C's "traversal depth and direction... both
    queryable" criterion, as an actual callable capability.

    Recurses one hop past `max_depth` internally (not exposed in `chain`)
    purely to determine `truncated` correctly — see `ParentChain`'s
    docstring for why a bare length comparison isn't good enough.
    """
    if direction not in ("up", "down"):
        raise ValueError(f"direction must be 'up' or 'down', got {direction!r}")

    start_col, end_col = ("start_lei", "end_lei") if direction == "up" else ("end_lei", "start_lei")

    rows = conn.execute(
        f"""
        WITH RECURSIVE walk(node, depth) AS (
            SELECT ?, 0
            UNION ALL
            SELECT r.{end_col}, w.depth + 1
            FROM walk w
            JOIN gleif_relationships r ON r.{start_col} = w.node
            WHERE r.relationship_type = 'IS_DIRECTLY_CONSOLIDATED_BY'
              AND w.depth <= ?
        )
        SELECT node, depth FROM walk WHERE depth > 0 ORDER BY depth
        """,
        [lei, max_depth],
    ).fetchall()

    chain = tuple(node for node, depth in rows if depth <= max_depth)
    truncated = any(depth > max_depth for _node, depth in rows)
    return ParentChain(chain=chain, truncated=truncated)


def ultimate_parent(
    conn: duckdb.DuckDBPyConnection, lei: str, max_depth: int = DEFAULT_MAX_DEPTH
) -> tuple[str, bool] | None:
    """Returns `(ultimate_parent_lei, truncated)`, or `None` if `lei` has no
    parent at all. Checks GLEIF's own published `IS_ULTIMATELY_CONSOLIDATED_BY`
    edge first (GLEIF often computes and publishes this directly as a
    shortcut); falls back to walking `IS_DIRECTLY_CONSOLIDATED_BY` to the end
    of the chain. Never treats a truncated walk's last node as confirmed.
    """
    direct_ultimate = conn.execute(
        "SELECT end_lei FROM gleif_relationships "
        "WHERE start_lei = ? AND relationship_type = 'IS_ULTIMATELY_CONSOLIDATED_BY'",
        [lei],
    ).fetchone()
    if direct_ultimate:
        return direct_ultimate[0], False

    result = parent_chain(conn, lei, direction="up", max_depth=max_depth)
    if not result.chain:
        return None
    return result.chain[-1], result.truncated
