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
from entity_screening.common.manifest import DEFAULT_RUNS_DIR, InvestigativeFileManifest

REDACTION_MARKER = {"_redacted": True, "_reason": "field-level sensitive (use-case-01 Section 9)"}


def _finding_to_dict(finding) -> dict:
    return {
        "finding_id": finding.finding_id,
        "case_id": finding.case_id,
        "run_id": finding.run_id,
        "discovered": _discovered_to_dict(finding.discovered),
        "declaration_search": [_search_to_dict(s) for s in finding.declaration_search],
        "factual_basis": finding.factual_basis.value,
        "nearest_declared": [_nearest_to_dict(n) for n in finding.nearest_declared],
        "concern_list_evidence": [_hit_to_dict(h) for h in finding.concern_list_evidence],
        "ownership_evidence": [_flag_to_dict(f) for f in finding.ownership_evidence],
    }


def build_investigative_file(
    conn: duckdb.DuckDBPyConnection, case_id: str, *, redact: bool = True
) -> dict:
    case = store.load_case(conn, case_id)
    if case is None:
        raise ValueError(f"Unknown case_id: {case_id!r}")
    subject = store.load_subject(conn, case.subject_id)
    declaration = store.load_declaration_for_subject(conn, case.subject_id)
    findings = store.load_findings(conn, case_id)
    effective = store.effective_actions(conn, case_id)
    history = store.load_worksheet_actions(conn, case_id)
    adjudications = store.load_adjudications(conn, case_id)
    certifications = store.load_certifications(conn, case_id)
    outcome = service.latest_outcome(conn, case_id)

    return {
        "case": {
            "case_id": case.case_id,
            "trigger": case.trigger,
            "access_scope": case.access_scope,
            "coverage_basis": case.coverage_basis.value,
            "statutory_deadline": case.statutory_deadline.isoformat()
            if case.statutory_deadline
            else None,
            "state": case.state.value,
            "office_id": case.office_id,
        },
        "subject": {
            "subject_id": subject.subject_id if subject else None,
            "display_name": subject.display_name if subject else None,
            "coverage_basis": subject.coverage_basis.value if subject else None,
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

    if fmt == "xlsx":
        out_path = export_dir / "investigative_file.xlsx"
        _write_xlsx(payload, out_path)
    else:
        out_path = export_dir / "investigative_file.json"
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    manifest.write(runs_dir)
    return out_path, manifest


def _write_xlsx(payload: dict, out_path: Path) -> None:
    import pandas as pd

    with pd.ExcelWriter(out_path) as writer:
        pd.DataFrame([payload["case"]]).to_excel(writer, sheet_name="Case", index=False)
        pd.DataFrame(payload["declaration"]["affiliations"]).to_excel(
            writer, sheet_name="Declared affiliations", index=False
        )
        pd.DataFrame(
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
                    "concern_lists": ", ".join(
                        h["list_name"] for h in f["concern_list_evidence"]
                    )
                    or "",
                    "concern_evidence_json": json.dumps(f["concern_list_evidence"], sort_keys=True),
                    "ownership_evidence_json": json.dumps(f["ownership_evidence"], sort_keys=True),
                }
                for f in payload["findings"]
            ]
        ).to_excel(writer, sheet_name="Findings", index=False)
        pd.DataFrame(payload["worksheet"]["action_history"]).to_excel(
            writer, sheet_name="Worksheet actions", index=False
        )
        pd.DataFrame(payload["adjudications"]).to_excel(
            writer, sheet_name="Adjudications", index=False
        )
        pd.DataFrame(payload["certifications"]).to_excel(
            writer, sheet_name="Certifications", index=False
        )
