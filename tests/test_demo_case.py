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
    assert len(body["rows"]) == 3


def test_demo_case_is_idempotent_not_rebuilt_on_second_request(client):
    first = client.get("/cases/demo/worksheet").json()
    second = client.get("/cases/demo/worksheet").json()
    assert [r["finding"]["finding_id"] for r in first["rows"]] == [
        r["finding"]["finding_id"] for r in second["rows"]
    ]


def test_demo_case_carries_the_real_ownership_finding_and_a_labelled_fixture_finding(client):
    rows = client.get("/cases/demo/worksheet").json()["rows"]
    by_source: dict[str, list] = {}
    for r in rows:
        by_source.setdefault(r["finding"]["discovered"]["source"], []).append(r["finding"])

    # Two publication omissions from the labelled synthetic works fixture.
    assert len(by_source["openalex"]) == 2
    assert {f["discovered"]["institution_name"] for f in by_source["openalex"]} == {
        "Beijing Institute of Technology",
        "Zhejiang University",
    }

    # One ownership finding on real DoD 1260H reference data.
    (ownership,) = by_source["gleif_ownership"]
    assert ownership["discovered"]["institution_name"] == "Aviation Industry Corporation of China Ltd."
    assert [h["list_name"] for h in ownership["concern_list_evidence"]] == ["dod_section_1260h"]


def test_demo_case_never_asserts_a_confirmed_finding(client):
    worksheet = client.get("/cases/demo/worksheet").json()
    export = client.get("/cases/demo/investigative-file.json").json()
    blob = (json.dumps(worksheet) + json.dumps(export)).lower()
    assert "confirmed" not in blob
    assert "risk score" not in blob


def test_demo_investigative_file_export_carries_the_synthetic_marker(client):
    """The demo export names a real DoD 1260H company in a fabricated
    ownership chain. Downloaded from a public URL, it must carry its own
    provenance marker -- the Streamlit banner does not travel with the file."""
    export = client.get("/cases/demo/investigative-file.json").json()
    assert export["provenance"]["synthetic"] is True
    notice = export["provenance"]["notice"].lower()
    assert "synthetic" in notice
    assert "not a real finding" in notice
