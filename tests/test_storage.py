import datetime

from entity_screening.common import storage
from entity_screening.common.schema import (
    MatchStatus,
    ResolvedEntity,
    ScoreBreakdown,
    ScoredEntity,
    ScreeningHit,
    SourceRecord,
)


def test_connect_creates_schema(tmp_path):
    conn = storage.connect(tmp_path / "test.duckdb")
    tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
    conn.close()
    assert {
        "raw_nsf_awards",
        "raw_opensanctions_targets",
        "resolved_entities",
        "screening_hits",
        "scored_entities",
    } <= tables


def test_same_entity_id_can_recur_across_different_runs(tmp_path):
    """entity_id is a deterministic hash of the normalized name, so the same
    real-world entity legitimately produces the same entity_id in two
    separate runs — that must not violate a primary key."""
    conn = storage.connect(tmp_path / "test.duckdb")
    entity = ResolvedEntity(
        entity_id="same-id", canonical_name="Acme Corp", entity_type="organization",
        source_records=(),
    )
    storage.insert_resolved_entities(conn, [entity], run_id="run-1")
    storage.insert_resolved_entities(conn, [entity], run_id="run-2")

    count = conn.execute("SELECT count(*) FROM resolved_entities").fetchone()[0]
    conn.close()
    assert count == 2


def test_insert_and_read_round_trips(tmp_path):
    conn = storage.connect(tmp_path / "test.duckdb")

    record = SourceRecord(
        source_dataset="nsf_award_search",
        retrieval_date=datetime.date(2026, 8, 31),
        source_record_id="1",
        fields={"awardeeName": "Acme Corp"},
    )
    storage.insert_source_records(conn, "raw_nsf_awards", [record])

    entity = ResolvedEntity(
        entity_id="e1", canonical_name="Acme Corp", entity_type="organization", source_records=()
    )
    storage.insert_resolved_entities(conn, [entity], run_id="run-1")

    hit = ScreeningHit(
        entity_id="e1",
        list_name="opensanctions_consolidated",
        matched_variant="Acme",
        matched_field="name_variants",
        confidence=0.95,
        evidence={"entry_id": "os-1"},
        status=MatchStatus.CANDIDATE_MATCH,
    )
    storage.insert_screening_hits(conn, [hit], run_id="run-1")

    scored = ScoredEntity(
        entity_id="e1",
        canonical_name="Acme Corp",
        score=ScoreBreakdown(total=47.5, factors={"screening_hit": 47.5}),
        screening_hits=(hit,),
        run_id="run-1",
    )
    storage.insert_scored_entities(conn, [scored])

    assert conn.execute("SELECT count(*) FROM raw_nsf_awards").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM resolved_entities").fetchone()[0] == 1
    assert conn.execute("SELECT status FROM screening_hits").fetchone()[0] == "candidate_match"
    assert conn.execute("SELECT total_score FROM scored_entities").fetchone()[0] == 47.5
    conn.close()


def test_load_resolved_entities_and_screening_hits_round_trip(tmp_path):
    conn = storage.connect(tmp_path / "test.duckdb")

    entity = ResolvedEntity(
        entity_id="e1", canonical_name="Acme Corp", entity_type="organization", source_records=()
    )
    storage.insert_resolved_entities(conn, [entity], run_id="run-1")

    hit = ScreeningHit(
        entity_id="e1",
        list_name="opensanctions_consolidated",
        matched_variant="Acme",
        matched_field="name_variants",
        confidence=0.95,
        evidence={"entry_id": "os-1", "matched_entry_fields": {"name": "Acme"}},
        status=MatchStatus.CANDIDATE_MATCH,
    )
    storage.insert_screening_hits(conn, [hit], run_id="run-1")

    loaded_entities = storage.load_resolved_entities(conn, "run-1")
    loaded_hits = storage.load_screening_hits(conn, "run-1")
    conn.close()

    assert len(loaded_entities) == 1
    assert loaded_entities[0].entity_id == "e1"
    assert loaded_entities[0].canonical_name == "Acme Corp"
    assert loaded_entities[0].source_records == ()

    assert len(loaded_hits) == 1
    assert loaded_hits[0].entity_id == "e1"
    assert loaded_hits[0].confidence == 0.95
    assert loaded_hits[0].status is MatchStatus.CANDIDATE_MATCH
    assert loaded_hits[0].evidence["matched_entry_fields"]["name"] == "Acme"


def test_load_resolved_entities_scoped_to_run_id(tmp_path):
    conn = storage.connect(tmp_path / "test.duckdb")
    entity = ResolvedEntity(
        entity_id="e1", canonical_name="Acme Corp", entity_type="organization", source_records=()
    )
    storage.insert_resolved_entities(conn, [entity], run_id="run-1")

    assert len(storage.load_resolved_entities(conn, "run-1")) == 1
    assert len(storage.load_resolved_entities(conn, "run-2")) == 0
    conn.close()
