"""HTTP surface for Use Case 01 -- HB 127 researcher screening.

An APIRouter mounted by api/main.py, kept separate so main.py's batch routes
and this file's case routes stay legible apart. Same posture as the batch
side: mutating actions go through the shared action-secret dependency
(_require_action_secret); reads are open. The demo case (case_id="demo")
self-heals from bundled fixtures on first access, with no live network call
-- the mirror of _ensure_demo_run_exists.
"""
from __future__ import annotations

from typing import Any

import duckdb
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from entity_screening import pipeline
from entity_screening.api.deps import db_path as _db_path
from entity_screening.api.deps import require_action_secret
from entity_screening.api.deps import runs_dir as _runs_dir
from entity_screening.case import demo, export as case_export, service, store
from entity_screening.case.service import CaseStateError
from entity_screening.case.vocab import DISMISS_REASON_CODES, ESCALATION_REASON_CODES
from entity_screening.common import storage
from entity_screening.common.schema import (
    Case,
    CaseState,
    CoverageBasis,
    DeclaredAffiliation,
    Declaration,
    DeclarationSource,
    ScopeKind,
    Subject,
    WorksheetActionKind,
)

router = APIRouter(prefix="/cases", tags=["hb127-case"])


# --------------------------------------------------------------------------
# DTOs
# --------------------------------------------------------------------------


class DeclarationSourceIn(BaseModel):
    source_id: str
    kind: str
    present: bool = True
    scope_kind: str
    scope_descriptor: dict[str, Any] = {}


class DeclaredAffiliationIn(BaseModel):
    affiliation_id: str
    source_id: str
    institution_name: str
    country: str | None = None
    role: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    activity_kind: str | None = None


class CreateCaseRequest(BaseModel):
    case_id: str
    subject_id: str
    subject_display_name: str
    coverage_basis: str  # "151a1" | "151a2"
    synthetic: bool = True
    classified_fields: dict[str, Any] = {}
    trigger: str
    access_scope: str
    statutory_deadline: str | None = None
    office_id: str = "default"
    declaration_sources: list[DeclarationSourceIn]
    declared_affiliations: list[DeclaredAffiliationIn]


class ReconcileRequest(BaseModel):
    # Live OpenAlex is opt-in; the demo runs entirely on fixtures.
    contact_email: str | None = None


class ActionRequest(BaseModel):
    action: str  # dismiss | request_clarification | escalate | certification_required
    reason_code: str
    reason_note: str = ""
    actor: str


class BulkActionRequest(ActionRequest):
    finding_ids: list[str]


class AdjudicationRequest(BaseModel):
    assessment: str
    recommendation: str
    actor: str


class CertificationRequest(BaseModel):
    finding_id: str
    substance_of_failure: str
    reasons_for_disregarding: str
    department_head: str


class TransitionRequest(BaseModel):
    target_state: str


class OutcomeRequest(BaseModel):
    outcome: str
    actor: str
    note: str = ""


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _connect() -> duckdb.DuckDBPyConnection:
    return storage.connect(_db_path())


def _ensure_demo_case_exists(conn: duckdb.DuckDBPyConnection) -> None:
    """Builds and reconciles the demo case on first access -- fixtures only,
    no live network call. Idempotent: build_demo_case replaces, and
    reconcile_case is current-state."""
    if demo.demo_case_exists(conn):
        return
    demo.build_demo_case(conn)
    pipeline.reconcile_case(
        demo.DEMO_CASE_ID,
        db_path=_db_path(),
        runs_dir=_runs_dir(),
        works_fixture=demo.load_demo_works_fixture(),
        gleif_lei_file=demo.DEMO_GLEIF_LEI_FILE,
        gleif_relationships_file=demo.DEMO_GLEIF_RELATIONSHIPS_FILE,
    )


def _load_case_or_404(conn: duckdb.DuckDBPyConnection, case_id: str) -> Case:
    if case_id == demo.DEMO_CASE_ID:
        _ensure_demo_case_exists(conn)
    case = store.load_case(conn, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Unknown case_id: {case_id}")
    return case


def _worksheet_payload(conn: duckdb.DuckDBPyConnection, case_id: str) -> dict:
    view = service.worksheet(conn, case_id)
    return {
        "case_id": case_id,
        "state": view.case.state.value,
        "coverage_basis": view.case.coverage_basis.value,
        "statutory_deadline": (
            view.case.statutory_deadline.isoformat()
            if view.case.statutory_deadline
            else None
        ),
        "unactioned_count": view.unactioned_count,
        "can_close": view.can_close,
        "rows": [
            {
                "finding": case_export._finding_to_dict(row.finding),
                "action": (
                    None
                    if row.action is None
                    else {
                        "action": row.action.action.value,
                        "reason_code": row.action.reason_code,
                        "reason_note": row.action.reason_note,
                        "actor": row.action.actor,
                        "recorded_at": row.action.recorded_at,
                        "batch_id": row.action.batch_id,
                    }
                ),
            }
            for row in view.rows
        ],
    }


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


@router.get("/reason-codes")
def reason_codes() -> dict:
    return {"dismiss": DISMISS_REASON_CODES, "escalation": ESCALATION_REASON_CODES}


@router.get("/dismissal-basis-summary")
def dismissal_basis_summary() -> dict:
    """Section 4.1's by-product: the office's own accumulated answer to 'how
    does your institution define substantial?', aggregated from real
    adjudications rather than a policy guessed at up front."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT reason_code, count(*) FROM worksheet_actions "
            "WHERE action = 'dismiss' GROUP BY reason_code ORDER BY count(*) DESC"
        ).fetchall()
    finally:
        conn.close()
    return {
        "by_reason_code": [{"reason_code": rc, "count": n} for rc, n in rows],
        "vocabulary": DISMISS_REASON_CODES,
    }


@router.post("")
def create_case(
    request: CreateCaseRequest, _s: None = Depends(require_action_secret)
) -> dict:
    from datetime import date

    try:
        subject = Subject(
            subject_id=request.subject_id,
            display_name=request.subject_display_name,
            coverage_basis=CoverageBasis(request.coverage_basis),
            synthetic=request.synthetic,
            classified_fields=request.classified_fields,
        )
        declaration = Declaration(
            declaration_id=f"{request.case_id}-declaration",
            subject_id=request.subject_id,
            synthetic=request.synthetic,
            sources=tuple(
                DeclarationSource(
                    source_id=s.source_id,
                    kind=s.kind,
                    present=s.present,
                    scope_kind=ScopeKind(s.scope_kind),
                    scope_descriptor=s.scope_descriptor,
                )
                for s in request.declaration_sources
            ),
            affiliations=tuple(
                DeclaredAffiliation(
                    affiliation_id=a.affiliation_id,
                    source_id=a.source_id,
                    institution_name=a.institution_name,
                    country=a.country,
                    role=a.role,
                    start_date=a.start_date,
                    end_date=a.end_date,
                    activity_kind=a.activity_kind,
                )
                for a in request.declared_affiliations
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    case = Case(
        case_id=request.case_id,
        subject_id=request.subject_id,
        trigger=request.trigger,
        access_scope=request.access_scope,
        coverage_basis=subject.coverage_basis,
        synthetic=request.synthetic,
        state=CaseState.DECLARATION_ASSEMBLY,
        statutory_deadline=(
            date.fromisoformat(request.statutory_deadline)
            if request.statutory_deadline
            else None
        ),
        office_id=request.office_id,
    )
    conn = _connect()
    try:
        store.save_subject(conn, subject)
        store.save_declaration(conn, declaration)
        store.save_case(conn, case)
    finally:
        conn.close()
    return {"case_id": case.case_id, "state": case.state.value}


@router.post("/{case_id}/reconcile")
def reconcile(
    case_id: str,
    request: ReconcileRequest,
    _s: None = Depends(require_action_secret),
) -> dict:
    conn = _connect()
    try:
        _load_case_or_404(conn, case_id)
    finally:
        conn.close()
    is_demo = case_id == demo.DEMO_CASE_ID
    manifest, findings = pipeline.reconcile_case(
        case_id,
        db_path=_db_path(),
        runs_dir=_runs_dir(),
        contact_email=request.contact_email,
        works_fixture=demo.load_demo_works_fixture() if is_demo else None,
        gleif_lei_file=demo.DEMO_GLEIF_LEI_FILE if is_demo else None,
        gleif_relationships_file=demo.DEMO_GLEIF_RELATIONSHIPS_FILE if is_demo else None,
    )
    return {
        "case_id": case_id,
        "finding_count": len(findings),
        "discovery_sources": manifest.discovery_sources,
        "reconciliation_run_id": manifest.run_id,
    }


@router.get("/{case_id}/worksheet")
def get_worksheet(case_id: str) -> dict:
    conn = _connect()
    try:
        _load_case_or_404(conn, case_id)
        return _worksheet_payload(conn, case_id)
    finally:
        conn.close()


@router.post("/{case_id}/findings/{finding_id}/action")
def post_action(
    case_id: str,
    finding_id: str,
    request: ActionRequest,
    _s: None = Depends(require_action_secret),
) -> dict:
    conn = _connect()
    try:
        _load_case_or_404(conn, case_id)
        try:
            service.record_action(
                conn,
                case_id,
                finding_id,
                WorksheetActionKind(request.action),
                request.reason_code,
                request.reason_note,
                request.actor,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return _worksheet_payload(conn, case_id)
    finally:
        conn.close()


@router.post("/{case_id}/worksheet/actions")
def post_bulk_action(
    case_id: str,
    request: BulkActionRequest,
    _s: None = Depends(require_action_secret),
) -> dict:
    conn = _connect()
    try:
        _load_case_or_404(conn, case_id)
        try:
            batch_id, _ = service.record_bulk_action(
                conn,
                case_id,
                request.finding_ids,
                WorksheetActionKind(request.action),
                request.reason_code,
                request.reason_note,
                request.actor,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        payload = _worksheet_payload(conn, case_id)
        payload["batch_id"] = batch_id
        return payload
    finally:
        conn.close()


@router.post("/{case_id}/transition")
def post_transition(
    case_id: str,
    request: TransitionRequest,
    _s: None = Depends(require_action_secret),
) -> dict:
    conn = _connect()
    try:
        _load_case_or_404(conn, case_id)
        try:
            case = service.transition(conn, case_id, CaseState(request.target_state))
        except CaseStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {"case_id": case_id, "state": case.state.value}
    finally:
        conn.close()


@router.post("/{case_id}/adjudication")
def post_adjudication(
    case_id: str,
    request: AdjudicationRequest,
    _s: None = Depends(require_action_secret),
) -> dict:
    conn = _connect()
    try:
        _load_case_or_404(conn, case_id)
        try:
            adj = service.record_adjudication(
                conn, case_id, request.assessment, request.recommendation, request.actor
            )
        except CaseStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {"case_id": case_id, "seq": adj.seq}
    finally:
        conn.close()


@router.post("/{case_id}/certifications")
def post_certification(
    case_id: str,
    request: CertificationRequest,
    _s: None = Depends(require_action_secret),
) -> dict:
    conn = _connect()
    try:
        _load_case_or_404(conn, case_id)
        try:
            service.record_certification(
                conn,
                case_id,
                request.finding_id,
                request.substance_of_failure,
                request.reasons_for_disregarding,
                request.department_head,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"case_id": case_id, "finding_id": request.finding_id}
    finally:
        conn.close()


@router.post("/{case_id}/outcome")
def post_outcome(
    case_id: str,
    request: OutcomeRequest,
    _s: None = Depends(require_action_secret),
) -> dict:
    conn = _connect()
    try:
        _load_case_or_404(conn, case_id)
        try:
            service.record_outcome(conn, case_id, request.outcome, request.actor, request.note)
        except (ValueError, CaseStateError) as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {"case_id": case_id, "outcome": request.outcome}
    finally:
        conn.close()


@router.get("/{case_id}/investigative-file.json")
def get_investigative_file_json(case_id: str, redact: bool = True) -> FileResponse:
    return _export(case_id, "json", redact)


@router.get("/{case_id}/investigative-file.xlsx")
def get_investigative_file_xlsx(case_id: str, redact: bool = True) -> FileResponse:
    return _export(case_id, "xlsx", redact)


def _export(case_id: str, fmt: str, redact: bool) -> FileResponse:
    conn = _connect()
    try:
        _load_case_or_404(conn, case_id)
        out_path, manifest = case_export.export_investigative_file(
            conn, case_id, fmt=fmt, redact=redact, runs_dir=_runs_dir()
        )
    finally:
        conn.close()
    media_type = (
        "application/json"
        if fmt == "json"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return FileResponse(
        out_path,
        media_type=media_type,
        filename=out_path.name,
        headers={"X-Export-Id": manifest.export_id},
    )
