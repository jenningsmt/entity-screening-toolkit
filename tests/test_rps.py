"""Restricted-party screening (RPS) -- Use Case 02, step 5.

`tests/fixtures/sample_us_trade_csl.csv` is real, not fabricated: one row
extracted verbatim from OpenSanctions' real `us_trade_csl` dataset
(data.opensanctions.org/datasets/latest/us_trade_csl/targets.simple.csv,
downloaded 2026-09-14 during this feature's planning), the U.S.
government's own Consolidated Screening List -- "Taiyuan Jinke
Semiconductor Technology Co., Ltd.", program_ids=US-BIS-EL (the real BIS
Entity List), confirmed present in OpenSanctions' data as of that date.
Used here as the binding real-data verification
(docs/plans/2026-09-14-restricted-party-screening.md) that RPS produces a
match carrying the real government program id, not just a generic
"opensanctions" tag.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from entity_screening.common import storage
from entity_screening.common.schema import WorksheetActionKind
from entity_screening.ingestion.base import IngestionErrorLog
from entity_screening.ingestion.opensanctions import OpenSanctionsTargetsIngester
from entity_screening.screening import rps_service, rps_store
from entity_screening.screening.lists import OpenSanctionsList
from entity_screening.screening.rps_schema import PartyKind, ScreeningEvent, ScreeningParty, ScreeningTrigger
from entity_screening.screening.rps_screen import screen_parties

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_CSL_FILE = FIXTURES_DIR / "sample_us_trade_csl.csv"
DEMO_OPENSANCTIONS_FILE = FIXTURES_DIR / "demo_opensanctions_targets.csv"


def _csl_concern_list(tmp_path) -> OpenSanctionsList:
    error_log = IngestionErrorLog(tmp_path / "errors.jsonl")
    ingester = OpenSanctionsTargetsIngester(error_log, csv_path=SAMPLE_CSL_FILE)
    lst = OpenSanctionsList(list(ingester.stream_records()))
    error_log.close()
    return lst


# --------------------------------------------------------------------------
# Pure matching (screening/rps_screen.py)
# --------------------------------------------------------------------------


def test_screen_party_matches_the_real_bis_entity_list_row(tmp_path):
    concern_list = _csl_concern_list(tmp_path)
    party = ScreeningParty(
        party_id="p1", event_id="e1", kind=PartyKind.ORGANIZATION,
        name="Taiyuan Jinke Semiconductor Technology Co., Ltd.",
        country="cn", role_in_event="counterparty",
    )
    matches = screen_parties([party], [concern_list])["p1"]
    assert len(matches) == 1
    (match,) = matches
    assert match.confidence == 1.0
    # The real government program id, not a generic "opensanctions" tag --
    # carried through evidence["matched_entry_fields"]["program_ids"].
    assert match.evidence["matched_entry_fields"]["program_ids"] == "US-BIS-EL"
    assert match.list_name == "opensanctions_consolidated"


def test_screen_party_no_match_returns_empty(tmp_path):
    concern_list = _csl_concern_list(tmp_path)
    party = ScreeningParty(
        party_id="p2", event_id="e1", kind=PartyKind.PERSON,
        name="A Totally Unrelated Name Zzqx", country="us", role_in_event="subject",
    )
    assert screen_parties([party], [concern_list])["p2"] == []


def test_country_is_never_a_screening_gate(tmp_path):
    """Negative-space test for the OFAC-embargoed-country scope boundary
    (docs/plans/2026-09-14-restricted-party-screening.md): a party whose
    country is a real OFAC-embargoed country but whose name matches
    nothing produces zero matches -- proving no country-level filtering
    occurs, not just documenting it."""
    concern_list = _csl_concern_list(tmp_path)
    for embargoed_country in ("cu", "ir", "kp", "sy", "ve"):  # Cuba, Iran, NK, Syria, Venezuela
        party = ScreeningParty(
            party_id="p3", event_id="e1", kind=PartyKind.PERSON,
            name="Some Unrelated Synthetic Name", country=embargoed_country,
            role_in_event="subject",
        )
        assert screen_parties([party], [concern_list])["p3"] == []


# --------------------------------------------------------------------------
# Storage + service round-trip
# --------------------------------------------------------------------------


def test_create_screen_and_disposition_round_trip(tmp_path):
    conn = storage.connect(tmp_path / "test.duckdb")
    event = ScreeningEvent(
        event_id="evt-1", trigger=ScreeningTrigger.PURCHASING_FINANCIAL, case_id=None,
        requested_by="analyst.a", requested_at="2026-09-14T00:00:00+00:00", synthetic=True,
    )
    party = ScreeningParty(
        party_id="party-1", event_id="evt-1", kind=PartyKind.ORGANIZATION,
        name="Taiyuan Jinke Semiconductor Technology Co., Ltd.", country="cn",
        role_in_event="counterparty",
    )
    rps_service.create_event(conn, event, [party])

    manifest = rps_service.screen_event(
        conn, "evt-1", opensanctions_file=SAMPLE_CSL_FILE, runs_dir=tmp_path / "runs"
    )
    assert manifest.party_count == 1
    assert manifest.match_count == 1
    assert manifest.opensanctions_snapshot_date is not None

    matches = rps_store.load_matches_for_event(conn, "evt-1")
    assert len(matches) == 1
    (match,) = matches

    disposition = rps_service.record_disposition(
        conn, "evt-1", match.match_id, WorksheetActionKind.ESCALATE,
        "needs_resec_determination", "Real BIS Entity List match, routing to RESEC.",
        "analyst.a",
    )
    assert disposition.reason_code == "needs_resec_determination"

    effective = rps_store.effective_dispositions(conn, "evt-1")
    assert effective[match.match_id].action == WorksheetActionKind.ESCALATE
    conn.close()


def test_purchasing_event_has_no_case_id_and_one_party(tmp_path):
    """Confirms the two-level type accommodates the non-case-shaped trigger
    without distortion (docs/plans/2026-09-14-restricted-party-screening.md
    Section 1 / the binding decision to build purchasing on day one)."""
    conn = storage.connect(tmp_path / "test.duckdb")
    event = ScreeningEvent(
        event_id="evt-purchase", trigger=ScreeningTrigger.PURCHASING_FINANCIAL,
        case_id=None, requested_by="procurement.a", requested_at="2026-09-14T00:00:00+00:00",
        synthetic=True,
    )
    party = ScreeningParty(
        party_id="party-vendor", event_id="evt-purchase", kind=PartyKind.ORGANIZATION,
        name="Some Vendor LLC", country="us", role_in_event="counterparty",
    )
    rps_service.create_event(conn, event, [party])
    loaded = rps_store.load_event(conn, "evt-purchase")
    assert loaded.case_id is None
    assert len(rps_store.load_parties(conn, "evt-purchase")) == 1
    conn.close()


def test_hire_event_produces_multiple_parties(tmp_path):
    """A hire screens the person AND their employer (TAMU's real documented
    practice) -- confirms the multi-party shape, not a single-row hire."""
    conn = storage.connect(tmp_path / "test.duckdb")
    event = ScreeningEvent(
        event_id="evt-hire", trigger=ScreeningTrigger.FOREIGN_PERSON_HIRE,
        case_id="hb127-case-1", requested_by="hr.a", requested_at="2026-09-14T00:00:00+00:00",
        synthetic=True,
    )
    parties = [
        ScreeningParty(party_id="p-subject", event_id="evt-hire", kind=PartyKind.PERSON,
                        name="Wei Chen", country="cn", role_in_event="subject"),
        ScreeningParty(party_id="p-employer", event_id="evt-hire", kind=PartyKind.ORGANIZATION,
                        name="Prior Employer Ltd", country="cn", role_in_event="current_employer"),
    ]
    rps_service.create_event(conn, event, parties)
    loaded_parties = rps_store.load_parties(conn, "evt-hire")
    assert {p.role_in_event for p in loaded_parties} == {"subject", "current_employer"}
    loaded_event = rps_store.load_event(conn, "evt-hire")
    assert loaded_event.case_id == "hb127-case-1"  # display-only join key, still round-trips
    conn.close()


def test_screening_event_rejects_non_synthetic():
    import pytest as _pytest

    with _pytest.raises(ValueError):
        ScreeningEvent(
            event_id="x", trigger=ScreeningTrigger.PURCHASING_FINANCIAL, case_id=None,
            requested_by="x", requested_at="x", synthetic=False,
        )


# --------------------------------------------------------------------------
# API (mirrors tests/test_api_ownership.py's TestClient pattern)
# --------------------------------------------------------------------------


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("ENTITY_SCREENING_DB_PATH", str(tmp_path / "test.duckdb"))
    monkeypatch.setenv("ENTITY_SCREENING_RUNS_DIR", str(tmp_path / "runs"))
    from entity_screening.api.main import app

    return TestClient(app)


def test_api_hire_event_end_to_end(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/screening-events/hire",
        json={
            "requested_by": "hr.a",
            "subject_name": "Wei Chen",
            "subject_country": "cn",
            "employer_name": "Taiyuan Jinke Semiconductor Technology Co., Ltd.",
            "employer_country": "cn",
        },
    )
    assert response.status_code == 200, response.text
    event_id = response.json()["event_id"]

    screen_response = client.post(
        f"/screening-events/{event_id}/screen",
        json={"opensanctions_file": str(SAMPLE_CSL_FILE)},
    )
    assert screen_response.status_code == 200, screen_response.text
    payload = screen_response.json()
    assert payload["match_count"] == 1
    matches = payload["matches"]
    assert len(matches) == 1
    assert matches[0]["list_name"] == "opensanctions_consolidated"
    assert matches[0]["disposition"] is None

    disposition_response = client.post(
        f"/screening-events/{event_id}/matches/{matches[0]['match_id']}/disposition",
        json={
            "action": "escalate",
            "reason_code": "needs_resec_determination",
            "reason_note": "Real BIS Entity List match.",
            "actor": "hr.a",
        },
    )
    assert disposition_response.status_code == 200, disposition_response.text
    final = disposition_response.json()
    assert final["matches"][0]["disposition"]["action"] == "escalate"


def test_api_purchasing_event_has_no_case_id(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    response = client.post(
        "/screening-events/purchasing",
        json={"requested_by": "procurement.a", "counterparty_name": "Some Vendor LLC"},
    )
    assert response.status_code == 200, response.text
    event_id = response.json()["event_id"]
    get_response = client.get(f"/screening-events/{event_id}")
    assert get_response.status_code == 200
    assert get_response.json()["case_id"] is None
    assert len(get_response.json()["parties"]) == 1


def test_api_visiting_scholar_event_screens_against_real_demo_data(tmp_path, monkeypatch):
    """Uses the full demo OpenSanctions fixture (which already carries 22
    real CSL-sourced rows including a US-BIS-EL entry, confirmed during this
    feature's binding verification -- no fixture change was needed)."""
    client = _client(tmp_path, monkeypatch)
    response = client.post(
        "/screening-events/visiting-scholar",
        json={
            "requested_by": "host.a",
            "visitor_name": "Some Visiting Scholar",
            "visitor_country": "cn",
            "institution_name": "Shenzhen Huada Jiutianke Technology Co., Ltd.",
            "institution_country": "cn",
        },
    )
    event_id = response.json()["event_id"]
    screen_response = client.post(
        f"/screening-events/{event_id}/screen",
        json={"opensanctions_file": str(DEMO_OPENSANCTIONS_FILE)},
    )
    assert screen_response.status_code == 200, screen_response.text
    assert screen_response.json()["match_count"] >= 1


def test_api_reason_codes_endpoint():
    from entity_screening.api.main import app

    client = TestClient(app)
    response = client.get("/screening-events/reason-codes")
    assert response.status_code == 200
    assert "needs_resec_determination" in response.json()["escalate"]


# --------------------------------------------------------------------------
# Listing (rps_store.list_events / GET /screening-events) -- the browse-view
# gap surfaced while designing the Streamlit page, closed before the page
# was built against it.
# --------------------------------------------------------------------------


def test_list_events_is_reverse_chronological_and_filters_by_trigger(tmp_path):
    conn = storage.connect(tmp_path / "test.duckdb")
    for i, (trigger, ts) in enumerate([
        (ScreeningTrigger.FOREIGN_PERSON_HIRE, "2026-09-14T10:00:00+00:00"),
        (ScreeningTrigger.PURCHASING_FINANCIAL, "2026-09-14T11:00:00+00:00"),
        (ScreeningTrigger.VISITING_SCHOLAR, "2026-09-14T12:00:00+00:00"),
    ]):
        event = ScreeningEvent(
            event_id=f"evt-{i}", trigger=trigger, case_id=None,
            requested_by="analyst.a", requested_at=ts, synthetic=True,
        )
        rps_store.save_event(conn, event)

    all_events = rps_store.list_events(conn)
    assert [e.event_id for e in all_events] == ["evt-2", "evt-1", "evt-0"]  # most recent first

    hires = rps_store.list_events(conn, trigger=ScreeningTrigger.FOREIGN_PERSON_HIRE)
    assert [e.event_id for e in hires] == ["evt-0"]
    conn.close()


def test_list_events_respects_limit(tmp_path):
    conn = storage.connect(tmp_path / "test.duckdb")
    for i in range(3):
        rps_store.save_event(conn, ScreeningEvent(
            event_id=f"evt-{i}", trigger=ScreeningTrigger.PURCHASING_FINANCIAL, case_id=None,
            requested_by="a", requested_at=f"2026-09-14T1{i}:00:00+00:00", synthetic=True,
        ))
    assert len(rps_store.list_events(conn, limit=2)) == 2
    conn.close()


def test_api_list_events_endpoint(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    for _ in range(2):
        client.post("/screening-events/purchasing", json={
            "requested_by": "procurement.a", "counterparty_name": "Some Vendor LLC",
        })
    response = client.get("/screening-events")
    assert response.status_code == 200
    events = response.json()["events"]
    assert len(events) == 2
    assert set(events[0]) == {"event_id", "trigger", "case_id", "requested_by", "requested_at"}

    filtered = client.get("/screening-events", params={"trigger": "foreign_person_hire"})
    assert filtered.json()["events"] == []


# --------------------------------------------------------------------------
# Allowlist protection on the screen endpoint (the security gap found while
# building the Streamlit page -- fixed before the page could exercise it).
# --------------------------------------------------------------------------


def test_screen_endpoint_rejects_a_path_outside_the_allowlist(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    create = client.post("/screening-events/purchasing", json={
        "requested_by": "procurement.a", "counterparty_name": "Some Vendor LLC",
    })
    event_id = create.json()["event_id"]

    monkeypatch.setenv(
        "MONOPS_DATA_FILE_ALLOWLIST", str(DEMO_OPENSANCTIONS_FILE)
    )
    response = client.post(
        f"/screening-events/{event_id}/screen",
        json={"opensanctions_file": str(SAMPLE_CSL_FILE)},  # real file, just not allowlisted
    )
    assert response.status_code == 400


def test_screen_endpoint_accepts_a_path_inside_the_allowlist(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    create = client.post("/screening-events/purchasing", json={
        "requested_by": "procurement.a", "counterparty_name": "Taiyuan Jinke Semiconductor Technology Co., Ltd.",
    })
    event_id = create.json()["event_id"]

    monkeypatch.setenv("MONOPS_DATA_FILE_ALLOWLIST", str(SAMPLE_CSL_FILE))
    response = client.post(
        f"/screening-events/{event_id}/screen",
        json={"opensanctions_file": str(SAMPLE_CSL_FILE)},
    )
    assert response.status_code == 200, response.text
    assert response.json()["match_count"] == 1
