import datetime
from pathlib import Path

from entity_screening.common import storage
from entity_screening.ingestion.base import IngestionErrorLog
from entity_screening.ownership.graph import parent_chain, ultimate_parent
from entity_screening.ownership.ingest import load_gleif_level2

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _conn_with_relationships_loaded(tmp_path):
    conn = storage.connect(tmp_path / "test.duckdb")
    error_log = IngestionErrorLog(tmp_path / "errors.jsonl")
    load_gleif_level2(
        conn, FIXTURES_DIR / "sample_gleif_relationships.csv", datetime.date(2026, 8, 1), error_log
    )
    error_log.close()
    return conn


def test_parent_chain_walks_direct_parent_edges_upward(tmp_path):
    conn = _conn_with_relationships_loaded(tmp_path)

    result = parent_chain(conn, "LEI-SUB", direction="up")

    assert result.chains == (("LEI-DIRECT-PARENT", "LEI-ULTIMATE-DE"),)
    assert result.truncated is False
    conn.close()


def test_parent_chain_direction_down_walks_subsidiaries(tmp_path):
    conn = _conn_with_relationships_loaded(tmp_path)

    result = parent_chain(conn, "LEI-ULTIMATE-DE", direction="down")

    assert any("LEI-DIRECT-PARENT" in chain for chain in result.chains)
    assert result.truncated is False
    conn.close()


def test_parent_chain_not_truncated_when_it_ends_naturally(tmp_path):
    """The chain LEI-SUB -> LEI-DIRECT-PARENT -> LEI-ULTIMATE-DE genuinely
    ends there (no further parent) — this must not be misreported as
    truncated just because a caller picked a small max_depth that happens to
    exceed the real chain length."""
    conn = _conn_with_relationships_loaded(tmp_path)

    result = parent_chain(conn, "LEI-SUB", direction="up", max_depth=2)

    assert result.chains == (("LEI-DIRECT-PARENT", "LEI-ULTIMATE-DE"),)
    assert result.truncated is False
    conn.close()


def test_parent_chain_reports_truncated_when_a_real_link_exists_beyond_max_depth(tmp_path):
    """The regression case the plan's review specifically called out: a chain
    exactly as long as max_depth must not be confused with one that's cut off.
    LEI-CHAIN-START -> 01 -> ... -> 11 is 11 real hops; with max_depth=10 the
    11th hop (to LEI-CHAIN-11) exists and must be detected, not guessed at
    from len(chain) == max_depth alone -- and the chain up to the real
    truncation point must still be reported, not silently dropped just
    because it isn't a genuine graph leaf."""
    conn = _conn_with_relationships_loaded(tmp_path)

    result = parent_chain(conn, "LEI-CHAIN-START", direction="up", max_depth=10)

    assert len(result.chains) == 1
    assert len(result.chains[0]) == 10
    assert result.chains[0][-1] == "LEI-CHAIN-10"
    assert result.truncated is True
    conn.close()


def test_parent_chain_exactly_at_max_depth_is_not_truncated(tmp_path):
    """The other half of the same regression: if the real chain is EXACTLY
    max_depth long with nothing beyond it, truncated must be False — proving
    the one-hop-past-max_depth peek actually distinguishes the two cases
    rather than both reporting truncated=True."""
    conn = _conn_with_relationships_loaded(tmp_path)

    result = parent_chain(conn, "LEI-CHAIN-START", direction="up", max_depth=11)

    assert len(result.chains) == 1
    assert len(result.chains[0]) == 11
    assert result.chains[0][-1] == "LEI-CHAIN-11"
    assert result.truncated is False
    conn.close()


def test_parent_chain_empty_for_an_entity_with_no_parent(tmp_path):
    conn = _conn_with_relationships_loaded(tmp_path)

    result = parent_chain(conn, "LEI-NO-PARENT", direction="up")

    assert result.chains == ()
    assert result.truncated is False
    conn.close()


def test_parent_chain_reports_every_distinct_branch_of_a_branching_graph(tmp_path):
    """Finding 7: SUB has two direct parents (P1, P2), each with their own
    distinct ultimate parent -- the old flattened-tuple return type either
    picked one arbitrarily (via chain[-1]) or produced an ordering artifact
    that didn't exist in the data (via the flattened chain tuple itself)."""
    conn = storage.connect(tmp_path / "branching.duckdb")
    error_log = IngestionErrorLog(tmp_path / "branching_errors.jsonl")
    csv_path = tmp_path / "branching_relationships.csv"
    csv_path.write_text(
        "Relationship.StartNode.NodeID,Relationship.EndNode.NodeID,"
        "Relationship.RelationshipType,Relationship.RelationshipStatus\n"
        "LEI-BRANCH-SUB,LEI-BRANCH-P1,IS_DIRECTLY_CONSOLIDATED_BY,ACTIVE\n"
        "LEI-BRANCH-SUB,LEI-BRANCH-P2,IS_DIRECTLY_CONSOLIDATED_BY,ACTIVE\n"
        "LEI-BRANCH-P1,LEI-BRANCH-TOPA,IS_DIRECTLY_CONSOLIDATED_BY,ACTIVE\n"
        "LEI-BRANCH-P2,LEI-BRANCH-TOPB,IS_DIRECTLY_CONSOLIDATED_BY,ACTIVE\n",
        encoding="utf-8",
    )
    load_gleif_level2(conn, csv_path, datetime.date(2026, 8, 1), error_log)
    error_log.close()

    result = parent_chain(conn, "LEI-BRANCH-SUB", direction="up")

    assert set(result.chains) == {
        ("LEI-BRANCH-P1", "LEI-BRANCH-TOPA"),
        ("LEI-BRANCH-P2", "LEI-BRANCH-TOPB"),
    }
    assert result.truncated is False
    conn.close()


def test_parent_chain_cyclic_relationship_terminates_instead_of_repeating(tmp_path):
    """The other half of Finding 7: a real A<->B cycle used to have no
    visited-set guard at all, so it recursed to max_depth producing a
    nonsense repeating chain ('B','A','B','A',...) and reported it as
    truncated. It must now terminate cleanly at the real cycle boundary."""
    conn = storage.connect(tmp_path / "cyclic.duckdb")
    error_log = IngestionErrorLog(tmp_path / "cyclic_errors.jsonl")
    csv_path = tmp_path / "cyclic_relationships.csv"
    csv_path.write_text(
        "Relationship.StartNode.NodeID,Relationship.EndNode.NodeID,"
        "Relationship.RelationshipType,Relationship.RelationshipStatus\n"
        "LEI-CYCLE-A,LEI-CYCLE-B,IS_DIRECTLY_CONSOLIDATED_BY,ACTIVE\n"
        "LEI-CYCLE-B,LEI-CYCLE-A,IS_DIRECTLY_CONSOLIDATED_BY,ACTIVE\n",
        encoding="utf-8",
    )
    load_gleif_level2(conn, csv_path, datetime.date(2026, 8, 1), error_log)
    error_log.close()

    result = parent_chain(conn, "LEI-CYCLE-A", direction="up", max_depth=10)

    assert result.chains == (("LEI-CYCLE-B",),)
    assert result.truncated is False
    conn.close()


def test_parent_chain_rejects_an_invalid_direction(tmp_path):
    conn = _conn_with_relationships_loaded(tmp_path)
    try:
        parent_chain(conn, "LEI-SUB", direction="sideways")
        assert False, "expected ValueError"
    except ValueError:
        pass
    conn.close()


def test_ultimate_parent_prefers_gleifs_own_shortcut_edge(tmp_path):
    conn = _conn_with_relationships_loaded(tmp_path)

    result = ultimate_parent(conn, "LEI-SUB")

    assert result == (("LEI-ULTIMATE-DE",), False)
    conn.close()


def test_ultimate_parent_falls_back_to_walking_when_no_shortcut_exists(tmp_path):
    conn = _conn_with_relationships_loaded(tmp_path)

    result = ultimate_parent(conn, "LEI-CHAIN-START", max_depth=10)

    assert result == (("LEI-CHAIN-10",), True)
    conn.close()


def test_ultimate_parent_returns_every_distinct_branch(tmp_path):
    conn = storage.connect(tmp_path / "branching.duckdb")
    error_log = IngestionErrorLog(tmp_path / "branching_errors.jsonl")
    csv_path = tmp_path / "branching_relationships.csv"
    csv_path.write_text(
        "Relationship.StartNode.NodeID,Relationship.EndNode.NodeID,"
        "Relationship.RelationshipType,Relationship.RelationshipStatus\n"
        "LEI-BRANCH-SUB,LEI-BRANCH-P1,IS_DIRECTLY_CONSOLIDATED_BY,ACTIVE\n"
        "LEI-BRANCH-SUB,LEI-BRANCH-P2,IS_DIRECTLY_CONSOLIDATED_BY,ACTIVE\n"
        "LEI-BRANCH-P1,LEI-BRANCH-TOPA,IS_DIRECTLY_CONSOLIDATED_BY,ACTIVE\n"
        "LEI-BRANCH-P2,LEI-BRANCH-TOPB,IS_DIRECTLY_CONSOLIDATED_BY,ACTIVE\n",
        encoding="utf-8",
    )
    load_gleif_level2(conn, csv_path, datetime.date(2026, 8, 1), error_log)
    error_log.close()

    result = ultimate_parent(conn, "LEI-BRANCH-SUB")

    assert result is not None
    ultimate_leis, truncated = result
    assert set(ultimate_leis) == {"LEI-BRANCH-TOPA", "LEI-BRANCH-TOPB"}
    assert truncated is False
    conn.close()


def test_ultimate_parent_returns_none_with_no_known_parent(tmp_path):
    conn = _conn_with_relationships_loaded(tmp_path)

    assert ultimate_parent(conn, "LEI-NO-PARENT") is None
    conn.close()
