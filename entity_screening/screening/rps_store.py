"""DuckDB persistence for restricted-party screening (RPS) -- Use Case 02,
step 5. Tables are declared in common/storage.py's SCHEMA_DDL, the same
pattern case/store.py follows for the HB 127 case tables; this module is
only the row <-> dataclass marshalling.

Lifecycle per table, mirroring case/store.py's own documented conventions:
- screening_events / screening_parties: current-state, replaced on re-save.
- screening_matches: current-state per event -- replace_matches deletes
  every match belonging to the event's parties before inserting. Re-running
  screening for an event replaces its match set.
- screening_dispositions: append-only history; the latest row per
  match_id is the effective disposition.
"""
from __future__ import annotations

import json
from collections.abc import Iterable

import duckdb

from entity_screening.common.schema import MatchStatus, WorksheetActionKind
from entity_screening.screening.rps_schema import (
    PartyKind,
    ScreeningDisposition,
    ScreeningEvent,
    ScreeningMatch,
    ScreeningParty,
    ScreeningTrigger,
)

# --------------------------------------------------------------------------
# Screening events
# --------------------------------------------------------------------------


def save_event(conn: duckdb.DuckDBPyConnection, event: ScreeningEvent) -> None:
    conn.execute("DELETE FROM screening_events WHERE event_id = ?", [event.event_id])
    conn.execute(
        "INSERT INTO screening_events VALUES (?, ?, ?, ?, ?, ?)",
        [
            event.event_id,
            event.trigger.value,
            event.case_id,
            event.requested_by,
            event.requested_at,
            event.synthetic,
        ],
    )


def list_events(
    conn: duckdb.DuckDBPyConnection,
    trigger: ScreeningTrigger | None = None,
    limit: int = 50,
) -> list[ScreeningEvent]:
    """Reverse-chronological (most recently requested first) -- the browse
    view a UI needs to find an event without already knowing its event_id.
    `trigger` narrows to one trigger type when supplied; `limit` bounds a
    first-cut listing with no cursor paging yet."""
    if trigger is None:
        rows = conn.execute(
            "SELECT event_id, trigger, case_id, requested_by, requested_at, synthetic "
            "FROM screening_events ORDER BY requested_at DESC LIMIT ?",
            [limit],
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT event_id, trigger, case_id, requested_by, requested_at, synthetic "
            "FROM screening_events WHERE trigger = ? ORDER BY requested_at DESC LIMIT ?",
            [trigger.value, limit],
        ).fetchall()
    return [
        ScreeningEvent(
            event_id=event_id,
            trigger=ScreeningTrigger(trigger_value),
            case_id=case_id,
            requested_by=requested_by,
            requested_at=requested_at,
            synthetic=bool(synthetic),
        )
        for event_id, trigger_value, case_id, requested_by, requested_at, synthetic in rows
    ]


def load_event(conn: duckdb.DuckDBPyConnection, event_id: str) -> ScreeningEvent | None:
    row = conn.execute(
        "SELECT event_id, trigger, case_id, requested_by, requested_at, synthetic "
        "FROM screening_events WHERE event_id = ?",
        [event_id],
    ).fetchone()
    if row is None:
        return None
    event_id, trigger, case_id, requested_by, requested_at, synthetic = row
    return ScreeningEvent(
        event_id=event_id,
        trigger=ScreeningTrigger(trigger),
        case_id=case_id,
        requested_by=requested_by,
        requested_at=requested_at,
        synthetic=bool(synthetic),
    )


# --------------------------------------------------------------------------
# Screening parties
# --------------------------------------------------------------------------


def save_parties(
    conn: duckdb.DuckDBPyConnection, event_id: str, parties: Iterable[ScreeningParty]
) -> None:
    conn.execute("DELETE FROM screening_parties WHERE event_id = ?", [event_id])
    rows = [
        (p.party_id, p.event_id, p.kind.value, p.name, p.country, p.role_in_event)
        for p in parties
    ]
    if rows:
        conn.executemany("INSERT INTO screening_parties VALUES (?, ?, ?, ?, ?, ?)", rows)


def load_parties(conn: duckdb.DuckDBPyConnection, event_id: str) -> list[ScreeningParty]:
    rows = conn.execute(
        "SELECT party_id, event_id, kind, name, country, role_in_event "
        "FROM screening_parties WHERE event_id = ? ORDER BY party_id",
        [event_id],
    ).fetchall()
    return [
        ScreeningParty(
            party_id=party_id,
            event_id=event_id,
            kind=PartyKind(kind),
            name=name,
            country=country,
            role_in_event=role_in_event,
        )
        for party_id, event_id, kind, name, country, role_in_event in rows
    ]


# --------------------------------------------------------------------------
# Screening matches
# --------------------------------------------------------------------------


def replace_matches(
    conn: duckdb.DuckDBPyConnection,
    party_ids: Iterable[str],
    matches: Iterable[ScreeningMatch],
) -> None:
    """Current-state per event: deletes every match for the given
    party_ids (the event's own parties), then inserts. Re-screening an
    event replaces its match set."""
    party_ids = list(party_ids)
    if party_ids:
        placeholders = ", ".join("?" for _ in party_ids)
        conn.execute(
            f"DELETE FROM screening_matches WHERE party_id IN ({placeholders})",
            party_ids,
        )
    rows = [
        (
            m.match_id,
            m.party_id,
            m.matched_variant,
            m.matched_field,
            m.list_name,
            m.confidence,
            json.dumps(m.evidence, default=str),
            m.status.value,
        )
        for m in matches
    ]
    if rows:
        conn.executemany(
            "INSERT INTO screening_matches VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows
        )


def load_matches_for_event(
    conn: duckdb.DuckDBPyConnection, event_id: str
) -> list[ScreeningMatch]:
    rows = conn.execute(
        "SELECT m.match_id, m.party_id, m.matched_variant, m.matched_field, m.list_name, "
        "m.confidence, m.evidence, m.status FROM screening_matches m "
        "JOIN screening_parties p ON p.party_id = m.party_id "
        "WHERE p.event_id = ? ORDER BY m.match_id",
        [event_id],
    ).fetchall()
    return [
        ScreeningMatch(
            match_id=match_id,
            party_id=party_id,
            matched_variant=matched_variant,
            matched_field=matched_field,
            list_name=list_name,
            confidence=confidence,
            evidence=json.loads(evidence),
            status=MatchStatus(status),
        )
        for match_id, party_id, matched_variant, matched_field, list_name, confidence, evidence, status
        in rows
    ]


# --------------------------------------------------------------------------
# Screening dispositions (mirrors case/store.py's worksheet_actions/tie_actions)
# --------------------------------------------------------------------------


def append_disposition(
    conn: duckdb.DuckDBPyConnection, disposition: ScreeningDisposition
) -> None:
    conn.execute(
        "INSERT INTO screening_dispositions VALUES (?, ?, ?, ?, ?, ?)",
        [
            disposition.match_id,
            disposition.action.value,
            disposition.reason_code,
            disposition.reason_note,
            disposition.actor,
            disposition.recorded_at,
        ],
    )


def load_dispositions_for_event(
    conn: duckdb.DuckDBPyConnection, event_id: str
) -> list[ScreeningDisposition]:
    rows = conn.execute(
        "SELECT d.match_id, d.action, d.reason_code, d.reason_note, d.actor, d.recorded_at "
        "FROM screening_dispositions d "
        "JOIN screening_matches m ON m.match_id = d.match_id "
        "JOIN screening_parties p ON p.party_id = m.party_id "
        "WHERE p.event_id = ? ORDER BY d.recorded_at",
        [event_id],
    ).fetchall()
    return [
        ScreeningDisposition(
            match_id=match_id,
            action=WorksheetActionKind(action),
            reason_code=reason_code,
            reason_note=reason_note,
            actor=actor,
            recorded_at=recorded_at,
        )
        for match_id, action, reason_code, reason_note, actor, recorded_at in rows
    ]


def effective_dispositions(
    conn: duckdb.DuckDBPyConnection, event_id: str
) -> dict[str, ScreeningDisposition]:
    """The latest disposition per match_id -- the effective one."""
    effective: dict[str, ScreeningDisposition] = {}
    for disposition in load_dispositions_for_event(conn, event_id):
        effective[disposition.match_id] = disposition
    return effective
