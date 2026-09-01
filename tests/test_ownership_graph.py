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

    assert result.chain == ("LEI-DIRECT-PARENT", "LEI-ULTIMATE-DE")
    assert result.truncated is False
    conn.close()


def test_parent_chain_direction_down_walks_subsidiaries(tmp_path):
    conn = _conn_with_relationships_loaded(tmp_path)

    result = parent_chain(conn, "LEI-ULTIMATE-DE", direction="down")

    assert "LEI-DIRECT-PARENT" in result.chain
    assert result.truncated is False
    conn.close()


def test_parent_chain_not_truncated_when_it_ends_naturally(tmp_path):
    """The chain LEI-SUB -> LEI-DIRECT-PARENT -> LEI-ULTIMATE-DE genuinely
    ends there (no further parent) — this must not be misreported as
    truncated just because a caller picked a small max_depth that happens to
    exceed the real chain length."""
    conn = _conn_with_relationships_loaded(tmp_path)

    result = parent_chain(conn, "LEI-SUB", direction="up", max_depth=2)

    assert result.chain == ("LEI-DIRECT-PARENT", "LEI-ULTIMATE-DE")
    assert result.truncated is False
    conn.close()


def test_parent_chain_reports_truncated_when_a_real_link_exists_beyond_max_depth(tmp_path):
    """The regression case the plan's review specifically called out: a chain
    exactly as long as max_depth must not be confused with one that's cut off.
    LEI-CHAIN-START -> 01 -> ... -> 11 is 11 real hops; with max_depth=10 the
    11th hop (to LEI-CHAIN-11) exists and must be detected, not guessed at
    from len(chain) == max_depth alone."""
    conn = _conn_with_relationships_loaded(tmp_path)

    result = parent_chain(conn, "LEI-CHAIN-START", direction="up", max_depth=10)

    assert len(result.chain) == 10
    assert result.chain[-1] == "LEI-CHAIN-10"
    assert result.truncated is True
    conn.close()


def test_parent_chain_exactly_at_max_depth_is_not_truncated(tmp_path):
    """The other half of the same regression: if the real chain is EXACTLY
    max_depth long with nothing beyond it, truncated must be False — proving
    the one-hop-past-max_depth peek actually distinguishes the two cases
    rather than both reporting truncated=True."""
    conn = _conn_with_relationships_loaded(tmp_path)

    result = parent_chain(conn, "LEI-CHAIN-START", direction="up", max_depth=11)

    assert len(result.chain) == 11
    assert result.chain[-1] == "LEI-CHAIN-11"
    assert result.truncated is False
    conn.close()


def test_parent_chain_empty_for_an_entity_with_no_parent(tmp_path):
    conn = _conn_with_relationships_loaded(tmp_path)

    result = parent_chain(conn, "LEI-NO-PARENT", direction="up")

    assert result.chain == ()
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

    assert result == ("LEI-ULTIMATE-DE", False)
    conn.close()


def test_ultimate_parent_falls_back_to_walking_when_no_shortcut_exists(tmp_path):
    conn = _conn_with_relationships_loaded(tmp_path)

    result = ultimate_parent(conn, "LEI-CHAIN-START", max_depth=10)

    assert result == ("LEI-CHAIN-10", True)
    conn.close()


def test_ultimate_parent_returns_none_with_no_known_parent(tmp_path):
    conn = _conn_with_relationships_loaded(tmp_path)

    assert ultimate_parent(conn, "LEI-NO-PARENT") is None
    conn.close()
