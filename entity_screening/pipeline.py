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
from datetime import date
from pathlib import Path

from entity_screening.common import storage
from entity_screening.common.manifest import (
    DEFAULT_RUNS_DIR,
    DatasetSnapshot,
    ExportManifest,
    GleifSnapshotManifest,
    RunManifest,
)
from entity_screening.common.schema import ForeignControlFlag, ResolvedEntity, ScoredEntity, ScreeningHit, SourceRecord
from entity_screening.ingestion.base import IngestionErrorLog
from entity_screening.ingestion.dod_1260h import DEFAULT_DATA_FILE as DEFAULT_DOD_1260H_FILE
from entity_screening.ingestion.dod_1260h import DoD1260HIngester
from entity_screening.ingestion.nsf import NSFAwardIngester
from entity_screening.ingestion.opensanctions import OpenSanctionsTargetsIngester
from entity_screening.ingestion.section_117 import Section117Ingester
from entity_screening.output.export import export_csv, export_excel
from entity_screening.ownership.flagging import flag_from_match
from entity_screening.ownership.graph import DEFAULT_MAX_DEPTH
from entity_screening.ownership.ingest import load_gleif_level1, load_gleif_level2
from entity_screening.ownership.match import resolve_entity_to_lei
from entity_screening.resolution.matcher import DEFAULT_THRESHOLD
from entity_screening.resolution.normalize import normalize_for_matching
from entity_screening.screening.lists import DoD1260HList, OpenSanctionsList
from entity_screening.screening.screen import screen_entity
from entity_screening.screening.section_117 import (
    DEFAULT_INSTITUTION_THRESHOLD as DEFAULT_SECTION_117_INSTITUTION_THRESHOLD,
)
from entity_screening.screening.section_117 import cross_check_section_117
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
    section_117_file: Path | str | None = None,
    section_117_institution_threshold: float = DEFAULT_SECTION_117_INSTITUTION_THRESHOLD,
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
    each run; the override exists for tests. `section_117_file` is optional
    with no bundled fallback (same "optional, no bundled default" posture as
    GLEIF) — omitted entirely, ingestion/cross-checking is skipped and
    behavior is identical to before Section 117 existed.
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

    section_117_records: list[SourceRecord] = []
    if section_117_file:
        section_117_ingester = Section117Ingester(error_log, xlsx_path=section_117_file)
        section_117_records = list(section_117_ingester.stream_records())
        manifest.add_dataset_snapshot(
            DatasetSnapshot(
                source_dataset=section_117_ingester.source_dataset,
                retrieved_at=section_117_ingester.retrieval_date.isoformat(),
                location=str(section_117_file),
                record_count=len(section_117_records),
            )
        )

    manifest.ingestion_error_counts["total"] = error_log.count
    error_log.close()

    manifest.rubric = rubric_to_dict(rubric)
    manifest.match_thresholds = {"screening_threshold": threshold}
    if section_117_file:
        manifest.match_thresholds["section_117_institution_threshold"] = (
            section_117_institution_threshold
        )

    entities = resolve_entities_from_nsf(nsf_records)
    concern_lists = [OpenSanctionsList(os_records), DoD1260HList(dod_records)]

    scored_entities: list[ScoredEntity] = []
    all_hits: list[ScreeningHit] = []
    for entity in entities:
        hits = list(screen_entity(entity, concern_lists, threshold=threshold))
        if section_117_records:
            hits.extend(
                cross_check_section_117(
                    entity,
                    section_117_records,
                    concern_lists,
                    institution_threshold=section_117_institution_threshold,
                    funder_threshold=threshold,
                )
            )
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
        storage.insert_source_records(conn, "raw_section_117", section_117_records)
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
    persisted entities/hits/ownership-flags under a (possibly different)
    rubric. Performs no database writes under any circumstance; this is what
    backs a live rubric-slider preview without growing `scored_entities` (or
    `ownership_flags`/`lei_matches`) on every drag. Ownership flags are only
    present if `enrich_ownership` has already been run for this `run_id` —
    otherwise `load_ownership_flags` just returns an empty list and scoring
    proceeds exactly as it did before Epic C existed.
    """
    conn = storage.connect(db_path)
    try:
        entities = storage.load_resolved_entities(conn, run_id)
        hits = storage.load_screening_hits(conn, run_id)
        ownership_flags = storage.load_ownership_flags(conn, run_id)
    finally:
        conn.close()

    hits_by_entity: dict[str, list[ScreeningHit]] = defaultdict(list)
    for hit in hits:
        hits_by_entity[hit.entity_id].append(hit)

    flags_by_entity: dict[str, list[ForeignControlFlag]] = defaultdict(list)
    for flag in ownership_flags:
        flags_by_entity[flag.entity_id].append(flag)

    scored_entities = []
    for entity in entities:
        entity_hits = hits_by_entity.get(entity.entity_id, [])
        entity_flags = flags_by_entity.get(entity.entity_id, [])
        breakdown = score_entity(entity, entity_hits, rubric=rubric, ownership_flags=entity_flags)
        scored_entities.append(
            ScoredEntity(
                entity_id=entity.entity_id,
                canonical_name=entity.canonical_name,
                score=breakdown,
                screening_hits=tuple(entity_hits),
                run_id=run_id,
                ownership_flags=tuple(entity_flags),
            )
        )
    return scored_entities


def enrich_ownership(
    run_id: str,
    gleif_lei_file: Path | str,
    gleif_relationships_file: Path | str,
    threshold: float = DEFAULT_THRESHOLD,
    max_depth: int = DEFAULT_MAX_DEPTH,
    db_path: Path | str = storage.DEFAULT_DB_PATH,
    runs_dir: Path | str = DEFAULT_RUNS_DIR,
) -> tuple[GleifSnapshotManifest, list[ForeignControlFlag]]:
    """Resolves an already-existing run's entities against GLEIF and computes
    foreign-control flags — a separate, explicit step from `run_screening`,
    callable independently against a run that already exists. GLEIF is a
    shared reference dataset, not a per-run ingestion source: `gleif_lei`/
    `gleif_relationships` are a disposable working copy (`CREATE OR REPLACE
    TABLE`, see `ownership/ingest.py`), rebuilt on every call, by any run.

    Does NOT touch `scored_entities` — that stays `run_screening`'s exclusive
    write. A caller wanting updated scores calls `rescore_run` afterward.

    Writes `GleifSnapshotManifest` to `data/processed/runs/<run_id>/ownership/
    manifest.json` — a durable, run-scoped copy, not just the mutable global
    tables — so run A's flags don't silently lose the ability to say which
    GLEIF download produced them the moment run B's enrichment call replaces
    those tables. Re-running this for the same `run_id` overwrites that file
    and the corresponding `lei_matches`/`ownership_flags` rows: a deliberate
    "current state" model, like `scored_entities`, not a historical log.
    """
    conn = storage.connect(db_path)
    try:
        run_dir = Path(runs_dir) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        error_log = IngestionErrorLog(run_dir / "ingestion_errors.jsonl")

        lei_count = load_gleif_level1(conn, gleif_lei_file, date.today(), error_log)
        relationship_count = load_gleif_level2(
            conn, gleif_relationships_file, date.today(), error_log
        )
        error_log.close()

        entities = storage.load_resolved_entities(conn, run_id)

        matches = []
        flags = []
        for entity in entities:
            match = resolve_entity_to_lei(conn, entity.entity_id, entity.canonical_name, threshold)
            if match is None:
                continue
            matches.append(match)
            flag = flag_from_match(conn, match, max_depth=max_depth)
            if flag is not None:
                flags.append(flag)

        storage.insert_lei_matches(conn, matches, run_id)
        storage.insert_ownership_flags(conn, flags, run_id)
    finally:
        conn.close()

    gleif_manifest = GleifSnapshotManifest.create(
        run_id=run_id,
        lei_record_count=lei_count,
        relationship_record_count=relationship_count,
        gleif_lei_file=gleif_lei_file,
        gleif_relationships_file=gleif_relationships_file,
    )
    gleif_manifest.write(runs_dir)
    return gleif_manifest, flags


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
