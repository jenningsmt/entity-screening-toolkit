"""HTTP surface for restricted-party screening (RPS) -- Use Case 02, step 5.

Same posture as api/case_routes.py: mutating actions go through the shared
action-secret dependency; reads are open. One creation route per trigger's
real-world event (mirroring how TAMU's own process differs by trigger -- a
hire has a Form, a visiting scholar has Form 5VS, a purchase has neither)
rather than one generic endpoint, per
docs/plans/2026-09-14-restricted-party-screening.md Section 4.

A hire/visiting-scholar event's `case_id`, when supplied, is a display-only
join key to an existing HB 127 case -- never a shared worksheet row-type.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import duckdb
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from entity_screening.api.deps import allowed_data_files, check_allowlisted
from entity_screening.api.deps import db_path as _db_path
from entity_screening.api.deps import require_action_secret
from entity_screening.api.deps import runs_dir as _runs_dir
from entity_screening.case.vocab import RPS_DISMISS_REASON_CODES, RPS_ESCALATION_REASON_CODES
from entity_screening.common import storage
from entity_screening.common.schema import WorksheetActionKind
from entity_screening.screening import rps_service, rps_store
from entity_screening.screening.rps_schema import (
    PartyKind,
    ScreeningEvent,
    ScreeningParty,
    ScreeningTrigger,
)

router = APIRouter(prefix="/screening-events", tags=["restricted-party-screening"])


# --------------------------------------------------------------------------
# DTOs
# --------------------------------------------------------------------------


class PartyIn(BaseModel):
    kind: str  # "person" | "organization"
    name: str
    country: str | None = None
    role_in_event: str


class HireEventRequest(BaseModel):
    requested_by: str
    synthetic: bool = True
    case_id: str | None = None
    subject_name: str
    subject_country: str | None = None
    employer_name: str
    employer_country: str | None = None
    prior_affiliations: list[PartyIn] = []
    references: list[PartyIn] = []


class VisitingScholarEventRequest(BaseModel):
    requested_by: str
    synthetic: bool = True
    case_id: str | None = None
    visitor_name: str
    visitor_country: str | None = None
    institution_name: str
    institution_country: str | None = None


class PurchasingEventRequest(BaseModel):
    requested_by: str
    synthetic: bool = True
    counterparty_name: str
    counterparty_country: str | None = None
    counterparty_kind: str = "organization"  # "person" | "organization"


class ScreenRequest(BaseModel):
    opensanctions_file: str | None = None


class DispositionRequest(BaseModel):
    action: str
    reason_code: str
    reason_note: str
    actor: str


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _connect() -> duckdb.DuckDBPyConnection:
    return storage.connect(_db_path())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _party_from_in(event_id: str, p: PartyIn) -> ScreeningParty:
    return ScreeningParty(
        party_id=rps_service.new_party_id(),
        event_id=event_id,
        kind=PartyKind(p.kind),
        name=p.name,
        country=p.country,
        role_in_event=p.role_in_event,
    )


def _event_or_404(conn: duckdb.DuckDBPyConnection, event_id: str) -> ScreeningEvent:
    event = rps_store.load_event(conn, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"Unknown event_id: {event_id}")
    return event


def _match_dto(match) -> dict[str, Any]:
    return {
        "match_id": match.match_id,
        "party_id": match.party_id,
        "matched_variant": match.matched_variant,
        "list_name": match.list_name,
        "confidence": match.confidence,
        "evidence": match.evidence,
        "status": match.status.value,
    }


def _disposition_dto(disposition) -> dict[str, Any] | None:
    if disposition is None:
        return None
    return {
        "action": disposition.action.value,
        "reason_code": disposition.reason_code,
        "reason_note": disposition.reason_note,
        "actor": disposition.actor,
        "recorded_at": disposition.recorded_at,
    }


def _event_payload(conn: duckdb.DuckDBPyConnection, event_id: str) -> dict[str, Any]:
    event = _event_or_404(conn, event_id)
    parties = rps_store.load_parties(conn, event_id)
    matches = rps_store.load_matches_for_event(conn, event_id)
    effective = rps_store.effective_dispositions(conn, event_id)
    return {
        "event_id": event.event_id,
        "trigger": event.trigger.value,
        "case_id": event.case_id,
        "requested_by": event.requested_by,
        "requested_at": event.requested_at,
        "parties": [
            {
                "party_id": p.party_id,
                "kind": p.kind.value,
                "name": p.name,
                "country": p.country,
                "role_in_event": p.role_in_event,
            }
            for p in parties
        ],
        "matches": [
            {
                **_match_dto(m),
                "disposition": _disposition_dto(effective.get(m.match_id)),
            }
            for m in matches
        ],
    }


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


@router.get("/reason-codes")
def get_reason_codes() -> dict:
    return {"dismiss": RPS_DISMISS_REASON_CODES, "escalate": RPS_ESCALATION_REASON_CODES}


@router.get("")
def list_events(trigger: str | None = None, limit: int = 50) -> dict:
    """Summary fields only (no parties/matches -- GET /{event_id} is the
    detail call) so a browse view can find an event without already knowing
    its event_id. Open, not gated, like every other read in this API."""
    conn = _connect()
    try:
        events = rps_store.list_events(
            conn, trigger=ScreeningTrigger(trigger) if trigger else None, limit=limit
        )
    finally:
        conn.close()
    return {
        "events": [
            {
                "event_id": e.event_id,
                "trigger": e.trigger.value,
                "case_id": e.case_id,
                "requested_by": e.requested_by,
                "requested_at": e.requested_at,
            }
            for e in events
        ]
    }


@router.post("/hire")
def create_hire_event(
    request: HireEventRequest, _s: None = Depends(require_action_secret)
) -> dict:
    event_id = rps_service.new_event_id()
    event = ScreeningEvent(
        event_id=event_id,
        trigger=ScreeningTrigger.FOREIGN_PERSON_HIRE,
        case_id=request.case_id,
        requested_by=request.requested_by,
        requested_at=_now(),
        synthetic=request.synthetic,
    )
    parties = [
        ScreeningParty(
            party_id=rps_service.new_party_id(), event_id=event_id, kind=PartyKind.PERSON,
            name=request.subject_name, country=request.subject_country, role_in_event="subject",
        ),
        ScreeningParty(
            party_id=rps_service.new_party_id(), event_id=event_id, kind=PartyKind.ORGANIZATION,
            name=request.employer_name, country=request.employer_country, role_in_event="current_employer",
        ),
    ]
    parties += [_party_from_in(event_id, p) for p in request.prior_affiliations]
    parties += [_party_from_in(event_id, p) for p in request.references]
    conn = _connect()
    try:
        rps_service.create_event(conn, event, parties)
    finally:
        conn.close()
    return {"event_id": event_id}


@router.post("/visiting-scholar")
def create_visiting_scholar_event(
    request: VisitingScholarEventRequest, _s: None = Depends(require_action_secret)
) -> dict:
    event_id = rps_service.new_event_id()
    event = ScreeningEvent(
        event_id=event_id,
        trigger=ScreeningTrigger.VISITING_SCHOLAR,
        case_id=request.case_id,
        requested_by=request.requested_by,
        requested_at=_now(),
        synthetic=request.synthetic,
    )
    parties = [
        ScreeningParty(
            party_id=rps_service.new_party_id(), event_id=event_id, kind=PartyKind.PERSON,
            name=request.visitor_name, country=request.visitor_country, role_in_event="subject",
        ),
        ScreeningParty(
            party_id=rps_service.new_party_id(), event_id=event_id, kind=PartyKind.ORGANIZATION,
            name=request.institution_name, country=request.institution_country,
            role_in_event="current_employer",
        ),
    ]
    conn = _connect()
    try:
        rps_service.create_event(conn, event, parties)
    finally:
        conn.close()
    return {"event_id": event_id}


@router.post("/purchasing")
def create_purchasing_event(
    request: PurchasingEventRequest, _s: None = Depends(require_action_secret)
) -> dict:
    event_id = rps_service.new_event_id()
    event = ScreeningEvent(
        event_id=event_id,
        trigger=ScreeningTrigger.PURCHASING_FINANCIAL,
        case_id=None,  # purchasing never links to an HB127 case -- see module docstring
        requested_by=request.requested_by,
        requested_at=_now(),
        synthetic=request.synthetic,
    )
    parties = [
        ScreeningParty(
            party_id=rps_service.new_party_id(), event_id=event_id,
            kind=PartyKind(request.counterparty_kind),
            name=request.counterparty_name, country=request.counterparty_country,
            role_in_event="counterparty",
        ),
    ]
    conn = _connect()
    try:
        rps_service.create_event(conn, event, parties)
    finally:
        conn.close()
    return {"event_id": event_id}


@router.post("/{event_id}/screen")
def screen_event(
    event_id: str, request: ScreenRequest, _s: None = Depends(require_action_secret)
) -> dict:
    check_allowlisted(request.opensanctions_file, allowed_data_files())
    conn = _connect()
    try:
        _event_or_404(conn, event_id)
        manifest = rps_service.screen_event(
            conn, event_id, opensanctions_file=request.opensanctions_file, runs_dir=_runs_dir()
        )
        return _event_payload(conn, event_id) | {"party_count": manifest.party_count, "match_count": manifest.match_count}
    except rps_service.RPSError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        conn.close()


@router.get("/{event_id}")
def get_event(event_id: str) -> dict:
    conn = _connect()
    try:
        return _event_payload(conn, event_id)
    finally:
        conn.close()


@router.post("/{event_id}/matches/{match_id}/disposition")
def post_disposition(
    event_id: str,
    match_id: str,
    request: DispositionRequest,
    _s: None = Depends(require_action_secret),
) -> dict:
    conn = _connect()
    try:
        _event_or_404(conn, event_id)
        try:
            rps_service.record_disposition(
                conn, event_id, match_id, WorksheetActionKind(request.action),
                request.reason_code, request.reason_note, request.actor,
            )
        except rps_service.RPSError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return _event_payload(conn, event_id)
    finally:
        conn.close()
