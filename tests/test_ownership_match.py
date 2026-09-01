import datetime
from pathlib import Path

from entity_screening.common import storage
from entity_screening.common.schema import MatchStatus
from entity_screening.ingestion.base import IngestionErrorLog
from entity_screening.ownership.ingest import load_gleif_level1
from entity_screening.ownership.match import resolve_entity_to_lei

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _conn_with_gleif_loaded(tmp_path):
    conn = storage.connect(tmp_path / "test.duckdb")
    error_log = IngestionErrorLog(tmp_path / "errors.jsonl")
    load_gleif_level1(conn, FIXTURES_DIR / "sample_gleif_lei.csv", datetime.date(2026, 8, 1), error_log)
    error_log.close()
    return conn


def test_resolve_entity_to_lei_finds_a_confident_match(tmp_path):
    conn = _conn_with_gleif_loaded(tmp_path)

    match = resolve_entity_to_lei(conn, "entity-1", "Fixture Subsidiary Corp")

    assert match is not None
    assert match.entity_id == "entity-1"
    assert match.lei == "LEI-SUB"
    assert match.legal_jurisdiction == "US"
    assert match.confidence >= 0.80
    assert match.status is MatchStatus.CANDIDATE_MATCH
    conn.close()


def test_resolve_entity_to_lei_returns_none_below_threshold(tmp_path):
    conn = _conn_with_gleif_loaded(tmp_path)

    match = resolve_entity_to_lei(conn, "entity-1", "Totally Unrelated Name Zzqx")

    assert match is None
    conn.close()


def test_resolve_entity_to_lei_excludes_inactive_entities(tmp_path):
    conn = _conn_with_gleif_loaded(tmp_path)

    match = resolve_entity_to_lei(conn, "entity-1", "Fixture Inactive Entity")

    assert match is None
    conn.close()


def test_resolve_entity_to_lei_never_returns_a_bare_lei_string(tmp_path):
    conn = _conn_with_gleif_loaded(tmp_path)

    match = resolve_entity_to_lei(conn, "entity-1", "Fixture Subsidiary Corp")

    assert isinstance(match.confidence, float)
    assert 0.0 <= match.confidence <= 1.0
    conn.close()
