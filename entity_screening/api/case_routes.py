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
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from entity_screening import pipeline
from entity_screening.api.deps import db_path as _db_path
from entity_screening.api.deps import require_action_secret
from entity_screening.api.deps import runs_dir as _runs_dir
from entity_screening.case import demo, export as case_export, service, store
from entity_screening.case.service import CaseStateError
from entity_screening.case.vocab import (
    COI_ESCALATION_REASON_CODES,
    DISMISS_REASON_CODES,
    ESCALATION_REASON_CODES,
    TIE_DISMISS_REASON_CODES,
    TIE_ESCALATION_REASON_CODES,
)
from entity_screening.common import storage
from entity_screening.common.schema import (
    Case,
    CaseKind,
    CaseState,
    CoverageBasis,
    DeclaredAffiliation,
    Declaration,
    DeclarationSource,
    ScopeKind,
    Subject,
    WorksheetActionKind,
)
from entity_screening.explanation import service as explanation_service
from entity_screening.explanation import store as explanation_store
from entity_screening.explanation.schema import MatchExplanation, ObservationKind

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
    coverage_basis: str | None = None  # "151a1" | "151a2"; None for a non-HB-127 case
    case_kind: str = "hb127_researcher_screening"
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


class BulkTieActionRequest(ActionRequest):
    tie_ids: list[str]


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


def _demo_no_synthesis_call(request: dict) -> object:
    """Epic J's demo-build fixture callable: always returns an ungrounded,
    no-citation response, deterministically, so the bundled public demo's
    explanations ship recitation-only by construction and never depend on a
    live Claude API call or a credential. Recitation-only is documented as a
    complete, valid explanation (explanation/schema.py), not a stand-in for
    one -- this is a deliberate choice to keep the public demo's explanations
    100% real (fully templated from real evidence, no fabricated "sample" LLM
    output shipped as if it were genuine), not a corner cut. Anyone running
    this with a real ANTHROPIC_API_KEY against a non-demo case gets the real
    synthesis step; see docs/plans/<date>-epic-j-evidence-grounded-
    explanation.md."""
    from types import SimpleNamespace

    return SimpleNamespace(content=[SimpleNamespace(type="text", text="", citations=[])])


def _ensure_demo_case_exists(conn: duckdb.DuckDBPyConnection) -> None:
    """Builds and reconciles both demo cases (the HB-127 case and step 6's
    second, annual-COI-disclosure-cycle case for the same synthetic subject)
    on first access -- fixtures only, no live network call. Rebuilds them
    whenever DEMO_FIXTURE_VERSION has moved past what a persistent data
    volume last recorded, so a schema/fixture change (e.g. concern ties split
    out of Finding) does not leave stale rows behind. Idempotent:
    build_demo_case/build_demo_coi_case replace, and reconcile_case is
    current-state. Also pre-generates (and caches) every finding/tie's
    explanation using the no-network fixture above -- so a visitor clicking
    "Explain this match" on a demo case always hits the cache, never a live
    call (Epic J)."""
    version = str(demo.DEMO_FIXTURE_VERSION)
    if (
        demo.demo_case_exists(conn)
        and demo.demo_coi_case_exists(conn)
        and store.demo_meta_get(conn, "fixture_version") == version
    ):
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
    demo.build_demo_coi_case(conn)
    pipeline.reconcile_case(
        demo.DEMO_COI_CASE_ID,
        db_path=_db_path(),
        runs_dir=_runs_dir(),
        works_fixture=demo.load_demo_works_fixture(),
        gleif_lei_file=demo.DEMO_GLEIF_LEI_FILE,
        gleif_relationships_file=demo.DEMO_GLEIF_RELATIONSHIPS_FILE,
    )
    for demo_case_id in (demo.DEMO_CASE_ID, demo.DEMO_COI_CASE_ID):
        case = store.load_case(conn, demo_case_id)
        subject = store.load_subject(conn, case.subject_id)
        synthetic = bool(case.synthetic and (subject.synthetic if subject else True))
        findings = store.load_findings(conn, demo_case_id)
        ties = store.load_ties(conn, demo_case_id)
        for f in findings:
            explanation_service.explain(
                conn, ObservationKind.FINDING, f, demo_case_id,
                _case_context_for(findings, ties, ObservationKind.FINDING, f.finding_id),
                synthetic=synthetic, call=_demo_no_synthesis_call,
            )
        for t in ties:
            explanation_service.explain(
                conn, ObservationKind.CONCERN_TIE, t, demo_case_id,
                _case_context_for(findings, ties, ObservationKind.CONCERN_TIE, t.tie_id),
                synthetic=synthetic, call=_demo_no_synthesis_call,
            )
    store.demo_meta_set(conn, "fixture_version", version)


def _load_case_or_404(conn: duckdb.DuckDBPyConnection, case_id: str) -> Case:
    if case_id in (demo.DEMO_CASE_ID, demo.DEMO_COI_CASE_ID):
        _ensure_demo_case_exists(conn)
    case = store.load_case(conn, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Unknown case_id: {case_id}")
    return case


def _action_dto(action) -> dict | None:
    if action is None:
        return None
    return {
        "action": action.action.value,
        "reason_code": action.reason_code,
        "reason_note": action.reason_note,
        "actor": action.actor,
        "recorded_at": action.recorded_at,
        "batch_id": action.batch_id,
    }


def _worksheet_payload(conn: duckdb.DuckDBPyConnection, case_id: str) -> dict:
    view = service.worksheet(conn, case_id)
    # Whose file is open. subject_id/display_name live on the Subject, not the
    # Case, so load it -- the same seam docs/2026-09-02-codebase-evaluation.md
    # flagged elsewhere: the data exists and used to stop before the payload.
    subject = store.load_subject(conn, view.case.subject_id)
    return {
        "case_id": case_id,
        "subject_id": view.case.subject_id,
        "subject_display_name": subject.display_name if subject else None,
        # Provenance-consistent with the export (case_export line ~111): a name
        # on a public URL beside a findings panel must carry the marker.
        "subject_synthetic": bool(
            view.case.synthetic and (subject.synthetic if subject else True)
        ),
        "state": view.case.state.value,
        "case_kind": view.case.case_kind.value,
        "coverage_basis": view.case.coverage_basis.value if view.case.coverage_basis else None,
        "statutory_deadline": (
            view.case.statutory_deadline.isoformat()
            if view.case.statutory_deadline
            else None
        ),
        "unactioned_count": view.unactioned_count,  # across both row types
        "can_close": view.can_close,
        "rows": [
            {
                "finding": case_export._finding_to_dict(row.finding),
                "action": _action_dto(row.action),
            }
            for row in view.rows
        ],
        "tie_rows": [
            {
                "tie": case_export._tie_to_dict(row.tie),
                "action": _action_dto(row.action),
            }
            for row in view.tie_rows
        ],
    }


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


@router.get("/reason-codes")
def reason_codes() -> dict:
    return {
        "dismiss": DISMISS_REASON_CODES,
        "escalation": ESCALATION_REASON_CODES,
        "tie_dismiss": TIE_DISMISS_REASON_CODES,
        "tie_escalation": TIE_ESCALATION_REASON_CODES,
        # COI (step 6) shares "dismiss" with HB-127; only escalation differs
        # (case/vocab.py: no Sec. 51B.153 certification path for a COI case).
        "coi_escalation": COI_ESCALATION_REASON_CODES,
        # M6: the worksheet UI's outcome-recording dropdown.
        "outcomes": sorted(service.VALID_OUTCOMES),
    }


@router.get("/dismissal-basis-summary")
def dismissal_basis_summary() -> dict:
    """Section 4.1's by-product: the office's own accumulated answer to 'how
    does your institution define substantial?', aggregated from real
    adjudications rather than a policy guessed at up front. Split by
    observation kind -- discrepancy dismissals and concern-tie dismissals
    turn on different things and are drawn from different vocabularies.

    M7: scoped to CLOSED, non-demo cases only -- "the office's accumulated
    case law," not a live scratch pad of whatever's mid-worksheet, and the
    public demo's own dismissals (anyone with the action secret can make
    one) must never count as real precedent. The join back to
    findings/concern_ties also means a dangling action -- one whose
    finding_id/tie_id a later reconcile removed (S5) -- is silently
    excluded rather than counted against an id that no longer exists."""
    conn = _connect()
    try:
        finding_rows = conn.execute(
            "SELECT wa.reason_code, count(*) FROM worksheet_actions wa "
            "JOIN findings f ON f.finding_id = wa.finding_id AND f.case_id = wa.case_id "
            "JOIN cases c ON c.case_id = wa.case_id "
            "WHERE wa.action = 'dismiss' AND c.state = 'closed' AND c.case_id NOT IN (?, ?) "
            "GROUP BY wa.reason_code ORDER BY count(*) DESC",
            [demo.DEMO_CASE_ID, demo.DEMO_COI_CASE_ID],
        ).fetchall()
        tie_rows = conn.execute(
            "SELECT ta.reason_code, count(*) FROM tie_actions ta "
            "JOIN concern_ties t ON t.tie_id = ta.tie_id AND t.case_id = ta.case_id "
            "JOIN cases c ON c.case_id = ta.case_id "
            "WHERE ta.action = 'dismiss' AND c.state = 'closed' AND c.case_id NOT IN (?, ?) "
            "GROUP BY ta.reason_code ORDER BY count(*) DESC",
            [demo.DEMO_CASE_ID, demo.DEMO_COI_CASE_ID],
        ).fetchall()
    finally:
        conn.close()
    return {
        "discrepancy": {
            "by_reason_code": [{"reason_code": rc, "count": n} for rc, n in finding_rows],
            "vocabulary": DISMISS_REASON_CODES,
        },
        "concern_tie": {
            "by_reason_code": [{"reason_code": rc, "count": n} for rc, n in tie_rows],
            "vocabulary": TIE_DISMISS_REASON_CODES,
        },
    }


@router.post("")
def create_case(
    request: CreateCaseRequest, _s: None = Depends(require_action_secret)
) -> dict:
    from datetime import date

    # M19: store.save_case (like save_subject/save_declaration) is a plain
    # DELETE-then-INSERT -- without this check, POSTing an existing
    # case_id silently overwrites it (and orphans its findings/actions/etc
    # against the replaced case) instead of failing loudly.
    if request.case_id in (demo.DEMO_CASE_ID, demo.DEMO_COI_CASE_ID):
        raise HTTPException(
            status_code=409, detail=f"Case id {request.case_id!r} is reserved."
        )
    conn = _connect()
    try:
        existing = store.load_case(conn, request.case_id)
    finally:
        conn.close()
    if existing is not None:
        raise HTTPException(
            status_code=409, detail=f"Case {request.case_id!r} already exists."
        )

    try:
        subject = Subject(
            subject_id=request.subject_id,
            display_name=request.subject_display_name,
            coverage_basis=(
                CoverageBasis(request.coverage_basis) if request.coverage_basis else None
            ),
            synthetic=request.synthetic,
            classified_fields=request.classified_fields,
        )
        declaration_id = f"{request.case_id}-declaration"
        declaration = Declaration(
            declaration_id=declaration_id,
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

    try:
        case_kind = CaseKind(request.case_kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    case = Case(
        case_id=request.case_id,
        subject_id=request.subject_id,
        declaration_id=declaration_id,
        trigger=request.trigger,
        access_scope=request.access_scope,
        coverage_basis=subject.coverage_basis,
        synthetic=request.synthetic,
        case_kind=case_kind,
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


_RECONCILE_ALLOWED_STATES = (
    CaseState.INTAKE,
    CaseState.DECLARATION_ASSEMBLY,
    CaseState.DISCOVERY,
)


@router.post("/{case_id}/reconcile")
def reconcile(
    case_id: str,
    request: ReconcileRequest,
    _s: None = Depends(require_action_secret),
) -> dict:
    conn = _connect()
    try:
        case = _load_case_or_404(conn, case_id)
        if case.state not in _RECONCILE_ALLOWED_STATES:
            # S5: re-running reconciliation regenerates a case's evidence,
            # which a worksheet in progress (or beyond) must not have wiped
            # out from under an analyst -- refused unless re-opened
            # (transition back to DISCOVERY) first.
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Case {case_id!r} is in {case.state.value!r} and cannot be "
                    "reconciled again without first re-opening it (POST "
                    ".../transition {\"target_state\": \"discovery\"})."
                ),
            )
    finally:
        conn.close()
    is_demo = case_id in (demo.DEMO_CASE_ID, demo.DEMO_COI_CASE_ID)
    manifest, findings, ties = pipeline.reconcile_case(
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
        "tie_count": len(ties),
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


def _explanation_dto(explanation: MatchExplanation) -> dict:
    return {
        "explanation_id": explanation.explanation_id,
        "observation_kind": explanation.observation_kind.value,
        "observation_id": explanation.observation_id,
        "case_id": explanation.case_id,
        "recitation": explanation.recitation,
        "synthesis_sentence": explanation.synthesis_sentence,
        "citations": [
            {"cited_text": c.cited_text, "start_char": c.start_char, "end_char": c.end_char}
            for c in explanation.citations
        ],
        "model": explanation.model,
        "prompt_version": explanation.prompt_version,
        "generated_at": explanation.generated_at,
        "synthetic": explanation.synthetic,
    }


def _find_primary_or_404(
    findings: list,
    ties: list,
    observation_kind: ObservationKind,
    observation_id: str,
    case_id: str,
) -> Any:
    """Shared by the generate (_explain) and cached-read
    (_cached_explanation_or_404) paths below, so both agree on what "the
    requested observation" means, including the 404 behaviour for an
    unknown id."""
    if observation_kind is ObservationKind.FINDING:
        primary = next((f for f in findings if f.finding_id == observation_id), None)
    else:
        primary = next((t for t in ties if t.tie_id == observation_id), None)
    if primary is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown {observation_kind.value} {observation_id!r} in case {case_id!r}",
        )
    return primary


def _case_context_for(
    findings: list, ties: list, observation_kind: ObservationKind, observation_id: str
) -> list:
    """Everything else in the case besides the primary observation -- the
    context the one allowed synthesis sentence may connect the primary to
    (explanation/generate.py). Shared by _explain (POST, generates),
    _cached_explanation_or_404 (GET, reads), and _ensure_demo_case_exists
    (build-time pre-generation) so all three build the *same* context for
    the same observation -- required since M17 folded case_context into
    evidence_hash_for's cache key: if any of the three built a different
    context, it would disagree on the hash for the same logical
    explanation, and the mismatch would surface as a silent, wrong cache
    hit/miss rather than an error."""
    if observation_kind is ObservationKind.FINDING:
        return [f for f in findings if f.finding_id != observation_id] + list(ties)
    return [t for t in ties if t.tie_id != observation_id] + list(findings)


def _explain(conn: duckdb.DuckDBPyConnection, case_id: str, observation_kind: ObservationKind, observation_id: str) -> dict:
    """Shared by the finding/tie explanation routes below: loads the case's
    full finding+tie set once, picks out the requested observation as the
    primary subject and everything else in the case as context for the one
    allowed synthesis sentence (explanation/generate.py), and gates the
    real, costed external call behind the same action secret every mutating
    route already uses -- unlike every other GET-shaped route in this file,
    this one is not free to call repeatedly."""
    case = _load_case_or_404(conn, case_id)
    findings = store.load_findings(conn, case_id)
    ties = store.load_ties(conn, case_id)
    primary = _find_primary_or_404(findings, ties, observation_kind, observation_id, case_id)
    context = _case_context_for(findings, ties, observation_kind, observation_id)

    subject = store.load_subject(conn, case.subject_id)
    synthetic = bool(case.synthetic and (subject.synthetic if subject else True))

    try:
        explanation = explanation_service.explain(
            conn, observation_kind, primary, case_id, context, synthetic=synthetic
        )
    except Exception as exc:  # the live Claude API is a real external dependency
        raise HTTPException(
            status_code=502,
            detail=(
                "Explanation generation failed (the Claude API call, or its "
                f"credentials, may be unavailable): {exc}"
            ),
        )
    return _explanation_dto(explanation)


def _cached_explanation_or_404(
    conn: duckdb.DuckDBPyConnection, case_id: str, observation_kind: ObservationKind, observation_id: str
) -> dict:
    """The ungated read half of B2: returns the same row `_explain` would
    consider cached (same (observation_id, evidence_hash) key via
    evidence_hash_for), or 404 -- and never calls explanation_service.explain,
    so it never triggers a live, costed generation. Anonymous visitors on the
    public demo can reach this even though the POST routes below are gated,
    since the demo's explanations are pre-generated at build time
    (_ensure_demo_case_exists)."""
    _load_case_or_404(conn, case_id)
    findings = store.load_findings(conn, case_id)
    ties = store.load_ties(conn, case_id)
    primary = _find_primary_or_404(findings, ties, observation_kind, observation_id, case_id)
    context = _case_context_for(findings, ties, observation_kind, observation_id)

    evidence_hash = explanation_service.evidence_hash_for(primary, context)
    cached = explanation_store.load_explanation(conn, observation_id, evidence_hash)
    if cached is None:
        raise HTTPException(
            status_code=404,
            detail=f"No cached explanation for {observation_kind.value} {observation_id!r} in case {case_id!r}",
        )
    return _explanation_dto(cached)


@router.get("/{case_id}/findings/{finding_id}/explanation")
def get_finding_explanation(case_id: str, finding_id: str) -> dict:
    conn = _connect()
    try:
        return _cached_explanation_or_404(conn, case_id, ObservationKind.FINDING, finding_id)
    finally:
        conn.close()


@router.get("/{case_id}/ties/{tie_id}/explanation")
def get_tie_explanation(case_id: str, tie_id: str) -> dict:
    conn = _connect()
    try:
        return _cached_explanation_or_404(conn, case_id, ObservationKind.CONCERN_TIE, tie_id)
    finally:
        conn.close()


@router.post("/{case_id}/findings/{finding_id}/explanation")
def post_finding_explanation(
    case_id: str, finding_id: str, _s: None = Depends(require_action_secret)
) -> dict:
    conn = _connect()
    try:
        return _explain(conn, case_id, ObservationKind.FINDING, finding_id)
    finally:
        conn.close()


@router.post("/{case_id}/ties/{tie_id}/explanation")
def post_tie_explanation(
    case_id: str, tie_id: str, _s: None = Depends(require_action_secret)
) -> dict:
    conn = _connect()
    try:
        return _explain(conn, case_id, ObservationKind.CONCERN_TIE, tie_id)
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


@router.post("/{case_id}/ties/{tie_id}/action")
def post_tie_action(
    case_id: str,
    tie_id: str,
    request: ActionRequest,
    _s: None = Depends(require_action_secret),
) -> dict:
    conn = _connect()
    try:
        _load_case_or_404(conn, case_id)
        try:
            service.record_tie_action(
                conn,
                case_id,
                tie_id,
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


@router.post("/{case_id}/ties/actions")
def post_bulk_tie_action(
    case_id: str,
    request: BulkTieActionRequest,
    _s: None = Depends(require_action_secret),
) -> dict:
    conn = _connect()
    try:
        _load_case_or_404(conn, case_id)
        try:
            batch_id, _ = service.record_bulk_tie_action(
                conn,
                case_id,
                request.tie_ids,
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
def get_investigative_file_json(
    case_id: str, redact: bool = True, x_monops_action_secret: str | None = Header(default=None)
) -> FileResponse:
    if not redact:
        require_action_secret(x_monops_action_secret)
    return _export(case_id, "json", redact)


@router.get("/{case_id}/investigative-file.xlsx")
def get_investigative_file_xlsx(
    case_id: str, redact: bool = True, x_monops_action_secret: str | None = Header(default=None)
) -> FileResponse:
    if not redact:
        require_action_secret(x_monops_action_secret)
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
