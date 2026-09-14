"""Orchestration for restricted-party screening (RPS) events -- Use Case 02,
step 5. Mirrors `case/service.py`'s role for the HB 127 case model: this is
where reason-code validation and the screen/persist/manifest sequence live,
kept out of `rps_screen.py` (pure matching) and `rps_store.py` (pure
persistence) the same way `case/service.py` is kept separate from
`reconciliation/discover.py` and `case/store.py`.

Only `OpenSanctionsList` is screened against here -- not DoD 1260H. DoD
1260H (Chinese military companies, Epic D) is a distinct concern list for a
different purpose; none of the seven restricted-party lists named in
docs/use-case-02-restricted-party-screening.md Section 1 are DoD 1260H, and
conflating the two would misrepresent which government list produced a
match.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

from entity_screening.case.vocab import is_valid_rps_reason_code
from entity_screening.common.manifest import DEFAULT_RUNS_DIR, ScreeningEventManifest
from entity_screening.common.schema import WorksheetActionKind
from entity_screening.ingestion.base import IngestionErrorLog
from entity_screening.ingestion.opensanctions import OpenSanctionsTargetsIngester
from entity_screening.screening import rps_store
from entity_screening.screening.lists import OpenSanctionsList
from entity_screening.screening.rps_schema import (
    ScreeningDisposition,
    ScreeningEvent,
    ScreeningParty,
)
from entity_screening.screening.rps_screen import screen_parties


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RPSError(RuntimeError):
    pass


def create_event(
    conn: duckdb.DuckDBPyConnection,
    event: ScreeningEvent,
    parties: list[ScreeningParty],
) -> ScreeningEvent:
    rps_store.save_event(conn, event)
    rps_store.save_parties(conn, event.event_id, parties)
    return event


def screen_event(
    conn: duckdb.DuckDBPyConnection,
    event_id: str,
    *,
    opensanctions_file: Path | str | None,
    runs_dir: Path | str = DEFAULT_RUNS_DIR,
) -> ScreeningEventManifest:
    """Screens every party in the event against OpenSanctions, replaces the
    event's match set, and writes a ScreeningEventManifest. `opensanctions_file`
    is optional -- with none supplied, screening runs with zero concern
    lists and produces zero matches (never an error; a screening pass that
    finds nothing real to screen against should say so structurally, not
    raise)."""
    event = rps_store.load_event(conn, event_id)
    if event is None:
        raise RPSError(f"Unknown event_id: {event_id!r}")
    parties = rps_store.load_parties(conn, event_id)

    concern_lists = []
    snapshot_date: str | None = None
    if opensanctions_file:
        error_log = IngestionErrorLog(
            Path(runs_dir) / "screening-events" / event_id / "ingestion_errors.jsonl"
        )
        ingester = OpenSanctionsTargetsIngester(error_log, csv_path=opensanctions_file)
        concern_lists.append(OpenSanctionsList(list(ingester.stream_records())))
        error_log.close()
        snapshot_date = (ingester.retrieval_date or date.today()).isoformat()

    matches_by_party = screen_parties(parties, concern_lists)
    all_matches = [m for matches in matches_by_party.values() for m in matches]
    rps_store.replace_matches(conn, [p.party_id for p in parties], all_matches)

    manifest = ScreeningEventManifest.create(
        event_id=event_id,
        opensanctions_snapshot_date=snapshot_date,
        party_count=len(parties),
        match_count=len(all_matches),
    )
    manifest.write(runs_dir)
    return manifest


def record_disposition(
    conn: duckdb.DuckDBPyConnection,
    event_id: str,
    match_id: str,
    action: WorksheetActionKind,
    reason_code: str,
    reason_note: str,
    actor: str,
) -> ScreeningDisposition:
    if not is_valid_rps_reason_code(action.value, reason_code):
        raise RPSError(
            f"reason_code {reason_code!r} is not in the RPS controlled vocabulary "
            f"for action {action.value!r} (see entity_screening/case/vocab.py)."
        )
    known = {m.match_id for m in rps_store.load_matches_for_event(conn, event_id)}
    if match_id not in known:
        raise RPSError(f"match_id {match_id!r} is not part of event {event_id!r}")
    disposition = ScreeningDisposition(
        match_id=match_id,
        action=action,
        reason_code=reason_code,
        reason_note=reason_note,
        actor=actor,
        recorded_at=_now(),
    )
    rps_store.append_disposition(conn, disposition)
    return disposition


def new_event_id() -> str:
    return str(uuid.uuid4())


def new_party_id() -> str:
    return str(uuid.uuid4())
