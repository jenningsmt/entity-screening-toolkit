import datetime
from pathlib import Path

from entity_screening.common import storage
from entity_screening.ingestion.base import IngestionErrorLog
from entity_screening.ownership.ingest import load_gleif_level1, load_gleif_level2

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_load_gleif_level1_bulk_loads_and_tags_provenance(tmp_path):
    conn = storage.connect(tmp_path / "test.duckdb")
    error_log = IngestionErrorLog(tmp_path / "errors.jsonl")

    count = load_gleif_level1(
        conn, FIXTURES_DIR / "sample_gleif_lei.csv", datetime.date(2026, 8, 1), error_log
    )
    error_log.close()

    assert count == 19
    row = conn.execute(
        "SELECT legal_name, legal_jurisdiction, entity_status, normalized_name_prefix, "
        "source_dataset, retrieval_date FROM gleif_lei WHERE lei = 'LEI-SUB'"
    ).fetchone()
    assert row[0] == "Fixture Subsidiary Corp"
    assert row[1] == "US"
    assert row[2] == "ACTIVE"
    assert row[3] == "fix"
    assert row[4] == "gleif_lei_level1"
    assert row[5] == datetime.date(2026, 8, 1)
    conn.close()


def test_load_gleif_level2_filters_to_relevant_active_relationships(tmp_path):
    conn = storage.connect(tmp_path / "test.duckdb")
    error_log = IngestionErrorLog(tmp_path / "errors.jsonl")

    count = load_gleif_level2(
        conn,
        FIXTURES_DIR / "sample_gleif_relationships.csv",
        datetime.date(2026, 8, 1),
        error_log,
    )
    error_log.close()

    assert count == 16
    row = conn.execute(
        "SELECT relationship_type, relationship_status, source_dataset FROM gleif_relationships "
        "WHERE start_lei = 'LEI-SUB' AND relationship_type = 'IS_ULTIMATELY_CONSOLIDATED_BY'"
    ).fetchone()
    assert row[0] == "IS_ULTIMATELY_CONSOLIDATED_BY"
    assert row[1] == "ACTIVE"
    assert row[2] == "gleif_relationships_level2"
    conn.close()


def test_reloading_gleif_replaces_the_working_tables(tmp_path):
    """CREATE OR REPLACE TABLE — the tables are a disposable working copy,
    not append-only, per the V2 plan."""
    conn = storage.connect(tmp_path / "test.duckdb")
    error_log = IngestionErrorLog(tmp_path / "errors.jsonl")

    load_gleif_level1(conn, FIXTURES_DIR / "sample_gleif_lei.csv", datetime.date(2026, 1, 1), error_log)
    load_gleif_level1(conn, FIXTURES_DIR / "sample_gleif_lei.csv", datetime.date(2026, 8, 1), error_log)
    error_log.close()

    count = conn.execute("SELECT count(*) FROM gleif_lei").fetchone()[0]
    retrieval_dates = conn.execute("SELECT DISTINCT retrieval_date FROM gleif_lei").fetchall()
    conn.close()

    assert count == 19  # not doubled
    assert retrieval_dates == [(datetime.date(2026, 8, 1),)]
