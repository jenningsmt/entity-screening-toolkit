"""Command-line entry point: python -m entity_screening.cli <subcommand>.

Subcommands:
    run       full pipeline: ingest -> resolve -> screen -> score -> export
    validate  structural sanity checks (Epic H), no data required
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from entity_screening import pipeline
from entity_screening.bibliometric.topic_similarity import CET_CORPUS_FILE, DOD_CORPUS_FILE
from entity_screening.common import storage
from entity_screening.common.manifest import RunManifest
from entity_screening.common.schema import (
    _FORBIDDEN_OBSERVATION_FIELD_TOKENS,
    _OBSERVATION_GRAPH_ALLOWED_FIELDS,
    ConcernTie,
    CoverageBasis,
    Declaration,
    DiscoveredAffiliation,
    DeclarationSearch,
    Finding,
    MatchStatus,
    NearestDeclared,
    Subject,
)
from entity_screening.common.attribution import attribution_for
from entity_screening.ingestion.dod_1260h import DEFAULT_DATA_FILE as DEFAULT_DOD_1260H_FILE
from entity_screening.resolution.matcher import DEFAULT_THRESHOLD
from entity_screening.screening.adversary_list import load_adversary_list
from entity_screening.screening.lists import registered_lists
from entity_screening.screening.rps_schema import (
    RPS_OBSERVATION_ALLOWED_FIELDS,
    ScreeningEvent,
    ScreeningMatch,
    ScreeningTrigger,
)
from entity_screening.screening.section_117 import LIST_NAME as SECTION_117_LIST_NAME
from entity_screening.screening.section_117 import DEFAULT_INSTITUTION_THRESHOLD
from entity_screening.scoring.rubric import STOCK_RUBRIC, rubric_from_dict


def run_pipeline(args: argparse.Namespace) -> RunManifest:
    rubric = STOCK_RUBRIC
    if args.rubric_file:
        rubric = rubric_from_dict(json.loads(Path(args.rubric_file).read_text(encoding="utf-8")))

    manifest, scored_entities = pipeline.run_screening(
        nsf_file=args.nsf_file,
        nsf_date_start=args.nsf_date_start,
        nsf_date_end=args.nsf_date_end,
        opensanctions_file=args.opensanctions_file,
        rubric=rubric,
        threshold=args.threshold,
        db_path=args.db_file,
        dod_1260h_file=args.dod_1260h_file,
        section_117_file=args.section_117_file,
        section_117_institution_threshold=args.section_117_institution_threshold,
    )

    ownership_flags_count = None
    if args.gleif_lei_file and args.gleif_relationships_file:
        _gleif_manifest, ownership_flags = pipeline.enrich_ownership(
            manifest.run_id,
            args.gleif_lei_file,
            args.gleif_relationships_file,
            threshold=args.threshold,
            db_path=args.db_file,
        )
        ownership_flags_count = len(ownership_flags)
        # Re-scores under the (possibly ownership-inclusive) final state before
        # export, so the CLI writes one export reflecting everything computed
        # rather than an initial one and a second, ownership-aware one.
        scored_entities = pipeline.rescore_run(manifest.run_id, rubric, db_path=args.db_file)

    bibliometric_hits_count = None
    if args.enrich_bibliometric:
        _bib_manifest, bibliometric_hits = pipeline.enrich_bibliometric(
            manifest.run_id,
            contact_email=args.openalex_contact_email,
            db_path=args.db_file,
        )
        bibliometric_hits_count = len(bibliometric_hits)
        scored_entities = pipeline.rescore_run(manifest.run_id, rubric, db_path=args.db_file)

    topic_similarity_flags_count = None
    if args.enrich_topic_similarity:
        _topic_manifest, topic_flags = pipeline.enrich_topic_similarity(
            manifest.run_id, db_path=args.db_file
        )
        topic_similarity_flags_count = len(topic_flags)

    out_csv, csv_manifest = pipeline.export_scored_entities(
        scored_entities,
        source_run_id=manifest.run_id,
        rubric=rubric,
        match_thresholds=manifest.match_thresholds,
        fmt="csv",
    )
    if args.excel:
        pipeline.export_scored_entities(
            scored_entities,
            source_run_id=manifest.run_id,
            rubric=rubric,
            match_thresholds=manifest.match_thresholds,
            fmt="xlsx",
        )

    total_hits = sum(len(s.screening_hits) for s in scored_entities)
    summary = (
        f"Run {manifest.run_id}: {len(scored_entities)} entities resolved, "
        f"{total_hits} candidate hits, "
        f"{manifest.ingestion_error_counts.get('total', 0)} ingestion errors logged.\n"
    )
    if ownership_flags_count is not None:
        summary += f"Foreign-control flags: {ownership_flags_count}\n"
    if bibliometric_hits_count is not None:
        summary += f"Bibliometric candidate hits: {bibliometric_hits_count}\n"
    if topic_similarity_flags_count is not None:
        summary += (
            f"Topic-similarity flags (advisory, not scored): {topic_similarity_flags_count}\n"
        )
    summary += f"CSV: {out_csv} (export {csv_manifest.export_id})\nDuckDB: {args.db_file}"
    print(summary)
    return manifest


def _cmd_run(args: argparse.Namespace) -> int:
    if bool(args.gleif_lei_file) != bool(args.gleif_relationships_file):
        print(
            "Error: --gleif-lei-file and --gleif-relationships-file must be "
            "supplied together (or both omitted to skip ownership analysis)."
        )
        return 1
    if args.enrich_topic_similarity and not args.enrich_bibliometric:
        print(
            "Error: --enrich-topic-similarity requires --enrich-bibliometric in "
            "the same run (topic similarity ranks the PIs enrich_bibliometric "
            "resolves; it has nothing to walk otherwise)."
        )
        return 1
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

    # The fact/judgment boundary (use-case-01 Section 4): the observation types
    # -- Finding (the Sec. 51B.153 omission test) and ConcernTie (the
    # Sec. 51B.151(b) tie test) -- state observable facts and never evaluate
    # them. Guard the whole graph of each, not just the outer shell: an
    # evaluative field on a nested type reaches the investigative-file export
    # just as surely.
    from dataclasses import fields as _dc_fields

    _observation_graph_types = {
        "Finding": Finding,
        "ConcernTie": ConcernTie,
        "DiscoveredAffiliation": DiscoveredAffiliation,
        "DeclarationSearch": DeclarationSearch,
        "NearestDeclared": NearestDeclared,
    }
    for type_name, dc in _observation_graph_types.items():
        actual = {f.name for f in _dc_fields(dc)}
        allowed = _OBSERVATION_GRAPH_ALLOWED_FIELDS.get(type_name)
        if allowed is None:
            problems.append(
                f"{type_name} is in an observation graph but has no entry in "
                "_OBSERVATION_GRAPH_ALLOWED_FIELDS — add one deliberately."
            )
            continue
        if actual != allowed:
            problems.append(
                f"{type_name}'s fields {sorted(actual)} do not match the frozen "
                f"allowlist {sorted(allowed)} — the fact/judgment boundary is "
                "enforced here, so widening what the system may assert about a "
                "person must be a deliberate edit to _OBSERVATION_GRAPH_ALLOWED_FIELDS "
                "in the same commit (use-case-01 Section 4)."
            )
        forbidden = {
            name
            for name in actual
            for token in _FORBIDDEN_OBSERVATION_FIELD_TOKENS
            if token in name.lower()
        }
        if forbidden:
            problems.append(
                f"{type_name} carries evaluative field(s) {sorted(forbidden)} — an "
                "observation type may not hold a severity/risk/priority/score/"
                "materiality/tier/weight/disposition/impair/prevent claim about a person."
            )

    # Same guard, extended to restricted-party screening (use-case-02 Section
    # 3) -- kept as RPS's own allowlist in screening/rps_schema.py rather than
    # merged into _OBSERVATION_GRAPH_ALLOWED_FIELDS above, since common/schema.py
    # does not import from screening/ (see that module's docstring).
    for type_name, dc in {"ScreeningMatch": ScreeningMatch}.items():
        actual = {f.name for f in _dc_fields(dc)}
        allowed = RPS_OBSERVATION_ALLOWED_FIELDS.get(type_name)
        if allowed is None:
            problems.append(
                f"{type_name} is in the RPS observation graph but has no entry in "
                "RPS_OBSERVATION_ALLOWED_FIELDS — add one deliberately."
            )
            continue
        if actual != allowed:
            problems.append(
                f"{type_name}'s fields {sorted(actual)} do not match the frozen "
                f"allowlist {sorted(allowed)} — the fact/judgment boundary is "
                "enforced here, so widening what RPS may assert about a party "
                "must be a deliberate edit to RPS_OBSERVATION_ALLOWED_FIELDS "
                "in the same commit (use-case-02 Section 3)."
            )
        forbidden = {
            name
            for name in actual
            for token in _FORBIDDEN_OBSERVATION_FIELD_TOKENS
            if token in name.lower()
        }
        if forbidden:
            problems.append(
                f"{type_name} carries evaluative field(s) {sorted(forbidden)} — an "
                "RPS observation type may not hold a severity/risk/priority/score/"
                "materiality/tier/weight/disposition/impair/prevent claim."
            )

    # No real PII by construction: Subject / Declaration reject synthetic=False.
    for pii_type in (Subject, Declaration):
        try:
            if pii_type is Subject:
                pii_type(
                    subject_id="x",
                    display_name="x",
                    coverage_basis=CoverageBasis.FOREIGN_NATIONAL_NO_PR,
                    synthetic=False,
                    classified_fields={},
                )
            else:
                pii_type(
                    declaration_id="x",
                    subject_id="x",
                    synthetic=False,
                    sources=(),
                    affiliations=(),
                )
        except ValueError:
            pass
        else:
            problems.append(
                f"{pii_type.__name__}(synthetic=False) was accepted — this build "
                "must make a real subject unrepresentable, not merely discouraged "
                "(use-case-01 Section 9)."
            )

    # Same guard, extended to RPS's ScreeningEvent (use-case-02 Section 3).
    try:
        ScreeningEvent(
            event_id="x",
            trigger=ScreeningTrigger.PURCHASING_FINANCIAL,
            case_id=None,
            requested_by="x",
            requested_at="x",
            synthetic=False,
        )
    except ValueError:
        pass
    else:
        problems.append(
            "ScreeningEvent(synthetic=False) was accepted — this build must make "
            "a real screening event unrepresentable, not merely discouraged "
            "(use-case-01 Section 9, extended to RPS)."
        )

    expected_lists = {"opensanctions_consolidated", "dod_section_1260h"}
    missing_lists = expected_lists - registered_lists().keys()
    if missing_lists:
        problems.append(
            "Missing expected entity-of-concern list(s) in screening/lists.py's "
            f"registry: {sorted(missing_lists)}"
        )

    if not DEFAULT_DOD_1260H_FILE.exists():
        problems.append(f"Missing bundled DoD 1260H curated list: {DEFAULT_DOD_1260H_FILE}")

    try:
        adversary_list = load_adversary_list()
    except Exception as exc:
        problems.append(f"Foreign-adversary-country list failed to load: {exc}")
    else:
        for code, citations in adversary_list.countries.items():
            if len(code) != 2 or not code.isalpha() or not code.isupper():
                problems.append(
                    f"Foreign-adversary-country list entry {code!r} is not a valid "
                    "ISO 3166-1 alpha-2 code."
                )
            if not citations:
                problems.append(
                    f"Foreign-adversary-country list entry {code!r} has no citations."
                )

    # Finding 6: every source a hit can be tagged against needs an attribution
    # entry (common/attribution.py) or its license/caveat silently doesn't
    # reach the evidence trail -- this is what makes adding a new
    # EntityOfConcernList (or Section 117's own list_name) without attribution
    # a CI failure instead of a shipped gap.
    attributable_sources = set(registered_lists().keys()) | {SECTION_117_LIST_NAME}
    missing_attribution = {s for s in attributable_sources if not attribution_for(s)}
    if missing_attribution:
        problems.append(
            "Missing entity_screening/common/attribution.py entry for source(s): "
            f"{sorted(missing_attribution)}"
        )

    if not DOD_CORPUS_FILE.exists():
        problems.append(f"Missing bundled DoD critical-technology-areas corpus: {DOD_CORPUS_FILE}")
    if not CET_CORPUS_FILE.exists():
        problems.append(f"Missing bundled CET list corpus: {CET_CORPUS_FILE}")

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
    run_parser.add_argument(
        "--dod-1260h-file",
        type=Path,
        default=DEFAULT_DOD_1260H_FILE,
        help="DoD Section 1260H curated list JSON (defaults to the bundled snapshot)",
    )
    run_parser.add_argument(
        "--section-117-file",
        type=Path,
        default=None,
        help="Section 117 foreign gift/contract disclosure bulk .xlsx file -- enables "
        "the foreign-funding cross-check; omit to skip it (no bundled default, like GLEIF)",
    )
    run_parser.add_argument(
        "--section-117-institution-threshold",
        type=float,
        default=DEFAULT_INSTITUTION_THRESHOLD,
        help="Higher than --threshold by default: a loose institution-name match "
        "would misfile disclosure evidence under the wrong entity entirely",
    )
    run_parser.add_argument(
        "--gleif-lei-file",
        type=Path,
        default=None,
        help="GLEIF Level 1 (LEI-CDF) concatenated CSV -- enables ownership/"
        "foreign-control analysis (Epic C); omit both GLEIF flags to skip it",
    )
    run_parser.add_argument(
        "--gleif-relationships-file",
        type=Path,
        default=None,
        help="GLEIF Level 2 (RR-CDF) concatenated CSV -- required alongside --gleif-lei-file",
    )
    run_parser.add_argument(
        "--enrich-bibliometric",
        action="store_true",
        help="Resolve this run's PIs to OpenAlex authors and cross-check their "
        "co-authorship/affiliation history (Epic E) -- a live API call, no file to supply",
    )
    run_parser.add_argument(
        "--openalex-contact-email",
        default=None,
        help="Optional contact email sent as OpenAlex's 'mailto' polite-pool parameter",
    )
    run_parser.add_argument(
        "--enrich-topic-similarity",
        action="store_true",
        help="Rank this run's PIs' real papers against DoD/CET critical-technology "
        "reference corpora (deferred VSS work) -- advisory only, never scored. "
        "Requires --enrich-bibliometric in the same invocation. Needs torch/"
        "sentence-transformers (see requirements-vss.txt), not installed by default.",
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
