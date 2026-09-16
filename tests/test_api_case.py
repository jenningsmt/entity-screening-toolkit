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

    # The worksheet must say whose file is open -- the subject fields exist on
    # the Subject and used to stop before this payload (seam closed 2026-09-07).
    assert body["subject_display_name"] == "Wei Chen"
    assert body["subject_id"] == "demo-subject"
    assert body["subject_synthetic"] is True
    # Two discrepancy rows (openalex) + one concern-tie row.
    assert sorted(r["finding"]["discovered"]["source"] for r in body["rows"]) == ["openalex", "openalex"]
    assert len(body["tie_rows"]) == 1
    assert body["can_close"] is False  # nothing actioned yet

    tie = body["tie_rows"][0]["tie"]
    assert tie["tie_kind"] == "declared_employer_ultimate_parent"
    hit = tie["concern_list_evidence"][0]
    assert hit["list_name"] == "dod_section_1260h"
    assert hit["evidence"]["source_attribution"]["license"]


def test_worksheet_closure_rule_and_investigative_file_export(client):
    body = client.get("/cases/demo/worksheet").json()
    ids = [r["finding"]["finding_id"] for r in body["rows"]]
    tie_ids = [r["tie"]["tie_id"] for r in body["tie_rows"]]

    # Cannot advance while unactioned.
    blocked = client.post("/cases/demo/transition", json={"target_state": "adjudication"})
    assert blocked.status_code == 409

    # Bulk-dismiss one, certify the other.
    bulk = client.post(
        "/cases/demo/worksheet/actions",
        json={
            "finding_ids": ids[:1],
            "action": "dismiss",
            "reason_code": "record_error_or_misattribution",
            "reason_note": "stale affiliation",
            "actor": "analyst.a",
        },
    )
    assert bulk.status_code == 200
    assert bulk.json()["batch_id"]

    client.post(
        f"/cases/demo/findings/{ids[1]}/action",
        json={
            "action": "certification_required",
            "reason_code": "possible_nondisclosure_for_certification",
            "reason_note": "undisclosed affiliation",
            "actor": "analyst.a",
        },
    )
    client.post(
        "/cases/demo/certifications",
        json={
            "finding_id": ids[1],
            "substance_of_failure": "Undisclosed affiliation to a foreign institution.",
            "reasons_for_disregarding": "Documented and disclosed elsewhere in the packet.",
            "department_head": "Dr. Head",
        },
    )

    # Findings done -- still cannot close: the concern tie is open.
    assert client.get("/cases/demo/worksheet").json()["can_close"] is False
    tie_resp = client.post(
        f"/cases/demo/ties/{tie_ids[0]}/action",
        json={
            "action": "escalate",
            "reason_code": "needs_counterintelligence_referral",
            "reason_note": "ultimate parent on 1260H",
            "actor": "analyst.a",
        },
    )
    assert tie_resp.status_code == 200

    worksheet = client.get("/cases/demo/worksheet").json()
    assert worksheet["can_close"] is True

    assert client.post("/cases/demo/transition", json={"target_state": "adjudication"}).status_code == 200
    assert client.post(
        "/cases/demo/adjudication",
        json={"assessment": "One item certified; a tie escalated.", "recommendation": "Proceed.", "actor": "analyst.a"},
    ).status_code == 200

    export = client.get("/cases/demo/investigative-file.json")
    assert export.status_code == 200
    payload = export.json()
    assert payload["subject"]["classified_fields"] == {
        "_redacted": True,
        "_reason": "field-level sensitive (use-case-01 Section 9)",
    }
    assert len(payload["findings"]) == 2
    assert len(payload["concern_ties"]) == 1
    assert payload["certifications"]
    assert payload["tie_actions"]["action_history"]
    assert list(payload).index("concern_ties") < list(payload).index("findings")


def test_reason_codes_route_includes_the_tie_vocabularies(client):
    codes = client.get("/cases/reason-codes").json()
    assert "tie_dismiss" in codes and "tie_escalation" in codes
    assert "historical_or_divested_relationship" in codes["tie_dismiss"]


def test_dismissal_basis_summary_splits_by_observation_kind(client):
    body = client.get("/cases/demo/worksheet").json()
    fid = body["rows"][0]["finding"]["finding_id"]
    tid = body["tie_rows"][0]["tie"]["tie_id"]
    client.post(
        f"/cases/demo/findings/{fid}/action",
        json={"action": "dismiss", "reason_code": "analyst_judgment_not_material", "reason_note": "", "actor": "a"},
    )
    client.post(
        f"/cases/demo/ties/{tid}/action",
        json={"action": "dismiss", "reason_code": "historical_or_divested_relationship", "reason_note": "", "actor": "a"},
    )
    summary = client.get("/cases/dismissal-basis-summary").json()
    assert summary["discrepancy"]["by_reason_code"][0]["reason_code"] == "analyst_judgment_not_material"
    assert summary["concern_tie"]["by_reason_code"][0]["reason_code"] == "historical_or_divested_relationship"


def test_tie_action_rejects_a_discrepancy_vocabulary_code(client):
    tid = client.get("/cases/demo/worksheet").json()["tie_rows"][0]["tie"]["tie_id"]
    resp = client.post(
        f"/cases/demo/ties/{tid}/action",
        json={"action": "dismiss", "reason_code": "outside_declaration_scope", "reason_note": "", "actor": "a"},
    )
    assert resp.status_code == 400


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


# --- B2: the demo's pre-generated explanations are reachable anonymously ---


def test_anonymous_get_returns_cached_explanation_but_post_stays_gated(client, monkeypatch):
    monkeypatch.setenv("MONOPS_ACTION_SECRET", "s3cr3t")
    worksheet = client.get("/cases/demo/worksheet").json()
    finding_id = worksheet["rows"][0]["finding"]["finding_id"]
    tie_id = worksheet["tie_rows"][0]["tie"]["tie_id"]

    get_finding = client.get(f"/cases/demo/findings/{finding_id}/explanation")
    assert get_finding.status_code == 200
    body = get_finding.json()
    assert body["observation_id"] == finding_id
    assert body["recitation"]

    get_tie = client.get(f"/cases/demo/ties/{tie_id}/explanation")
    assert get_tie.status_code == 200
    assert get_tie.json()["observation_id"] == tie_id

    post_finding = client.post(f"/cases/demo/findings/{finding_id}/explanation", json={})
    assert post_finding.status_code == 403
    post_tie = client.post(f"/cases/demo/ties/{tie_id}/explanation", json={})
    assert post_tie.status_code == 403


def test_get_explanation_404s_for_an_unknown_observation_id(client):
    client.get("/cases/demo/worksheet")  # trigger self-heal
    assert client.get("/cases/demo/findings/not-a-real-id/explanation").status_code == 404
    assert client.get("/cases/demo/ties/not-a-real-id/explanation").status_code == 404


def test_get_explanation_misses_cache_after_a_prompt_version_bump(client, monkeypatch):
    """The GET path and explain()'s own cache check must agree on what
    counts as stale: bumping PROMPT_VERSION changes evidence_hash_for's
    output, so a row cached under the old prompt version must not be served
    as if it were still current."""
    from entity_screening.explanation import service as explanation_service

    worksheet = client.get("/cases/demo/worksheet").json()
    finding_id = worksheet["rows"][0]["finding"]["finding_id"]
    assert client.get(f"/cases/demo/findings/{finding_id}/explanation").status_code == 200

    # PROMPT_VERSION is imported into service.py's own namespace (`from
    # ...generate import PROMPT_VERSION`), so evidence_hash_for reads
    # service.PROMPT_VERSION, not generate.PROMPT_VERSION -- patch it there.
    monkeypatch.setattr(explanation_service, "PROMPT_VERSION", "test-bumped-version")
    assert client.get(f"/cases/demo/findings/{finding_id}/explanation").status_code == 404


# --- S7: redact=false requires the action secret ---------------------------


def test_redact_false_requires_the_action_secret(client, monkeypatch):
    monkeypatch.setenv("MONOPS_ACTION_SECRET", "s3cr3t")
    client.get("/cases/demo/worksheet")  # trigger self-heal

    unauth = client.get("/cases/demo/investigative-file.json?redact=false")
    assert unauth.status_code == 403

    ok = client.get(
        "/cases/demo/investigative-file.json?redact=false",
        headers={"X-Monops-Action-Secret": "s3cr3t"},
    )
    assert ok.status_code == 200
    assert ok.json()["subject"]["classified_fields"] != {
        "_redacted": True,
        "_reason": "field-level sensitive (use-case-01 Section 9)",
    }


def test_redact_default_stays_open_and_redacted(client, monkeypatch):
    monkeypatch.setenv("MONOPS_ACTION_SECRET", "s3cr3t")
    client.get("/cases/demo/worksheet")  # trigger self-heal

    response = client.get("/cases/demo/investigative-file.json")
    assert response.status_code == 200
    assert response.json()["subject"]["classified_fields"] == {
        "_redacted": True,
        "_reason": "field-level sensitive (use-case-01 Section 9)",
    }
