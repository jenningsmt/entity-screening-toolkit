"""Reusable pipeline orchestration shared by the CLI and the API layer.

Both `entity_screening/cli.py` and `entity_screening/api/main.py` call these
functions rather than duplicating ingest/resolve/screen/score/export logic
(docs/requirements.md Section 9a's FastAPI-layer design).

Reproducibility invariants (binding, not incidental):
- `run_screening` is the one and only writer of the `scored_entities` table —
  it computes the run's canonical baseline score under its own rubric.
- `rescore_run` is a pure read-compute-return function. It never writes to
  the database, no matter how many times or how rapidly it's called (it's
  what backs interactive rubric-slider exploration in the UI).
- `export_scored_entities` writes an immutable `ExportManifest` on every call,
  unconditionally, so every exported file's score values are traceable to the
  exact rubric that produced them — independent of what the source run's own
  `RunManifest` says, since that may no longer be the active rubric.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from pathlib import Path

from entity_screening.common import storage
from entity_screening.common.manifest import DEFAULT_RUNS_DIR, DatasetSnapshot, ExportManifest, RunManifest
from entity_screening.common.schema import ResolvedEntity, ScoredEntity, ScreeningHit, SourceRecord
from entity_screening.ingestion.base import IngestionErrorLog
from entity_screening.ingestion.dod_1260h import DEFAULT_DATA_FILE as DEFAULT_DOD_1260H_FILE
from entity_screening.ingestion.dod_1260h import DoD1260HIngester
from entity_screening.ingestion.nsf import NSFAwardIngester
from entity_screening.ingestion.opensanctions import OpenSanctionsTargetsIngester
from entity_screening.output.export import export_csv, export_excel
from entity_screening.resolution.normalize import normalize_for_matching
from entity_screening.screening.lists import DoD1260HList, OpenSanctionsList
from entity_screening.screening.screen import screen_entity
from entity_screening.scoring.rubric import ScoringRubric, rubric_to_dict
from entity_screening.scoring.score import score_entity


def resolve_entities_from_nsf(records: list[SourceRecord]) -> list[ResolvedEntity]:
    """Groups NSF award records by normalized awardee name into a ResolvedEntity.

    V1's resolution is deliberately simple (exact match on the normalized
    name) — Epic B's fuzzy cross-source matching applies at screening time,
    against the entity-of-concern lists, not here at intra-source grouping.
    """
    groups: dict[str, list[SourceRecord]] = defaultdict(list)
    display_names: dict[str, str] = {}
    for record in records:
        name = str(record.fields.get("awardeeName", "")).strip()
        if not name:
            continue
        key = normalize_for_matching(name)
        if not key:
            continue
        groups[key].append(record)
        display_names.setdefault(key, name)

    return [
        ResolvedEntity(
            entity_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, key)),
            canonical_name=display_names[key],
            entity_type="organization",
            source_records=tuple(recs),
        )
        for key, recs in groups.items()
    ]


def run_screening(
    *,
    nsf_file: Path | str | None,
    nsf_date_start: str | None,
    nsf_date_end: str | None,
    opensanctions_file: Path | str,
    rubric: ScoringRubric,
    threshold: float,
    db_path: Path | str = storage.DEFAULT_DB_PATH,
    runs_dir: Path | str = DEFAULT_RUNS_DIR,
    dod_1260h_file: Path | str = DEFAULT_DOD_1260H_FILE,
) -> tuple[RunManifest, list[ScoredEntity]]:
    """Ingest -> resolve -> screen -> score -> persist.

    Returns both the manifest and the in-memory scored entities (rather than
    forcing a caller to immediately call `rescore_run` just to get back data
    already computed here) — callers that want to export call
    `export_scored_entities` with this return value directly. `runs_dir`
    exists (mirroring `db_path`) so callers — tests and the API layer alike —
    can redirect manifest/export output away from the real
    data/processed/runs/ without patching a module-level constant, which
    wouldn't work anyway since RunManifest's default argument is bound at
    import time, not looked up per call. `dod_1260h_file` defaults to the
    bundled curated snapshot (screening/data/dod_1260h.json) — unlike NSF
    and OpenSanctions, there's no live source a user needs to point this at
    each run; the override exists for tests.
    """
    manifest = RunManifest.start()
    run_dir = manifest.run_dir(runs_dir)
    error_log = IngestionErrorLog(run_dir / "ingestion_errors.jsonl")

    nsf_ingester = NSFAwardIngester(
        error_log,
        local_file=nsf_file,
        date_start=nsf_date_start,
        date_end=nsf_date_end,
    )
    nsf_records = list(nsf_ingester.stream_records())
    manifest.add_dataset_snapshot(
        DatasetSnapshot(
            source_dataset=nsf_ingester.source_dataset,
            retrieved_at=nsf_ingester.retrieval_date.isoformat(),
            location=nsf_ingester.location(),
            record_count=len(nsf_records),
        )
    )

    os_ingester = OpenSanctionsTargetsIngester(error_log, csv_path=opensanctions_file)
    os_records = list(os_ingester.stream_records())
    manifest.add_dataset_snapshot(
        DatasetSnapshot(
            source_dataset=os_ingester.source_dataset,
            retrieved_at=os_ingester.retrieval_date.isoformat(),
            location=str(opensanctions_file),
            record_count=len(os_records),
        )
    )

    dod_ingester = DoD1260HIngester(error_log, data_file=dod_1260h_file)
    dod_records = list(dod_ingester.stream_records())
    manifest.add_dataset_snapshot(
        DatasetSnapshot(
            source_dataset=dod_ingester.source_dataset,
            retrieved_at=dod_ingester.retrieval_date.isoformat(),
            location=str(dod_1260h_file),
            record_count=len(dod_records),
        )
    )

    manifest.ingestion_error_counts["total"] = error_log.count
    error_log.close()

    manifest.rubric = rubric_to_dict(rubric)
    manifest.match_thresholds = {"screening_threshold": threshold}

    entities = resolve_entities_from_nsf(nsf_records)
    concern_lists = [OpenSanctionsList(os_records), DoD1260HList(dod_records)]

    scored_entities: list[ScoredEntity] = []
    all_hits: list[ScreeningHit] = []
    for entity in entities:
        hits = list(screen_entity(entity, concern_lists, threshold=threshold))
        all_hits.extend(hits)
        breakdown = score_entity(entity, hits, rubric=rubric)
        scored_entities.append(
            ScoredEntity(
                entity_id=entity.entity_id,
                canonical_name=entity.canonical_name,
                score=breakdown,
                screening_hits=tuple(hits),
                run_id=manifest.run_id,
            )
        )

    conn = storage.connect(db_path)
    try:
        storage.insert_source_records(conn, "raw_nsf_awards", nsf_records)
        storage.insert_source_records(conn, "raw_opensanctions_targets", os_records)
        storage.insert_source_records(conn, "raw_dod_1260h", dod_records)
        storage.insert_resolved_entities(conn, entities, manifest.run_id)
        storage.insert_screening_hits(conn, all_hits, manifest.run_id)
        storage.insert_scored_entities(conn, scored_entities)
    finally:
        conn.close()

    manifest.finish()
    manifest.write(runs_dir)
    return manifest, scored_entities


def rescore_run(
    run_id: str, rubric: ScoringRubric, db_path: Path | str = storage.DEFAULT_DB_PATH
) -> list[ScoredEntity]:
    """Pure read-compute-return — recomputes scores for an existing run's
    persisted entities/hits under a (possibly different) rubric. Performs no
    database writes under any circumstance; this is what backs a live
    rubric-slider preview without growing `scored_entities` on every drag.
    """
    conn = storage.connect(db_path)
    try:
        entities = storage.load_resolved_entities(conn, run_id)
        hits = storage.load_screening_hits(conn, run_id)
    finally:
        conn.close()

    hits_by_entity: dict[str, list[ScreeningHit]] = defaultdict(list)
    for hit in hits:
        hits_by_entity[hit.entity_id].append(hit)

    scored_entities = []
    for entity in entities:
        entity_hits = hits_by_entity.get(entity.entity_id, [])
        breakdown = score_entity(entity, entity_hits, rubric=rubric)
        scored_entities.append(
            ScoredEntity(
                entity_id=entity.entity_id,
                canonical_name=entity.canonical_name,
                score=breakdown,
                screening_hits=tuple(entity_hits),
                run_id=run_id,
            )
        )
    return scored_entities


def export_scored_entities(
    scored_entities: list[ScoredEntity],
    *,
    source_run_id: str,
    rubric: ScoringRubric,
    match_thresholds: dict,
    fmt: str,
    runs_dir: Path | str = DEFAULT_RUNS_DIR,
) -> tuple[Path, ExportManifest]:
    """Writes a CSV or Excel export plus its own immutable ExportManifest,
    colocated in the same directory — called identically by the CLI's
    single-shot run and the API's export endpoint, so every exported file
    gets a manifest, not just the ones produced through the API.
    """
    export_manifest = ExportManifest.create(
        source_run_id=source_run_id,
        rubric=rubric_to_dict(rubric),
        match_thresholds=match_thresholds,
        fmt=fmt,
    )
    export_dir = export_manifest.export_dir(runs_dir)
    if fmt == "xlsx":
        out_path = export_dir / "candidate_matches.xlsx"
        export_excel(scored_entities, out_path, export_manifest.export_id)
    else:
        out_path = export_dir / "candidate_matches.csv"
        export_csv(scored_entities, out_path, export_manifest.export_id)
    export_manifest.write(runs_dir)
    return out_path, export_manifest
