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
    """`chains` holds every distinct real path from the start LEI to a leaf
    (a node with no further real edge, within `max_depth`) -- plural because
    the underlying graph can genuinely branch: GLEIF's Level 2 data does
    contain entities with multiple active `IS_DIRECTLY_CONSOLIDATED_BY`
    edges, and flattening that into one tuple (this type's original shape)
    produced an ordering artifact that neither existed in the data nor
    reliably picked the "real" chain — see Finding 7 in the 2026-09-02
    codebase evaluation. Each element of `chains` does NOT include the start
    LEI itself, matching the pre-branching-fix convention (a caller building
    a full path does `(start_lei, *one_chain)`, exactly as
    `flagging.py:flag_from_match` does).

    `truncated=True` means at least one branch of the walk found a real link
    beyond `max_depth` — the caller must not treat any `chains[i][-1]` as a
    confirmed final node when this is True. This is deliberately not left
    for a caller to infer from chain length: that comparison can't tell "this
    branch is exactly this long and complete" apart from "there's more we
    didn't look at" (see the V2 plan's acceptance criteria) — `parent_chain()`
    below peeks one hop past `max_depth` internally specifically so
    `truncated` is a fact, not a guess.
    """

    chains: tuple[tuple[str, ...], ...]
    truncated: bool


def parent_chain(
    conn: duckdb.DuckDBPyConnection,
    lei: str,
    direction: str = "up",
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> ParentChain:
    """Walks `IS_DIRECTLY_CONSOLIDATED_BY` edges from `lei`, toward parents
    (`direction="up"`) or subsidiaries (`direction="down"`), returning every
    distinct real path up to `max_depth` hops. Epic C's "traversal depth and
    direction... both queryable" criterion, as an actual callable capability
    that also doesn't collapse a branching graph into one arbitrary tuple
    (see `ParentChain`'s docstring).

    Each recursion step carries its own full path (not just the current
    node) for two reasons: it lets `NOT list_contains(path, ...)` guard
    against cycles per-branch (a real A<->B cycle terminates instead of
    recursing forever, and does not falsely block an *unrelated* branch that
    happens to revisit a node another branch already used), and it lets the
    Python-side pass below tell a true dead end apart from an intermediate
    node on a longer branch -- see the `parent_paths` comment.

    Recurses one hop past `max_depth` internally purely to determine
    `truncated` correctly, exactly as the pre-branching-fix version did.
    """
    if direction not in ("up", "down"):
        raise ValueError(f"direction must be 'up' or 'down', got {direction!r}")

    start_col, end_col = ("start_lei", "end_lei") if direction == "up" else ("end_lei", "start_lei")

    rows = conn.execute(
        f"""
        WITH RECURSIVE walk(node, path, depth) AS (
            SELECT ? AS node, [?] AS path, 0 AS depth
            UNION ALL
            SELECT r.{end_col}, list_append(w.path, r.{end_col}), w.depth + 1
            FROM walk w
            JOIN gleif_relationships r ON r.{start_col} = w.node
            WHERE r.relationship_type = 'IS_DIRECTLY_CONSOLIDATED_BY'
              AND w.depth <= ?
              AND NOT list_contains(w.path, r.{end_col})
        )
        SELECT path, depth FROM walk WHERE depth > 0 ORDER BY depth
        """,
        [lei, lei, max_depth],
    ).fetchall()

    truncated = any(depth > max_depth for _path, depth in rows)
    reportable = [(tuple(path), depth) for path, depth in rows if depth <= max_depth]

    # A reportable row is a chain endpoint worth returning unless some OTHER
    # reportable row is its direct one-hop continuation -- i.e. unless this
    # row's own path is some other row's "parent path" (that row's path minus
    # its last element). This correctly handles all three real cases: a
    # linear chain's true dead end (no continuation exists at all -> kept);
    # an intermediate node on a longer within-budget branch (a deeper
    # reportable continuation exists -> dropped, the longer chain reports it
    # instead); and a node sitting at exactly max_depth with a real link
    # beyond it (that continuation was peeked but excluded from `reportable`
    # since its depth exceeds max_depth, so this node has no reportable
    # continuation and is correctly kept as the chain's reported endpoint --
    # `truncated=True` is what signals there's more beyond it, not omission).
    parent_paths = {path[:-1] for path, _depth in reportable}
    chains = tuple(path[1:] for path, _depth in reportable if path not in parent_paths)

    return ParentChain(chains=chains, truncated=truncated)


def ultimate_parent(
    conn: duckdb.DuckDBPyConnection, lei: str, max_depth: int = DEFAULT_MAX_DEPTH
) -> tuple[tuple[str, ...], bool] | None:
    """Returns `(ultimate_parent_leis, truncated)` -- plural because a real
    ownership graph can genuinely branch into more than one ultimate parent
    (see `ParentChain`'s docstring); `None` if `lei` has no parent at all.
    Checks GLEIF's own published `IS_ULTIMATELY_CONSOLIDATED_BY` edge(s)
    first (GLEIF often computes and publishes this directly as a shortcut);
    falls back to walking `IS_DIRECTLY_CONSOLIDATED_BY` to the end of every
    branch. Never treats a truncated walk's leaf nodes as confirmed final.
    De-duplicates by LEI (a diamond-shaped graph can reach the same ultimate
    parent via more than one distinct path) while preserving first-seen order.
    """
    direct_ultimate_rows = conn.execute(
        "SELECT DISTINCT end_lei FROM gleif_relationships "
        "WHERE start_lei = ? AND relationship_type = 'IS_ULTIMATELY_CONSOLIDATED_BY'",
        [lei],
    ).fetchall()
    if direct_ultimate_rows:
        return tuple(row[0] for row in direct_ultimate_rows), False

    result = parent_chain(conn, lei, direction="up", max_depth=max_depth)
    if not result.chains:
        return None
    seen: list[str] = []
    for chain in result.chains:
        if chain[-1] not in seen:
            seen.append(chain[-1])
    return tuple(seen), result.truncated
