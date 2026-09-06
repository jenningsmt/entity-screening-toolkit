"""HTTP surface for Use Case 01 -- the case worksheet API."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from entity_screening.api.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ENTITY_SCREENING_DB_PATH", str(tmp_path / "test.duckdb"))
    monkeypatch.setenv("ENTITY_SCREENING_RUNS_DIR", str(tmp_path / "runs"))
    return TestClient(app)


def test_demo_case_self_heals_and_shows_a_worked_worksheet(client):
    response = client.get("/cases/demo/worksheet")
    assert response.status_code == 200
    body = response.json()
    assert body["case_id"] == "demo"
    assert body["state"] == "worksheet"
    # Two publication omissions + one ownership-parent-on-1260H finding.
    sources = sorted(r["finding"]["discovered"]["source"] for r in body["rows"])
    assert sources == ["gleif_ownership", "openalex", "openalex"]
    assert body["can_close"] is False  # nothing actioned yet

    ownership_row = next(
        r for r in body["rows"] if r["finding"]["discovered"]["source"] == "gleif_ownership"
    )
    hit = ownership_row["finding"]["concern_list_evidence"][0]
    assert hit["list_name"] == "dod_section_1260h"
    assert hit["evidence"]["source_attribution"]["license"]


def test_worksheet_closure_rule_and_investigative_file_export(client):
    rows = client.get("/cases/demo/worksheet").json()["rows"]
    ids = [r["finding"]["finding_id"] for r in rows]

    # Cannot advance while unactioned.
    blocked = client.post("/cases/demo/transition", json={"target_state": "adjudication"})
    assert blocked.status_code == 409

    # Bulk-dismiss two, certify the third.
    bulk = client.post(
        "/cases/demo/worksheet/actions",
        json={
            "finding_ids": ids[:2],
            "action": "dismiss",
            "reason_code": "record_error_or_misattribution",
            "reason_note": "stale affiliations",
            "actor": "analyst.a",
        },
    )
    assert bulk.status_code == 200
    assert bulk.json()["batch_id"]

    client.post(
        f"/cases/demo/findings/{ids[2]}/action",
        json={
            "action": "certification_required",
            "reason_code": "possible_nondisclosure_for_certification",
            "reason_note": "ultimate parent on 1260H",
            "actor": "analyst.a",
        },
    )
    client.post(
        "/cases/demo/certifications",
        json={
            "finding_id": ids[2],
            "substance_of_failure": "Undisclosed ultimate parent on the DoD 1260H list.",
            "reasons_for_disregarding": "Documented and disclosed elsewhere in the packet.",
            "department_head": "Dr. Head",
        },
    )

    worksheet = client.get("/cases/demo/worksheet").json()
    assert worksheet["can_close"] is True

    assert client.post("/cases/demo/transition", json={"target_state": "adjudication"}).status_code == 200
    assert client.post(
        "/cases/demo/adjudication",
        json={"assessment": "One item certified; rest dismissed.", "recommendation": "Proceed.", "actor": "analyst.a"},
    ).status_code == 200

    export = client.get("/cases/demo/investigative-file.json")
    assert export.status_code == 200
    payload = export.json()
    assert payload["subject"]["classified_fields"] == {
        "_redacted": True,
        "_reason": "field-level sensitive (use-case-01 Section 9)",
    }
    assert len(payload["findings"]) == 3
    assert payload["certifications"]
    assert payload["adjudications"][0]["assessment"].startswith("One item certified")


def test_invalid_reason_code_is_rejected(client):
    ids = [r["finding"]["finding_id"] for r in client.get("/cases/demo/worksheet").json()["rows"]]
    resp = client.post(
        f"/cases/demo/findings/{ids[0]}/action",
        json={"action": "dismiss", "reason_code": "not_substantial", "reason_note": "", "actor": "a"},
    )
    assert resp.status_code == 400


def test_create_case_rejects_non_synthetic_subject(client):
    resp = client.post(
        "/cases",
        json={
            "case_id": "c1",
            "subject_id": "s1",
            "subject_display_name": "Real Person",
            "coverage_basis": "151a1",
            "synthetic": False,
            "trigger": "hire",
            "access_scope": "data",
            "declaration_sources": [],
            "declared_affiliations": [],
        },
    )
    assert resp.status_code == 400


def test_action_gate_blocks_mutations_when_a_secret_is_configured(client, monkeypatch):
    monkeypatch.setenv("MONOPS_ACTION_SECRET", "s3cr3t")
    ids = [r["finding"]["finding_id"] for r in client.get("/cases/demo/worksheet").json()["rows"]]
    unauth = client.post(
        f"/cases/demo/findings/{ids[0]}/action",
        json={"action": "dismiss", "reason_code": "record_error_or_misattribution", "reason_note": "", "actor": "a"},
    )
    assert unauth.status_code == 403
    ok = client.post(
        f"/cases/demo/findings/{ids[0]}/action",
        json={"action": "dismiss", "reason_code": "record_error_or_misattribution", "reason_note": "", "actor": "a"},
        headers={"X-Monops-Action-Secret": "s3cr3t"},
    )
    assert ok.status_code == 200
