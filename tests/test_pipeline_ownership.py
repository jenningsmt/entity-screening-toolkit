import json
from pathlib import Path

from entity_screening import pipeline
from entity_screening.common import storage
from entity_screening.common.manifest import GleifSnapshotManifest
from entity_screening.scoring.rubric import STOCK_RUBRIC, ScoringRubric

FIXTURES_DIR = Path(__file__).parent / "fixtures"
OPENSANCTIONS_FILE = FIXTURES_DIR / "sample_opensanctions_targets.csv"
GLEIF_LEI_FILE = FIXTURES_DIR / "sample_gleif_lei.csv"
GLEIF_RELATIONSHIPS_FILE = FIXTURES_DIR / "sample_gleif_relationships.csv"


def _nsf_file_for(tmp_path, awardee_name: str) -> Path:
    path = tmp_path / "nsf_awards.json"
    path.write_text(
        json.dumps(
            {"response": {"award": [{"id": "9000001", "awardeeName": awardee_name}]}}
        ),
        encoding="utf-8",
    )
    return path


def _run_and_enrich(tmp_path, awardee_name: str, gleif_lei_file=GLEIF_LEI_FILE):
    db_path = tmp_path / "test.duckdb"
    manifest, scored_entities = pipeline.run_screening(
        nsf_file=_nsf_file_for(tmp_path, awardee_name),
        nsf_date_start=None,
        nsf_date_end=None,
        opensanctions_file=OPENSANCTIONS_FILE,
        rubric=STOCK_RUBRIC,
        threshold=0.80,
        db_path=db_path,
        runs_dir=tmp_path,
    )
    gleif_manifest, flags = pipeline.enrich_ownership(
        manifest.run_id,
        gleif_lei_file,
        GLEIF_RELATIONSHIPS_FILE,
        db_path=db_path,
        runs_dir=tmp_path,
    )
    return db_path, manifest, gleif_manifest, flags


def test_enrich_ownership_produces_a_foreign_control_flag(tmp_path):
    db_path, manifest, gleif_manifest, flags = _run_and_enrich(
        tmp_path, "Fixture Subsidiary Corp"
    )

    assert len(flags) == 1
    assert flags[0].ultimate_parent_jurisdiction == "DE"
    assert gleif_manifest.lei_record_count == 19
    assert gleif_manifest.relationship_record_count == 16

    conn = storage.connect(db_path)
    flag_rows = conn.execute(
        "SELECT count(*) FROM ownership_flags WHERE run_id = ?", [manifest.run_id]
    ).fetchone()[0]
    match_rows = conn.execute(
        "SELECT count(*) FROM lei_matches WHERE run_id = ?", [manifest.run_id]
    ).fetchone()[0]
    conn.close()
    assert flag_rows == 1
    assert match_rows == 1  # the one resolved entity, matched whether or not it flagged


def test_enrich_ownership_writes_a_durable_per_run_manifest(tmp_path):
    db_path, manifest, gleif_manifest, _flags = _run_and_enrich(
        tmp_path, "Fixture Subsidiary Corp"
    )

    manifest_path = tmp_path / manifest.run_id / "ownership" / "manifest.json"
    assert manifest_path.exists()

    loaded = GleifSnapshotManifest.load(manifest_path)
    assert loaded.run_id == manifest.run_id
    assert loaded.lei_record_count == gleif_manifest.lei_record_count


def test_no_flag_case_still_persists_a_lei_match(tmp_path):
    """Same-jurisdiction entities resolve to an LEI but produce no flag —
    lei_matches must still record that match (Epic C's "queryable" interactive
    endpoint needs it for any resolved entity, not only flagged ones)."""
    db_path, manifest, _gleif_manifest, flags = _run_and_enrich(
        tmp_path, "Fixture Same Country Sub"
    )

    assert flags == []
    conn = storage.connect(db_path)
    match_rows = conn.execute(
        "SELECT count(*) FROM lei_matches WHERE run_id = ?", [manifest.run_id]
    ).fetchone()[0]
    conn.close()
    assert match_rows == 1


def test_rescore_run_reflects_ownership_flags_without_recomputing_them(tmp_path):
    db_path, manifest, _gleif_manifest, flags = _run_and_enrich(
        tmp_path, "Fixture Subsidiary Corp"
    )
    assert flags  # sanity: fixture actually produced a flag to rescore against

    conn = storage.connect(db_path)
    before_flags = conn.execute("SELECT count(*) FROM ownership_flags").fetchone()[0]
    before_matches = conn.execute("SELECT count(*) FROM lei_matches").fetchone()[0]
    conn.close()

    baseline = pipeline.rescore_run(manifest.run_id, STOCK_RUBRIC, db_path=db_path)
    heavier = pipeline.rescore_run(
        manifest.run_id,
        ScoringRubric(foreign_control_weight=STOCK_RUBRIC.foreign_control_weight * 10),
        db_path=db_path,
    )

    conn = storage.connect(db_path)
    after_flags = conn.execute("SELECT count(*) FROM ownership_flags").fetchone()[0]
    after_matches = conn.execute("SELECT count(*) FROM lei_matches").fetchone()[0]
    conn.close()

    assert after_flags == before_flags
    assert after_matches == before_matches

    baseline_by_id = {s.entity_id: s for s in baseline}
    heavier_by_id = {s.entity_id: s for s in heavier}
    flagged_entity_id = flags[0].entity_id
    assert heavier_by_id[flagged_entity_id].score.total > baseline_by_id[flagged_entity_id].score.total
    assert baseline_by_id[flagged_entity_id].ownership_flags


def test_enrich_ownership_twice_does_not_collide_and_manifest_reflects_latest_call(tmp_path):
    db_path, manifest, first_manifest, first_flags = _run_and_enrich(
        tmp_path, "Fixture Subsidiary Corp"
    )
    assert first_flags

    second_manifest, second_flags = pipeline.enrich_ownership(
        manifest.run_id,
        GLEIF_LEI_FILE,
        GLEIF_RELATIONSHIPS_FILE,
        db_path=db_path,
        runs_dir=tmp_path,
    )

    conn = storage.connect(db_path)
    flag_rows = conn.execute(
        "SELECT count(*) FROM ownership_flags WHERE run_id = ?", [manifest.run_id]
    ).fetchone()[0]
    match_rows = conn.execute(
        "SELECT count(*) FROM lei_matches WHERE run_id = ?", [manifest.run_id]
    ).fetchone()[0]
    conn.close()

    # Not doubled -- re-enrichment replaces, doesn't append.
    assert flag_rows == len(second_flags) == 1
    assert match_rows == 1

    manifest_path = tmp_path / manifest.run_id / "ownership" / "manifest.json"
    on_disk = GleifSnapshotManifest.load(manifest_path)
    assert on_disk.loaded_at == second_manifest.loaded_at
    assert on_disk.loaded_at != first_manifest.loaded_at
