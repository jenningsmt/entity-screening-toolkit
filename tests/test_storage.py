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
