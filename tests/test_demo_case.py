"""The self-healing HB 127 demo case (case_id="demo").

Mirror of test_demo_run.py for the case path: it must build itself from
bundled fixtures on first access, with no live network call, and show a
real, worked-through worksheet.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from entity_screening.api.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ENTITY_SCREENING_DB_PATH", str(tmp_path / "test.duckdb"))
    monkeypatch.setenv("ENTITY_SCREENING_RUNS_DIR", str(tmp_path / "runs"))
    return TestClient(app)


def test_demo_case_self_heals_on_first_worksheet_request(client):
    response = client.get("/cases/demo/worksheet")
    assert response.status_code == 200
    body = response.json()
    assert body["case_id"] == "demo"
    assert body["state"] == "worksheet"
    assert len(body["rows"]) == 2  # two discrepancies
    assert len(body["tie_rows"]) == 1  # one concern tie
    assert body["can_close"] is False


def test_demo_case_is_idempotent_not_rebuilt_on_second_request(client):
    first = client.get("/cases/demo/worksheet").json()
    second = client.get("/cases/demo/worksheet").json()
    assert [r["finding"]["finding_id"] for r in first["rows"]] == [
        r["finding"]["finding_id"] for r in second["rows"]
    ]
    assert [r["tie"]["tie_id"] for r in first["tie_rows"]] == [
        r["tie"]["tie_id"] for r in second["tie_rows"]
    ]


def test_demo_discrepancies_are_the_two_labelled_fixture_affiliations(client):
    rows = client.get("/cases/demo/worksheet").json()["rows"]
    assert all(r["finding"]["discovered"]["source"] == "openalex" for r in rows)
    assert {r["finding"]["discovered"]["institution_name"] for r in rows} == {
        "Beijing Institute of Technology",
        "Zhejiang University",
    }


def test_demo_concern_tie_is_the_ownership_parent_on_the_real_1260h_list(client):
    tie_rows = client.get("/cases/demo/worksheet").json()["tie_rows"]
    assert len(tie_rows) == 1
    tie = tie_rows[0]["tie"]
    assert tie["tie_kind"] == "declared_employer_ultimate_parent"
    assert tie["concern_entity_name"] == "Aviation Industry Corporation of China Ltd."
    assert [h["list_name"] for h in tie["concern_list_evidence"]] == ["dod_section_1260h"]
    assert tie["related_finding_id"] is None
    # Section 10 licence NFR reaches the tie evidence.
    hit = tie["concern_list_evidence"][0]
    assert hit["evidence"]["source_attribution"]["license"]
    assert hit["evidence"]["ownership_path"]["source_attribution"]["license"]


def test_demo_case_never_asserts_a_confirmed_observation(client):
    worksheet = client.get("/cases/demo/worksheet").json()
    export = client.get("/cases/demo/investigative-file.json").json()
    blob = (json.dumps(worksheet) + json.dumps(export)).lower()
    assert "confirmed" not in blob
    assert "risk score" not in blob


def test_a_stale_demo_case_is_rebuilt_when_the_fixture_version_moves(client, tmp_path):
    """Simulates the deployed instance: a demo case built under an older
    fixture version, with a stale row, is wiped and re-reconciled on the
    first request after DEMO_FIXTURE_VERSION moves."""
    from entity_screening.case import demo, store
    from entity_screening.common import storage

    db_path = tmp_path / "test.duckdb"
    conn = storage.connect(db_path)
    demo.build_demo_case(conn)
    # a stale finding + an old version marker
    conn.execute(
        "INSERT INTO findings (finding_id, case_id, run_id, discovered, declaration_search, "
        "factual_basis, nearest_declared) VALUES (?,?,?,?,?,?,?)",
        ["stale", "demo", "old", '{"source":"gleif_ownership","institution_name":"Stale",'
         '"country":null,"country_on_adversary_list":null,"adversary_list_version":null,'
         '"first_observed":null,"last_observed":null,"record_count":1,"role":null,"source_refs":[]}',
         "[]", "absent_outside_all_source_scopes", "[]"],
    )
    store.demo_meta_set(conn, "fixture_version", "1")
    conn.close()

    body = client.get("/cases/demo/worksheet").json()
    names = {r["finding"]["discovered"]["institution_name"] for r in body["rows"]}
    assert "Stale" not in names
    assert names == {"Beijing Institute of Technology", "Zhejiang University"}

    conn = storage.connect(db_path)
    assert store.demo_meta_get(conn, "fixture_version") == str(demo.DEMO_FIXTURE_VERSION)
    conn.close()


def test_demo_investigative_file_export_carries_the_synthetic_marker(client):
    """The demo export names a real DoD 1260H company in a fabricated
    ownership chain. Downloaded from a public URL, it must carry its own
    provenance marker -- the Streamlit banner does not travel with the file."""
    export = client.get("/cases/demo/investigative-file.json").json()
    assert export["provenance"]["synthetic"] is True
    notice = export["provenance"]["notice"].lower()
    assert "synthetic" in notice
    assert "not a real finding" in notice
