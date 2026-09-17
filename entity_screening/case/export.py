"""The investigative file: Sec. 51B.153's named output artifact.

Export produces the worked worksheet plus its adjudication -- not a table of
matches (use-case-01 Section 8). What makes the file defensible is not that
the case was reviewed but that every finding was dispositioned by a named
person on a stated basis, and that a Sec. 51B.153 department-head
certification (where one was needed) is inside it.

Redaction is on by default. The declaration is modeled and displayed as a
structured affiliation list, never a DS-160 replica; the subject's
classified fields (date of birth, passport / national ID numbers, home
address) are replaced with a redaction marker unless the caller explicitly
asks for an unredacted export (use-case-01 Section 9).

Every finding's concern-list / ownership evidence carries its
`source_attribution` (GLEIF's, the concern list's) through to the file --
Section 10's licence NFR applies to this output the same as to the batch
CSV, and `tests/test_output_contract.py` asserts it here.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import duckdb

from entity_screening.case import service, store
from entity_screening.case.store import (
    _discovered_to_dict,
    _flag_to_dict,
    _hit_to_dict,
    _nearest_to_dict,
    _search_to_dict,
)
from entity_screening.common.manifest import (
    DEFAULT_RUNS_DIR,
    InvestigativeFileManifest,
    prune_sibling_export_dirs,
)

REDACTION_MARKER = {"_redacted": True, "_reason": "field-level sensitive (use-case-01 Section 9)"}

# The synthetic marker must survive to the export, not just the screen. The
# investigative file is the artifact designed to leave the system -- a
# downloaded JSON/XLSX that names a real concern-listed company connected by
# an invented edge to a fabricated subsidiary, with no provenance marker, is
# the one output here that could be mistaken for a real finding about a real
# company. The Streamlit banner protects the screen; this protects the file.
PROVENANCE_NOTICE = (
    "SYNTHETIC DEMONSTRATION DATA -- NOT A REAL FINDING ABOUT ANY REAL PERSON "
    "OR COMPANY. This build handles no real declaration data (use-case-01 "
    "Section 9); the subject and their declaration are fabricated in full, "
    "including their declared employer's own corporate identity (a fabricated "
    "GLEIF LEI record; LEIs prefixed 'SYNTH...'). Named entities further up an "
    "ownership chain may be real organisations whose GLEIF LEI records and "
    "concern-list designations are real, extracted from a real GLEIF Golden "
    "Copy download (see tests/fixtures/demo_case/gleif.NOTICE.md) -- only the "
    "edge connecting the fabricated subsidiary to that real parent is "
    "invented. Do not treat this file, in whole or in part, as a screening "
    "determination."
)


def _finding_to_dict(finding) -> dict:
    return {
        "finding_id": finding.finding_id,
        "case_id": finding.case_id,
        "run_id": finding.run_id,
        "discovered": _discovered_to_dict(finding.discovered),
        "declaration_search": [_search_to_dict(s) for s in finding.declaration_search],
        "factual_basis": finding.factual_basis.value,
        "nearest_declared": [_nearest_to_dict(n) for n in finding.nearest_declared],
    }


def _tie_to_dict(tie) -> dict:
    return {
        "tie_id": tie.tie_id,
        "case_id": tie.case_id,
        "run_id": tie.run_id,
        "tie_kind": tie.tie_kind.value,
        "anchor_affiliation_id": tie.anchor_affiliation_id,
        "related_finding_id": tie.related_finding_id,
        "concern_entity_name": tie.concern_entity_name,
        "country": tie.country,
        "country_on_adversary_list": tie.country_on_adversary_list,
        "adversary_list_version": tie.adversary_list_version,
        "first_observed": tie.first_observed,
        "last_observed": tie.last_observed,
        "record_count": tie.record_count,
        "concern_list_evidence": [_hit_to_dict(h) for h in tie.concern_list_evidence],
        "ownership_evidence": [_flag_to_dict(f) for f in tie.ownership_evidence],
        "hq_country": tie.hq_country,
        "hq_country_on_adversary_list": tie.hq_country_on_adversary_list,
    }


def build_investigative_file(
    conn: duckdb.DuckDBPyConnection, case_id: str, *, redact: bool = True
) -> dict:
    case = store.load_case(conn, case_id)
    if case is None:
        raise ValueError(f"Unknown case_id: {case_id!r}")
    subject = store.load_subject(conn, case.subject_id)
    declaration = store.load_declaration(conn, case.declaration_id)
    findings = store.load_findings(conn, case_id)
    ties = store.load_ties(conn, case_id)
    effective = store.effective_actions(conn, case_id)
    history = store.load_worksheet_actions(conn, case_id)
    tie_effective = store.effective_tie_actions(conn, case_id)
    tie_history = store.load_tie_actions(conn, case_id)
    adjudications = store.load_adjudications(conn, case_id)
    certifications = store.load_certifications(conn, case_id)
    outcome = service.latest_outcome(conn, case_id)

    return {
        "provenance": {
            "synthetic": bool(case.synthetic and (subject.synthetic if subject else True)),
            "notice": PROVENANCE_NOTICE,
        },
        "case": {
            "case_id": case.case_id,
            "case_kind": case.case_kind.value,
            "trigger": case.trigger,
            "access_scope": case.access_scope,
            "coverage_basis": case.coverage_basis.value if case.coverage_basis else None,
            "statutory_deadline": case.statutory_deadline.isoformat()
            if case.statutory_deadline
            else None,
            "state": case.state.value,
            "office_id": case.office_id,
        },
        "subject": {
            "subject_id": subject.subject_id if subject else None,
            "display_name": subject.display_name if subject else None,
            "coverage_basis": (
                subject.coverage_basis.value if subject and subject.coverage_basis else None
            ),
            "classified_fields": (
                REDACTION_MARKER
                if (redact or subject is None)
                else subject.classified_fields
            ),
        },
        "declaration": {
            "sources": [
                {
                    "source_id": s.source_id,
                    "kind": s.kind,
                    "present": s.present,
                    "scope_kind": s.scope_kind.value,
                    "scope_descriptor": s.scope_descriptor,
                }
                for s in (declaration.sources if declaration else ())
            ],
            "affiliations": [
                {
                    "affiliation_id": a.affiliation_id,
                    "source_id": a.source_id,
                    "institution_name": a.institution_name,
                    "country": a.country,
                    "role": a.role,
                    "start_date": a.start_date,
                    "end_date": a.end_date,
                    "activity_kind": a.activity_kind,
                }
                for a in (declaration.affiliations if declaration else ())
            ],
        },
        # concern_ties sorts before findings; the Sec. 51B.151(b) observations
        # are the higher-stakes ones and a reader should hit them first.
        "concern_ties": [_tie_to_dict(t) for t in ties],
        "findings": [_finding_to_dict(f) for f in findings],
        "worksheet": {
            "effective_actions": {
                fid: {
                    "action": wa.action.value,
                    "reason_code": wa.reason_code,
                    "reason_note": wa.reason_note,
                    "actor": wa.actor,
                    "recorded_at": wa.recorded_at,
                    "batch_id": wa.batch_id,
                }
                for fid, wa in effective.items()
            },
            "action_history": [
                {
                    "finding_id": wa.finding_id,
                    "action": wa.action.value,
                    "reason_code": wa.reason_code,
                    "reason_note": wa.reason_note,
                    "actor": wa.actor,
                    "recorded_at": wa.recorded_at,
                    "batch_id": wa.batch_id,
                }
                for wa in history
            ],
        },
        "tie_actions": {
            "effective_actions": {
                tid: {
                    "action": ta.action.value,
                    "reason_code": ta.reason_code,
                    "reason_note": ta.reason_note,
                    "actor": ta.actor,
                    "recorded_at": ta.recorded_at,
                    "batch_id": ta.batch_id,
                }
                for tid, ta in tie_effective.items()
            },
            "action_history": [
                {
                    "tie_id": ta.tie_id,
                    "action": ta.action.value,
                    "reason_code": ta.reason_code,
                    "reason_note": ta.reason_note,
                    "actor": ta.actor,
                    "recorded_at": ta.recorded_at,
                    "batch_id": ta.batch_id,
                }
                for ta in tie_history
            ],
        },
        "adjudications": [asdict(a) for a in adjudications],
        "certifications": [asdict(c) for c in certifications],
        "outcome": outcome,
    }


def export_investigative_file(
    conn: duckdb.DuckDBPyConnection,
    case_id: str,
    *,
    fmt: str = "json",
    redact: bool = True,
    runs_dir: Path | str = DEFAULT_RUNS_DIR,
) -> tuple[Path, InvestigativeFileManifest]:
    payload = build_investigative_file(conn, case_id, redact=redact)
    adjudications = payload["adjudications"]
    manifest = InvestigativeFileManifest.create(
        case_id=case_id,
        redaction_profile="default" if redact else "unredacted",
        adjudication_seq_exported=adjudications[-1]["seq"] if adjudications else None,
        fmt=fmt,
        finding_count=len(payload["findings"]),
    )
    payload["export"] = {
        "export_id": manifest.export_id,
        "exported_at": manifest.exported_at,
        "redaction_profile": manifest.redaction_profile,
        "adjudication_seq_exported": manifest.adjudication_seq_exported,
    }
    export_dir = manifest.export_dir(runs_dir)
    prune_sibling_export_dirs(export_dir)  # S6 (interim): cap disk growth from repeated GETs

    if fmt == "xlsx":
        out_path = export_dir / "investigative_file.xlsx"
        _write_xlsx(payload, out_path)
    else:
        out_path = export_dir / "investigative_file.json"
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    manifest.write(runs_dir)
    return out_path, manifest


_FINDING_SHEET_COLUMNS = [
    "finding_id", "discovered_source", "institution_name", "country",
    "first_observed", "last_observed", "record_count", "factual_basis",
    "declaration_sources_searched", "in_scope_of",
]
_TIE_SHEET_COLUMNS = [
    "tie_id", "tie_kind", "concern_entity_name", "anchor_affiliation_id",
    "related_finding_id", "country", "country_on_adversary_list",
    "adversary_list_version", "concern_lists", "best_confidence",
    "concern_evidence_json", "ownership_evidence_json",
]
_ACTION_SHEET_COLUMNS = [
    "finding_id", "action", "reason_code", "reason_note", "actor", "recorded_at", "batch_id",
]
_TIE_ACTION_SHEET_COLUMNS = [
    "tie_id", "action", "reason_code", "reason_note", "actor", "recorded_at", "batch_id",
]
_ADJUDICATION_SHEET_COLUMNS = [
    "case_id", "seq", "assessment", "recommendation", "actor", "recorded_at",
]
_CERTIFICATION_SHEET_COLUMNS = [
    "case_id", "finding_id", "substance_of_failure", "reasons_for_disregarding",
    "department_head", "recorded_at",
]


def _write_xlsx(payload: dict, out_path: Path) -> None:
    import pandas as pd

    def sheet(writer, name, rows, columns):
        # Explicit `columns` so the header row renders even with zero data --
        # a reader can tell "none recorded" from "not implemented".
        pd.DataFrame(rows, columns=columns).to_excel(writer, sheet_name=name, index=False)

    with pd.ExcelWriter(out_path) as writer:
        # First sheet: the synthetic-data marker, so it is the first thing a
        # reader of the file sees.
        pd.DataFrame(
            [
                {"field": "synthetic", "value": str(payload["provenance"]["synthetic"])},
                {"field": "notice", "value": payload["provenance"]["notice"]},
            ]
        ).to_excel(writer, sheet_name="READ ME -- provenance", index=False)
        pd.DataFrame([payload["case"]]).to_excel(writer, sheet_name="Case", index=False)
        pd.DataFrame(payload["declaration"]["affiliations"]).to_excel(
            writer, sheet_name="Declared affiliations", index=False
        )
        # Concern ties before Findings -- the Sec. 51B.151(b) observations are
        # the higher-stakes ones and must not be buried under omission rows.
        sheet(
            writer,
            "Concern ties",
            [
                {
                    "tie_id": t["tie_id"],
                    "tie_kind": t["tie_kind"],
                    "concern_entity_name": t["concern_entity_name"],
                    "anchor_affiliation_id": t["anchor_affiliation_id"] or "",
                    "related_finding_id": t["related_finding_id"] or "",
                    "country": t["country"] or "",
                    "country_on_adversary_list": (
                        "not yet checked" if t["country_on_adversary_list"] is None
                        else str(t["country_on_adversary_list"])
                    ),
                    "adversary_list_version": t["adversary_list_version"] or "",
                    "concern_lists": ", ".join(h["list_name"] for h in t["concern_list_evidence"]),
                    "best_confidence": max(
                        (h["confidence"] for h in t["concern_list_evidence"]), default=0.0
                    ),
                    "concern_evidence_json": json.dumps(t["concern_list_evidence"], sort_keys=True),
                    "ownership_evidence_json": json.dumps(t["ownership_evidence"], sort_keys=True),
                }
                for t in payload["concern_ties"]
            ],
            _TIE_SHEET_COLUMNS,
        )
        sheet(
            writer,
            "Findings",
            [
                {
                    "finding_id": f["finding_id"],
                    "discovered_source": f["discovered"]["source"],
                    "institution_name": f["discovered"]["institution_name"],
                    "country": f["discovered"]["country"],
                    "first_observed": f["discovered"]["first_observed"],
                    "last_observed": f["discovered"]["last_observed"],
                    "record_count": f["discovered"]["record_count"],
                    "factual_basis": f["factual_basis"],
                    "declaration_sources_searched": ", ".join(
                        s["source_kind"] for s in f["declaration_search"]
                    ),
                    "in_scope_of": ", ".join(
                        s["source_kind"] for s in f["declaration_search"] if s["covers_this_item"]
                    )
                    or "(none)",
                }
                for f in payload["findings"]
            ],
            _FINDING_SHEET_COLUMNS,
        )
        sheet(writer, "Worksheet actions", payload["worksheet"]["action_history"], _ACTION_SHEET_COLUMNS)
        sheet(writer, "Tie actions", payload["tie_actions"]["action_history"], _TIE_ACTION_SHEET_COLUMNS)
        sheet(writer, "Adjudications", payload["adjudications"], _ADJUDICATION_SHEET_COLUMNS)
        sheet(writer, "Certifications", payload["certifications"], _CERTIFICATION_SHEET_COLUMNS)
