"""Case worksheet, adjudication, and lifecycle operations.

The worksheet is the analyst's working surface: one row per finding, and a
case cannot leave the WORKSHEET state while any row is unactioned (use-case-01
Section 8's closure rule). Bulk action -- one disposition, one reason, across
a selected class of findings -- is a requirement, not a convenience: without
it the volume defeats the worksheet.

Adjudication is append-only. Re-opening a closed case appends a new
Adjudication (seq + 1); the earlier one stays intact and readable because it
was correct given what was known then.

`actor` is a plain string throughout. This build has no login (the API's only
gate is the shared action secret); the actor identifier is supplied by the
caller. For a portfolio demo on synthetic data that is the right scope, but
it is a real limitation, not an oversight -- a production deployment would
need real authentication behind it.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import duckdb

from entity_screening.case import store
from entity_screening.case.vocab import is_valid_reason_code, is_valid_tie_reason_code
from entity_screening.common.schema import (
    Adjudication,
    Case,
    CaseState,
    Certification,
    ConcernTie,
    Finding,
    TieAction,
    WorksheetAction,
    WorksheetActionKind,
)

# Allowed forward transitions. CLOSED -> DISCOVERY is the re-open path.
_TRANSITIONS: dict[CaseState, set[CaseState]] = {
    CaseState.INTAKE: {CaseState.DECLARATION_ASSEMBLY},
    CaseState.DECLARATION_ASSEMBLY: {CaseState.DISCOVERY},
    CaseState.DISCOVERY: {CaseState.WORKSHEET},
    CaseState.WORKSHEET: {CaseState.ADJUDICATION},
    CaseState.ADJUDICATION: {CaseState.OUTCOME, CaseState.WORKSHEET},
    CaseState.OUTCOME: {CaseState.CLOSED},
    CaseState.CLOSED: {CaseState.DISCOVERY},
}

_VALID_OUTCOMES = {
    "cleared",
    "cleared_with_certification",
    "not_cleared",
    "withdrawn",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CaseStateError(RuntimeError):
    """A requested lifecycle transition is not allowed from the current state."""


@dataclass(frozen=True)
class WorksheetRow:
    finding: Finding
    action: WorksheetAction | None  # the effective (latest) action, or None


@dataclass(frozen=True)
class TieRow:
    tie: ConcernTie
    action: TieAction | None


@dataclass(frozen=True)
class WorksheetView:
    case: Case
    rows: tuple[WorksheetRow, ...]  # discrepancy (Finding) rows
    tie_rows: tuple[TieRow, ...]  # concern-tie rows
    unactioned_count: int  # across BOTH row types
    can_close: bool


def worksheet(conn: duckdb.DuckDBPyConnection, case_id: str) -> WorksheetView:
    case = store.load_case(conn, case_id)
    if case is None:
        raise ValueError(f"Unknown case_id: {case_id!r}")
    findings = store.load_findings(conn, case_id)
    effective = store.effective_actions(conn, case_id)
    rows = tuple(
        WorksheetRow(finding=f, action=effective.get(f.finding_id)) for f in findings
    )
    ties = store.load_ties(conn, case_id)
    tie_effective = store.effective_tie_actions(conn, case_id)
    tie_rows = tuple(
        TieRow(tie=t, action=tie_effective.get(t.tie_id)) for t in ties
    )
    unactioned = sum(1 for r in rows if r.action is None) + sum(
        1 for r in tie_rows if r.action is None
    )
    total = len(rows) + len(tie_rows)
    return WorksheetView(
        case=case,
        rows=rows,
        tie_rows=tie_rows,
        unactioned_count=unactioned,
        # A case cannot leave the worksheet while any row of EITHER type is
        # unactioned (use-case-01 Section 8, extended for concern ties).
        can_close=(unactioned == 0 and total > 0),
    )


def record_action(
    conn: duckdb.DuckDBPyConnection,
    case_id: str,
    finding_id: str,
    action: WorksheetActionKind,
    reason_code: str,
    reason_note: str,
    actor: str,
    batch_id: str | None = None,
) -> WorksheetAction:
    if not is_valid_reason_code(action.value, reason_code):
        raise ValueError(
            f"reason_code {reason_code!r} is not in the controlled vocabulary for "
            f"action {action.value!r} (see entity_screening/case/vocab.py)."
        )
    known = {f.finding_id for f in store.load_findings(conn, case_id)}
    if finding_id not in known:
        raise ValueError(f"finding_id {finding_id!r} is not in case {case_id!r}")
    wa = WorksheetAction(
        finding_id=finding_id,
        action=action,
        reason_code=reason_code,
        reason_note=reason_note,
        actor=actor,
        recorded_at=_now(),
        batch_id=batch_id,
    )
    store.append_worksheet_action(conn, case_id, wa)
    return wa


def record_bulk_action(
    conn: duckdb.DuckDBPyConnection,
    case_id: str,
    finding_ids: list[str],
    action: WorksheetActionKind,
    reason_code: str,
    reason_note: str,
    actor: str,
) -> tuple[str, list[WorksheetAction]]:
    """One disposition across a selected class of findings. Every action
    shares a `batch_id` so a bulk dismissal is auditable as one act by one
    person on one stated basis (use-case-01 Section 8)."""
    batch_id = str(uuid.uuid4())
    actions = [
        record_action(
            conn, case_id, fid, action, reason_code, reason_note, actor, batch_id=batch_id
        )
        for fid in finding_ids
    ]
    return batch_id, actions


def record_tie_action(
    conn: duckdb.DuckDBPyConnection,
    case_id: str,
    tie_id: str,
    action: WorksheetActionKind,
    reason_code: str,
    reason_note: str,
    actor: str,
    batch_id: str | None = None,
) -> TieAction:
    """One analyst disposition of one ConcernTie -- own reason vocabulary
    (case/vocab.py:TIE_DISMISS_REASON_CODES)."""
    if not is_valid_tie_reason_code(action.value, reason_code):
        raise ValueError(
            f"reason_code {reason_code!r} is not in the concern-tie vocabulary for "
            f"action {action.value!r} (see entity_screening/case/vocab.py)."
        )
    known = {t.tie_id for t in store.load_ties(conn, case_id)}
    if tie_id not in known:
        raise ValueError(f"tie_id {tie_id!r} is not in case {case_id!r}")
    ta = TieAction(
        tie_id=tie_id,
        action=action,
        reason_code=reason_code,
        reason_note=reason_note,
        actor=actor,
        recorded_at=_now(),
        batch_id=batch_id,
    )
    store.append_tie_action(conn, case_id, ta)
    return ta


def record_bulk_tie_action(
    conn: duckdb.DuckDBPyConnection,
    case_id: str,
    tie_ids: list[str],
    action: WorksheetActionKind,
    reason_code: str,
    reason_note: str,
    actor: str,
) -> tuple[str, list[TieAction]]:
    """Bulk tie disposition -- a convenience, not a requirement (concern-tie
    rows are few; the volume problem is on the discrepancy side)."""
    batch_id = str(uuid.uuid4())
    actions = [
        record_tie_action(
            conn, case_id, tid, action, reason_code, reason_note, actor, batch_id=batch_id
        )
        for tid in tie_ids
    ]
    return batch_id, actions


def transition(
    conn: duckdb.DuckDBPyConnection, case_id: str, target: CaseState
) -> Case:
    case = store.load_case(conn, case_id)
    if case is None:
        raise ValueError(f"Unknown case_id: {case_id!r}")
    allowed = _TRANSITIONS.get(case.state, set())
    if target not in allowed:
        raise CaseStateError(
            f"Case {case_id!r} cannot move from {case.state.value} to {target.value}. "
            f"Allowed: {sorted(s.value for s in allowed)}."
        )
    if case.state == CaseState.WORKSHEET and target == CaseState.ADJUDICATION:
        view = worksheet(conn, case_id)
        if not view.can_close:
            raise CaseStateError(
                f"Case {case_id!r} has {view.unactioned_count} unactioned worksheet "
                "row(s). Every discrepancy AND every concern tie must have an analyst "
                "action before the case leaves the worksheet (use-case-01 Section 8's "
                "closure rule)."
            )
    from dataclasses import replace

    updated = replace(case, state=target)
    store.save_case(conn, updated)
    return updated


def record_adjudication(
    conn: duckdb.DuckDBPyConnection,
    case_id: str,
    assessment: str,
    recommendation: str,
    actor: str,
) -> Adjudication:
    """Append-only. The case must be in ADJUDICATION state (reached only once
    the worksheet is complete). A re-opened case appends seq + 1."""
    case = store.load_case(conn, case_id)
    if case is None:
        raise ValueError(f"Unknown case_id: {case_id!r}")
    if case.state != CaseState.ADJUDICATION:
        raise CaseStateError(
            f"Case {case_id!r} is in {case.state.value}, not adjudication."
        )
    adj = Adjudication(
        case_id=case_id,
        seq=store.next_adjudication_seq(conn, case_id),
        assessment=assessment,
        recommendation=recommendation,
        actor=actor,
        recorded_at=_now(),
    )
    store.append_adjudication(conn, adj)
    return adj


def record_certification(
    conn: duckdb.DuckDBPyConnection,
    case_id: str,
    finding_id: str,
    substance_of_failure: str,
    reasons_for_disregarding: str,
    department_head: str,
) -> Certification:
    """The Sec. 51B.153 department-head written certification that a
    non-disclosure may be disregarded. A copy belongs in the investigative
    file, so this is appended to the case and included in the export."""
    known = {f.finding_id for f in store.load_findings(conn, case_id)}
    if finding_id not in known:
        raise ValueError(f"finding_id {finding_id!r} is not in case {case_id!r}")
    cert = Certification(
        case_id=case_id,
        finding_id=finding_id,
        substance_of_failure=substance_of_failure,
        reasons_for_disregarding=reasons_for_disregarding,
        department_head=department_head,
        recorded_at=_now(),
    )
    store.append_certification(conn, cert)
    return cert


def record_outcome(
    conn: duckdb.DuckDBPyConnection,
    case_id: str,
    outcome: str,
    actor: str,
    note: str = "",
) -> None:
    if outcome not in _VALID_OUTCOMES:
        raise ValueError(
            f"outcome {outcome!r} not one of {sorted(_VALID_OUTCOMES)}"
        )
    case = store.load_case(conn, case_id)
    if case is None or case.state != CaseState.OUTCOME:
        raise CaseStateError(
            f"Case {case_id!r} must be in the outcome state to record an outcome."
        )
    conn.execute(
        "INSERT INTO case_outcomes VALUES (?, ?, ?, ?, ?)",
        [case_id, outcome, note, actor, _now()],
    )


def latest_outcome(conn: duckdb.DuckDBPyConnection, case_id: str) -> dict | None:
    row = conn.execute(
        "SELECT outcome, note, actor, recorded_at FROM case_outcomes "
        "WHERE case_id = ? ORDER BY recorded_at DESC LIMIT 1",
        [case_id],
    ).fetchone()
    if row is None:
        return None
    outcome, note, actor, recorded_at = row
    return {"outcome": outcome, "note": note, "actor": actor, "recorded_at": recorded_at}


def reopen_case(conn: duckdb.DuckDBPyConnection, case_id: str) -> Case:
    """A closed case re-opens on new information. Returns it to DISCOVERY so
    reconciliation runs again against current reference data; the prior
    adjudication and any exported investigative file are untouched."""
    return transition(conn, case_id, CaseState.DISCOVERY)
