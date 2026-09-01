import json
from pathlib import Path

from entity_screening import pipeline
from entity_screening.common import storage
from entity_screening.scoring.rubric import STOCK_RUBRIC, ScoringRubric

FIXTURES_DIR = Path(__file__).parent / "fixtures"
NSF_FILE = FIXTURES_DIR / "sample_nsf_awards.json"
OPENSANCTIONS_FILE = FIXTURES_DIR / "sample_opensanctions_targets.csv"
DOD_1260H_FIXTURE_FILE = FIXTURES_DIR / "sample_dod_1260h.json"


def _run(db_path):
    return pipeline.run_screening(
        nsf_file=NSF_FILE,
        nsf_date_start=None,
        nsf_date_end=None,
        opensanctions_file=OPENSANCTIONS_FILE,
        rubric=STOCK_RUBRIC,
        threshold=0.80,
        db_path=db_path,
    )


def test_run_screening_twice_against_the_same_db_does_not_collide(tmp_path):
    """Regression test: entity_id is a deterministic hash of the normalized
    name (pipeline.py:resolve_entities_from_nsf), so the same real-world
    entity legitimately recurs with the same entity_id across two separate
    runs against the same persistent DB — exactly what a long-lived API
    server does on every POST /runs. This used to raise a DuckDB primary-key
    violation because resolved_entities keyed on entity_id alone; the key is
    now (entity_id, run_id)."""
    db_path = tmp_path / "test.duckdb"
    manifest_1, scored_1 = _run(db_path)
    manifest_2, scored_2 = _run(db_path)

    assert manifest_1.run_id != manifest_2.run_id
    assert {s.entity_id for s in scored_1} == {s.entity_id for s in scored_2}

    conn = storage.connect(db_path)
    total_rows = conn.execute("SELECT count(*) FROM resolved_entities").fetchone()[0]
    conn.close()
    assert total_rows == len(scored_1) + len(scored_2)


def test_run_screening_persists_exactly_one_score_row_per_entity(tmp_path):
    db_path = tmp_path / "test.duckdb"
    manifest, scored_entities = _run(db_path)

    conn = storage.connect(db_path)
    row_count = conn.execute(
        "SELECT count(*) FROM scored_entities WHERE run_id = ?", [manifest.run_id]
    ).fetchone()[0]
    conn.close()

    assert row_count == len(scored_entities)
    assert row_count > 0


def test_rescore_run_never_writes_to_the_database(tmp_path):
    db_path = tmp_path / "test.duckdb"
    manifest, _ = _run(db_path)

    conn = storage.connect(db_path)
    before = conn.execute("SELECT count(*) FROM scored_entities").fetchone()[0]
    conn.close()

    custom_rubric = ScoringRubric(screening_hit_weight=999.0)
    for _ in range(3):
        pipeline.rescore_run(manifest.run_id, custom_rubric, db_path=db_path)

    conn = storage.connect(db_path)
    after = conn.execute("SELECT count(*) FROM scored_entities").fetchone()[0]
    conn.close()

    assert after == before


def test_rescore_run_actually_changes_scores_under_a_different_rubric(tmp_path):
    db_path = tmp_path / "test.duckdb"
    manifest, original_scores = _run(db_path)

    heavier_rubric = ScoringRubric(screening_hit_weight=STOCK_RUBRIC.screening_hit_weight * 10)
    rescored = pipeline.rescore_run(manifest.run_id, heavier_rubric, db_path=db_path)

    original_by_id = {s.entity_id: s for s in original_scores}
    rescored_by_id = {s.entity_id: s for s in rescored}
    hit_entity_ids = [eid for eid, s in original_by_id.items() if s.screening_hits]

    assert hit_entity_ids, "fixture should produce at least one screening hit"
    for entity_id in hit_entity_ids:
        assert rescored_by_id[entity_id].score.total > original_by_id[entity_id].score.total


def test_export_scored_entities_writes_a_distinct_manifest_per_call(tmp_path):
    db_path = tmp_path / "test.duckdb"
    manifest, scored_entities = _run(db_path)

    _, export_manifest_1 = pipeline.export_scored_entities(
        scored_entities,
        source_run_id=manifest.run_id,
        rubric=STOCK_RUBRIC,
        match_thresholds=manifest.match_thresholds,
        fmt="csv",
    )
    custom_rubric = ScoringRubric(screening_hit_weight=1.0)
    rescored = pipeline.rescore_run(manifest.run_id, custom_rubric, db_path=db_path)
    _, export_manifest_2 = pipeline.export_scored_entities(
        rescored,
        source_run_id=manifest.run_id,
        rubric=custom_rubric,
        match_thresholds=manifest.match_thresholds,
        fmt="csv",
    )

    assert export_manifest_1.export_id != export_manifest_2.export_id
    assert export_manifest_1.rubric != export_manifest_2.rubric
    assert export_manifest_2.rubric["screening_hit_weight"] == 1.0


def test_run_screening_checks_the_dod_1260h_list_too(tmp_path):
    """End-to-end wiring check: a resolved entity matching a DoD 1260H
    curated entry produces a hit tagged with that list, using a controlled
    fixture rather than relying on coincidence with the real bundled list."""
    nsf_file = tmp_path / "nsf_awards.json"
    nsf_file.write_text(
        json.dumps(
            {
                "response": {
                    "award": [
                        {
                            "id": "9000001",
                            "awardeeName": "Fixture Military Technology Co., Ltd.",
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    db_path = tmp_path / "test.duckdb"
    manifest, scored_entities = pipeline.run_screening(
        nsf_file=nsf_file,
        nsf_date_start=None,
        nsf_date_end=None,
        opensanctions_file=OPENSANCTIONS_FILE,
        rubric=STOCK_RUBRIC,
        threshold=0.80,
        db_path=db_path,
        dod_1260h_file=DOD_1260H_FIXTURE_FILE,
    )

    assert any(s.source_dataset == "dod_section_1260h" for s in manifest.dataset_snapshots)
    hits = [h for s in scored_entities for h in s.screening_hits]
    dod_hits = [h for h in hits if h.list_name == "dod_section_1260h"]
    assert len(dod_hits) == 1
