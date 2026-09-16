"""S6 (interim): both export paths -- case/export.py's
export_investigative_file and pipeline.export_scored_entities -- write a
brand-new export directory per call and, being reachable from ungated GET
routes, must not be allowed to grow without bound. Confirms
common.manifest.prune_sibling_export_dirs actually caps both.
"""
from __future__ import annotations

import time
from pathlib import Path

from entity_screening import pipeline
from entity_screening.case import demo, export as case_export
from entity_screening.common import storage
from entity_screening.common.manifest import MAX_EXPORTS_PER_TARGET
from entity_screening.pipeline import reconcile_case
from entity_screening.scoring.rubric import STOCK_RUBRIC

FIXTURES_DIR = Path(__file__).parent / "fixtures"
NSF_FILE = FIXTURES_DIR / "sample_nsf_awards.json"
OPENSANCTIONS_FILE = FIXTURES_DIR / "sample_opensanctions_targets.csv"

_CALLS = MAX_EXPORTS_PER_TARGET + 5


def test_case_export_directory_count_is_capped(tmp_path):
    db_path = tmp_path / "case.duckdb"
    runs_dir = tmp_path / "runs"
    conn = storage.connect(db_path)
    demo.build_demo_case(conn)
    conn.close()
    reconcile_case(
        demo.DEMO_CASE_ID,
        db_path=db_path,
        runs_dir=runs_dir,
        works_fixture=demo.load_demo_works_fixture(),
        gleif_lei_file=demo.DEMO_GLEIF_LEI_FILE,
        gleif_relationships_file=demo.DEMO_GLEIF_RELATIONSHIPS_FILE,
    )

    conn = storage.connect(db_path)
    export_ids = []
    for _ in range(_CALLS):
        _, manifest = case_export.export_investigative_file(
            conn, demo.DEMO_CASE_ID, fmt="json", runs_dir=runs_dir
        )
        export_ids.append(manifest.export_id)
        # A real anonymous visitor's requests are separated by at least an
        # HTTP round-trip; this loop calls the function directly, so space
        # the calls out past this filesystem's observed mtime granularity
        # (~15ms bursts of same-tick creates were seen in a tight loop) --
        # otherwise "the survivors are the most recent" is untestable, not
        # because pruning is wrong, but because the OS can't tell two
        # same-tick creates apart to order them.
        time.sleep(0.02)
    conn.close()

    export_parent = runs_dir / "cases" / demo.DEMO_CASE_ID / "investigative_file"
    surviving = {d.name for d in export_parent.iterdir() if d.is_dir()}
    assert len(surviving) == MAX_EXPORTS_PER_TARGET
    # The survivors are the most recent calls, not an arbitrary subset.
    assert surviving == set(export_ids[-MAX_EXPORTS_PER_TARGET:])


def test_batch_export_directory_count_is_capped(tmp_path):
    db_path = tmp_path / "run.duckdb"
    runs_dir = tmp_path / "runs"
    manifest, scored_entities = pipeline.run_screening(
        nsf_file=NSF_FILE,
        nsf_date_start=None,
        nsf_date_end=None,
        opensanctions_file=OPENSANCTIONS_FILE,
        rubric=STOCK_RUBRIC,
        threshold=0.80,
        db_path=db_path,
        runs_dir=runs_dir,
    )

    export_ids = []
    for _ in range(_CALLS):
        _, export_manifest = pipeline.export_scored_entities(
            scored_entities,
            source_run_id=manifest.run_id,
            rubric=STOCK_RUBRIC,
            match_thresholds=manifest.match_thresholds,
            fmt="csv",
            runs_dir=runs_dir,
        )
        export_ids.append(export_manifest.export_id)
        time.sleep(0.02)  # see the comment in test_case_export_directory_count_is_capped

    export_parent = runs_dir / manifest.run_id / "exports"
    surviving = {d.name for d in export_parent.iterdir() if d.is_dir()}
    assert len(surviving) == MAX_EXPORTS_PER_TARGET
    assert surviving == set(export_ids[-MAX_EXPORTS_PER_TARGET:])
