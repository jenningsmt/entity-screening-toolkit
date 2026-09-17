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

from entity_screening.case.vocab import is_valid_rps_reason_code
from entity_screening.common import storage
from entity_screening.common.schema import SourceRecord, WorksheetActionKind
from entity_screening.ingestion.base import IngestionErrorLog
from entity_screening.ingestion.opensanctions import OpenSanctionsTargetsIngester
from entity_screening.screening import rps_service, rps_store
from entity_screening.screening.lists import OpenSanctionsList, cached_concern_list
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
    # M14: which real-world role produced the match, without a separate
    # join back to the party record.
    assert match.matched_field == "counterparty"


def test_screen_party_no_match_returns_empty(tmp_path):
    concern_list = _csl_concern_list(tmp_path)
    party = ScreeningParty(
        party_id="p2", event_id="e1", kind=PartyKind.PERSON,
        name="A Totally Unrelated Name Zzqx", country="us", role_in_event="subject",
    )
    assert screen_parties([party], [concern_list])["p2"] == []


def test_screen_party_person_kind_does_not_false_positive_via_the_pre_fix_acronym_bug(tmp_path):
    """S9, end to end through screen_party: a PartyKind.PERSON party with a
    non-ASCII name must not falsely match an unrelated list entry the way
    the pre-fix ASCII-only acronym regex + corporate-suffix-stripping
    combination would have (confirmed directly in test_matcher.py)."""
    error_log = IngestionErrorLog(tmp_path / "errors.jsonl")
    error_log.close()
    concern_list = OpenSanctionsList(
        [
            SourceRecord(
                source_dataset="opensanctions_targets_simple",
                retrieval_date=None,
                source_record_id="entry-1",
                fields={
                    "id": "entry-1", "schema": "Person",
                    "name": "Akın Alptuna", "aliases": "",
                },
            )
        ]
    )
    party = ScreeningParty(
        party_id="p-person", event_id="e1", kind=PartyKind.PERSON,
        name="Ana Sa", country="us", role_in_event="subject",
    )
    assert screen_parties([party], [concern_list])["p-person"] == []


def test_screen_party_organization_kind_acronym_matching_is_unaffected(tmp_path):
    """The org path's real acronym matching (Epic B's own acceptance
    criterion) must still fire after S9's person-kind bypass -- the
    bypass is opt-in per party kind, not a global regression."""
    concern_list = OpenSanctionsList(
        [
            SourceRecord(
                source_dataset="opensanctions_targets_simple",
                retrieval_date=None,
                source_record_id="entry-ibm",
                fields={"id": "entry-ibm", "schema": "Company", "name": "IBM", "aliases": ""},
            )
        ]
    )
    party = ScreeningParty(
        party_id="p-org", event_id="e1", kind=PartyKind.ORGANIZATION,
        name="International Business Machines Corporation", country="us",
        role_in_event="counterparty",
    )
    matches = screen_parties([party], [concern_list])["p-org"]
    assert len(matches) == 1
    assert matches[0].evidence["match_basis"] == "acronym"


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
    # M14: the employer (not the subject) is what matched, visible without
    # a separate join back to the party record.
    assert matches[0]["matched_field"] == "current_employer"

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


# --------------------------------------------------------------------------
# S10: a zero-list screen must not render like "screened, clean."
# --------------------------------------------------------------------------


def test_get_event_shows_no_manifest_before_any_screen(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    event_id = client.post(
        "/screening-events/purchasing",
        json={"requested_by": "procurement.a", "counterparty_name": "Some Vendor LLC"},
    ).json()["event_id"]

    body = client.get(f"/screening-events/{event_id}").json()
    assert body["screening_manifest"] is None


def test_screening_with_no_file_is_distinguishable_from_a_real_clean_screen(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    event_id = client.post(
        "/screening-events/purchasing",
        json={"requested_by": "procurement.a", "counterparty_name": "Some Vendor LLC"},
    ).json()["event_id"]

    zero_list = client.post(
        f"/screening-events/{event_id}/screen", json={"opensanctions_file": None}
    ).json()
    assert zero_list["match_count"] == 0
    assert zero_list["screening_manifest"]["opensanctions_snapshot_date"] is None

    real_clean = client.post(
        f"/screening-events/{event_id}/screen",
        json={"opensanctions_file": str(SAMPLE_CSL_FILE)},
    ).json()
    assert real_clean["match_count"] == 0  # "Some Vendor LLC" matches nothing real
    assert real_clean["screening_manifest"]["opensanctions_snapshot_date"] is not None

    # A later plain GET sees the same distinction, not just the POST response.
    later = client.get(f"/screening-events/{event_id}").json()
    assert later["screening_manifest"]["opensanctions_snapshot_date"] is not None
    assert later["screening_manifest"]["match_count"] == 0


# --------------------------------------------------------------------------
# S11: don't re-ingest and re-index the whole concern list on every call.
# --------------------------------------------------------------------------


def test_cached_concern_list_returns_the_same_object_for_an_unchanged_file(tmp_path):
    path = tmp_path / "targets.csv"
    path.write_text("id,schema,name,aliases\n1,Company,Acme Corp,\n", encoding="utf-8")
    build_calls = []

    def build():
        build_calls.append(1)
        return OpenSanctionsList([])

    first = cached_concern_list(path, "opensanctions", build)
    second = cached_concern_list(path, "opensanctions", build)

    assert first is second
    assert len(build_calls) == 1  # the builder only ran once


def test_cached_concern_list_rebuilds_after_the_file_is_replaced(tmp_path):
    path = tmp_path / "targets.csv"
    path.write_text("id,schema,name,aliases\n1,Company,Acme Corp,\n", encoding="utf-8")

    first = cached_concern_list(path, "opensanctions", lambda: OpenSanctionsList([]))

    import os
    import time

    time.sleep(0.01)
    path.write_text("id,schema,name,aliases\n1,Company,Acme Corp,\n2,Company,Other Corp,\n", encoding="utf-8")
    os.utime(path, None)  # force a distinct mtime even on filesystems with coarse resolution

    second = cached_concern_list(path, "opensanctions", lambda: OpenSanctionsList([]))

    assert first is not second


def test_screen_event_does_not_re_ingest_the_same_file_on_a_second_call(tmp_path, monkeypatch):
    """S11's actual regression guard: a second screen_event call against
    the same file must not re-parse it. Confirmed by call-counting the
    ingester's stream_records, not just by eyeballing timing -- on the
    unmodified tree this fails (called twice). Uses a tmp_path-local copy
    of the fixture rather than SAMPLE_CSL_FILE directly -- the cache is
    per-process (module-level), so a path other tests in this same
    session already warmed would make this test observe a false 0, not a
    real 1."""
    local_csl_file = tmp_path / "csl.csv"
    local_csl_file.write_text(SAMPLE_CSL_FILE.read_text(encoding="utf-8"), encoding="utf-8")

    client = _client(tmp_path, monkeypatch)
    event_id = client.post(
        "/screening-events/purchasing",
        json={"requested_by": "procurement.a", "counterparty_name": "Some Vendor LLC"},
    ).json()["event_id"]

    from entity_screening.ingestion import opensanctions as os_ingest

    calls = []
    real_stream_records = os_ingest.OpenSanctionsTargetsIngester.stream_records

    def counted_stream_records(self):
        calls.append(1)
        return real_stream_records(self)

    monkeypatch.setattr(
        os_ingest.OpenSanctionsTargetsIngester, "stream_records", counted_stream_records
    )

    client.post(
        f"/screening-events/{event_id}/screen",
        json={"opensanctions_file": str(local_csl_file)},
    )
    client.post(
        f"/screening-events/{event_id}/screen",
        json={"opensanctions_file": str(local_csl_file)},
    )

    assert len(calls) == 1


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


def test_api_list_events_limit_is_bounded(tmp_path, monkeypatch):
    """M16: an unbounded caller-controlled `limit` on a public read."""
    client = _client(tmp_path, monkeypatch)
    assert client.get("/screening-events", params={"limit": 500}).status_code == 200
    assert client.get("/screening-events", params={"limit": 501}).status_code == 422
    assert client.get("/screening-events", params={"limit": 0}).status_code == 422


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


# --------------------------------------------------------------------------
# M15: RPS must not accept a Sec. 51B.153/HB127-specific disposition.
# --------------------------------------------------------------------------


def test_is_valid_rps_reason_code_rejects_certification_required():
    """Confirmed live before the fix: this returned True, because
    is_valid_rps_reason_code only special-cased "dismiss" and treated
    every other action -- including certification_required, a Sec.
    51B.153/HB127-only concept -- as if it were "escalate"."""
    assert is_valid_rps_reason_code("certification_required", "needs_resec_determination") is False


def test_is_valid_rps_reason_code_rejects_request_clarification():
    assert is_valid_rps_reason_code("request_clarification", "needs_resec_determination") is False


def test_is_valid_rps_reason_code_still_accepts_dismiss_and_escalate():
    assert is_valid_rps_reason_code("dismiss", "coincidental_name_match") is True
    assert is_valid_rps_reason_code("escalate", "needs_resec_determination") is True


def test_api_disposition_rejects_certification_required(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    create = client.post("/screening-events/purchasing", json={
        "requested_by": "procurement.a",
        "counterparty_name": "Taiyuan Jinke Semiconductor Technology Co., Ltd.",
    })
    event_id = create.json()["event_id"]
    screen = client.post(
        f"/screening-events/{event_id}/screen",
        json={"opensanctions_file": str(SAMPLE_CSL_FILE)},
    )
    match_id = screen.json()["matches"][0]["match_id"]

    response = client.post(
        f"/screening-events/{event_id}/matches/{match_id}/disposition",
        json={
            "action": "certification_required",
            "reason_code": "needs_resec_determination",
            "reason_note": "Should be rejected -- not an RPS-valid action.",
            "actor": "hr.a",
        },
    )
    assert response.status_code == 400
