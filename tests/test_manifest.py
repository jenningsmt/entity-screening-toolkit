import json

from entity_screening.common.manifest import DatasetSnapshot, ExportManifest, RunManifest


def test_manifest_round_trips_through_disk(tmp_path):
    manifest = RunManifest.start()
    manifest.add_dataset_snapshot(
        DatasetSnapshot(
            source_dataset="nsf_award_search",
            retrieved_at="2026-08-31",
            location="tests/fixtures/sample_nsf_awards.json",
            record_count=3,
        )
    )
    manifest.rubric = {"screening_hit_weight": 50.0}
    manifest.finish()

    out_path = manifest.write(base=tmp_path)
    assert out_path.exists()

    loaded = RunManifest.load(out_path)
    assert loaded.run_id == manifest.run_id
    assert loaded.finished_at is not None
    assert len(loaded.dataset_snapshots) == 1
    assert loaded.dataset_snapshots[0].source_dataset == "nsf_award_search"
    assert loaded.rubric == {"screening_hit_weight": 50.0}


def test_manifest_json_is_traceable_to_exact_inputs(tmp_path):
    manifest = RunManifest.start()
    manifest.add_dataset_snapshot(
        DatasetSnapshot("opensanctions_targets_simple", "2026-08-31", "targets.simple.csv", 700000)
    )
    out_path = manifest.write(base=tmp_path)

    raw = json.loads(out_path.read_text())
    assert raw["dataset_snapshots"][0]["record_count"] == 700000
    assert raw["run_id"] == manifest.run_id


def test_export_manifest_round_trips_through_disk(tmp_path):
    export_manifest = ExportManifest.create(
        source_run_id="run-1",
        rubric={"screening_hit_weight": 75.0},
        match_thresholds={"screening_threshold": 0.8},
        fmt="csv",
    )
    out_path = export_manifest.write(base=tmp_path)
    assert out_path.exists()

    loaded = ExportManifest.load(out_path)
    assert loaded.export_id == export_manifest.export_id
    assert loaded.source_run_id == "run-1"
    assert loaded.rubric == {"screening_hit_weight": 75.0}
    assert loaded.format == "csv"


def test_export_manifest_gets_a_fresh_id_every_call():
    first = ExportManifest.create("run-1", rubric={}, match_thresholds={}, fmt="csv")
    second = ExportManifest.create("run-1", rubric={}, match_thresholds={}, fmt="csv")
    assert first.export_id != second.export_id
