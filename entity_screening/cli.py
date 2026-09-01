"""Command-line entry point: python -m entity_screening.cli <subcommand>.

Subcommands:
    run       full pipeline: ingest -> resolve -> screen -> score -> export
    validate  structural sanity checks (Epic H), no data required
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import defaultdict
from pathlib import Path

from entity_screening.common import storage
from entity_screening.common.manifest import DatasetSnapshot, RunManifest
from entity_screening.common.schema import MatchStatus, ResolvedEntity, ScoredEntity, SourceRecord
from entity_screening.ingestion.base import IngestionErrorLog
from entity_screening.ingestion.nsf import NSFAwardIngester
from entity_screening.ingestion.opensanctions import OpenSanctionsTargetsIngester
from entity_screening.output.export import export_csv, export_excel
from entity_screening.resolution.matcher import DEFAULT_THRESHOLD
from entity_screening.resolution.normalize import normalize_for_matching
from entity_screening.screening.lists import OpenSanctionsList, registered_lists
from entity_screening.screening.screen import screen_entity
from entity_screening.scoring.rubric import STOCK_RUBRIC, rubric_from_dict, rubric_to_dict
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
            source_records=tuple(records),
        )
        for key, records in groups.items()
    ]


def run_pipeline(args: argparse.Namespace) -> RunManifest:
    manifest = RunManifest.start()
    run_dir = manifest.run_dir()
    error_log = IngestionErrorLog(run_dir / "ingestion_errors.jsonl")

    nsf_ingester = NSFAwardIngester(
        error_log,
        local_file=args.nsf_file,
        date_start=args.nsf_date_start,
        date_end=args.nsf_date_end,
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

    os_ingester = OpenSanctionsTargetsIngester(error_log, csv_path=args.opensanctions_file)
    os_records = list(os_ingester.stream_records())
    manifest.add_dataset_snapshot(
        DatasetSnapshot(
            source_dataset=os_ingester.source_dataset,
            retrieved_at=os_ingester.retrieval_date.isoformat(),
            location=str(args.opensanctions_file),
            record_count=len(os_records),
        )
    )

    manifest.ingestion_error_counts["total"] = error_log.count
    error_log.close()

    conn = storage.connect(args.db_file)
    storage.insert_source_records(conn, "raw_nsf_awards", nsf_records)
    storage.insert_source_records(conn, "raw_opensanctions_targets", os_records)

    rubric = STOCK_RUBRIC
    if args.rubric_file:
        rubric = rubric_from_dict(json.loads(Path(args.rubric_file).read_text(encoding="utf-8")))
    manifest.rubric = rubric_to_dict(rubric)
    manifest.match_thresholds = {"screening_threshold": args.threshold}

    entities = resolve_entities_from_nsf(nsf_records)
    concern_list = OpenSanctionsList(os_records)

    scored_entities: list[ScoredEntity] = []
    all_hits = []
    for entity in entities:
        hits = list(screen_entity(entity, [concern_list], threshold=args.threshold))
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

    storage.insert_resolved_entities(conn, entities, manifest.run_id)
    storage.insert_screening_hits(conn, all_hits, manifest.run_id)
    storage.insert_scored_entities(conn, scored_entities)
    conn.close()

    manifest.finish()
    manifest.write()

    out_csv = run_dir / "candidate_matches.csv"
    export_csv(scored_entities, out_csv)
    if args.excel:
        export_excel(scored_entities, run_dir / "candidate_matches.xlsx")

    total_hits = sum(len(s.screening_hits) for s in scored_entities)
    print(
        f"Run {manifest.run_id}: {len(entities)} entities resolved, "
        f"{total_hits} candidate hits, {error_log.count} ingestion errors logged.\n"
        f"CSV: {out_csv}\n"
        f"DuckDB: {args.db_file}"
    )
    return manifest


def _cmd_run(args: argparse.Namespace) -> int:
    run_pipeline(args)
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    """Structural sanity checks — no data required (Epic H)."""
    problems: list[str] = []

    if len(MatchStatus) != 1 or MatchStatus.CANDIDATE_MATCH.value != "candidate_match":
        problems.append(
            "MatchStatus must have exactly one member, CANDIDATE_MATCH — "
            "output must never be able to assert a confirmed match."
        )

    if not registered_lists():
        problems.append("No entity-of-concern lists are registered in screening/lists.py.")

    from dataclasses import fields as dc_fields

    for f in dc_fields(STOCK_RUBRIC):
        value = getattr(STOCK_RUBRIC, f.name)
        if not isinstance(value, (int, float)):
            problems.append(f"Rubric field {f.name!r} is not numeric: {value!r}")

    fixtures_dir = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
    known_difficult = fixtures_dir / "known_difficult_pairs.json"
    if not known_difficult.exists():
        problems.append(f"Missing known-difficult regression fixture: {known_difficult}")

    if problems:
        print("VALIDATION FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("Validation passed: schema, rubric, list registry, and fixtures are all sound.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="entity_screening", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the full V1 pipeline")
    run_parser.add_argument("--nsf-file", type=Path, default=None, help="Local NSF awards JSON file")
    run_parser.add_argument("--nsf-date-start", default=None, help="mm/dd/yyyy, live API only")
    run_parser.add_argument("--nsf-date-end", default=None, help="mm/dd/yyyy, live API only")
    run_parser.add_argument(
        "--opensanctions-file", type=Path, required=True, help="Path to targets.simple.csv"
    )
    run_parser.add_argument("--rubric-file", type=Path, default=None, help="JSON rubric override")
    run_parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    run_parser.add_argument("--excel", action="store_true", help="Also export .xlsx")
    run_parser.add_argument(
        "--db-file", type=Path, default=storage.DEFAULT_DB_PATH, help="DuckDB working file"
    )
    run_parser.set_defaults(func=_cmd_run)

    validate_parser = subparsers.add_parser("validate", help="Structural sanity checks")
    validate_parser.set_defaults(func=_cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
