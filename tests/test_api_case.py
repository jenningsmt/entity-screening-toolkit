"""HTTP surface for Use Case 01 -- the case worksheet API."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from entity_screening.api.main import app
from entity_screening.case import demo, store as case_store
from entity_screening.common import storage
from entity_screening.pipeline import reconcile_case


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


def test_reason_codes_route_includes_the_outcome_vocabulary(client):
    codes = client.get("/cases/reason-codes").json()
    assert set(codes["outcomes"]) == {
        "cleared", "cleared_with_certification", "not_cleared", "withdrawn",
    }


def test_dismissal_basis_summary_excludes_demo_cases_and_open_cases(client):
    """M7: dismissing a row on the (open, demo) case must never appear --
    the summary is "the office's accumulated case law" (closed, real
    cases only), not a live scratch pad, and the demo case is excluded
    regardless of state."""
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
    assert summary["discrepancy"]["by_reason_code"] == []
    assert summary["concern_tie"]["by_reason_code"] == []


def _real_closed_case_with_a_dismissed_finding(client, tmp_path, case_id="c1"):
    """A non-demo case, reconciled directly at the pipeline layer (the
    route only injects a works_fixture for demo cases), driven through the
    full lifecycle to CLOSED with one finding dismissed along the way."""
    resp = client.post(
        "/cases",
        json={
            "case_id": case_id,
            "subject_id": f"{case_id}-subj",
            "subject_display_name": "Test Subject",
            "coverage_basis": "151a1",
            "synthetic": True,
            "trigger": "hire",
            "access_scope": "data",
            "declaration_sources": [],
            "declared_affiliations": [],
        },
    )
    assert resp.status_code == 200

    db_path = tmp_path / "test.duckdb"
    works_fixture = [
        {
            "id": "https://openalex.org/W1",
            "publication_date": "2022-01-01",
            "authorships": [
                {
                    "is_subject": True,
                    "author_position": "first",
                    "author": {"id": "https://openalex.org/A1", "display_name": "Test Subject"},
                    "institutions": [
                        {"display_name": "Ordinary University", "country_code": "US"}
                    ],
                }
            ],
        }
    ]
    reconcile_case(case_id, db_path=db_path, runs_dir=tmp_path / "runs", works_fixture=works_fixture)

    worksheet = client.get(f"/cases/{case_id}/worksheet").json()
    fid = worksheet["rows"][0]["finding"]["finding_id"]
    client.post(
        f"/cases/{case_id}/findings/{fid}/action",
        json={"action": "dismiss", "reason_code": "analyst_judgment_not_material", "reason_note": "", "actor": "a"},
    )
    assert client.post(
        f"/cases/{case_id}/transition", json={"target_state": "adjudication"}
    ).status_code == 200
    client.post(
        f"/cases/{case_id}/adjudication",
        json={"assessment": "Not material.", "recommendation": "Proceed.", "actor": "a"},
    )
    assert client.post(
        f"/cases/{case_id}/transition", json={"target_state": "outcome"}
    ).status_code == 200
    client.post(f"/cases/{case_id}/outcome", json={"outcome": "cleared", "actor": "a", "note": ""})
    assert client.post(
        f"/cases/{case_id}/transition", json={"target_state": "closed"}
    ).status_code == 200
    return case_id


def test_dismissal_basis_summary_includes_a_real_closed_case(client, tmp_path):
    _real_closed_case_with_a_dismissed_finding(client, tmp_path)
    summary = client.get("/cases/dismissal-basis-summary").json()
    assert summary["discrepancy"]["by_reason_code"][0]["reason_code"] == "analyst_judgment_not_material"


def test_dismissal_basis_summary_excludes_a_still_open_real_case(client, tmp_path):
    db_path = tmp_path / "test.duckdb"
    client.post(
        "/cases",
        json={
            "case_id": "c2",
            "subject_id": "c2-subj",
            "subject_display_name": "Test Subject Two",
            "coverage_basis": "151a1",
            "synthetic": True,
            "trigger": "hire",
            "access_scope": "data",
            "declaration_sources": [],
            "declared_affiliations": [],
        },
    )
    works_fixture = [
        {
            "id": "https://openalex.org/W2",
            "publication_date": "2022-01-01",
            "authorships": [
                {
                    "is_subject": True,
                    "author_position": "first",
                    "author": {"id": "https://openalex.org/A2", "display_name": "Test Subject Two"},
                    "institutions": [
                        {"display_name": "Another University", "country_code": "US"}
                    ],
                }
            ],
        }
    ]
    reconcile_case("c2", db_path=db_path, runs_dir=tmp_path / "runs", works_fixture=works_fixture)
    worksheet = client.get("/cases/c2/worksheet").json()
    fid = worksheet["rows"][0]["finding"]["finding_id"]
    client.post(
        f"/cases/c2/findings/{fid}/action",
        json={"action": "dismiss", "reason_code": "analyst_judgment_not_material", "reason_note": "", "actor": "a"},
    )
    # Case c2 is left open (WORKSHEET) -- must not appear.
    summary = client.get("/cases/dismissal-basis-summary").json()
    assert summary["discrepancy"]["by_reason_code"] == []


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


def _create_case_request(case_id: str, subject_id: str = "s1") -> dict:
    return {
        "case_id": case_id,
        "subject_id": subject_id,
        "subject_display_name": "Test Subject",
        "coverage_basis": "151a1",
        "synthetic": True,
        "trigger": "hire",
        "access_scope": "data",
        "declaration_sources": [],
        "declared_affiliations": [],
    }


def test_create_case_rejects_the_reserved_demo_case_ids(client):
    assert client.post("/cases", json=_create_case_request("demo")).status_code == 409
    assert client.post("/cases", json=_create_case_request("demo-coi")).status_code == 409


def test_create_case_rejects_an_existing_case_id_instead_of_overwriting(client):
    first = client.post("/cases", json=_create_case_request("c1"))
    assert first.status_code == 200

    second = client.post("/cases", json=_create_case_request("c1", subject_id="s2"))
    assert second.status_code == 409

    # The first case's data is untouched by the rejected second attempt.
    worksheet = client.get("/cases/c1/worksheet").json()
    assert worksheet["subject_id"] == "s1"


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


# --- S5: the money test -- re-reconciling doesn't orphan actions or the ---
# --- explanation cache, because finding_id/tie_id are now deterministic ---


def test_reconcile_action_reconcile_again_survives_with_no_orphans(client, tmp_path):
    """Reconcile (self-heal), dismiss a finding, fetch its cached
    explanation, then re-reconcile the case directly at the pipeline layer
    (bypassing the route's new state guard on purpose -- that guard has
    its own tests; this test is about id/cache stability once a
    re-reconcile legitimately happens, e.g. after a re-open). The action
    must still be attached to the same finding_id, the cached explanation
    must still be servable, and no `explanations` row may reference an id
    that no longer exists."""
    worksheet = client.get("/cases/demo/worksheet").json()  # triggers self-heal
    finding_id = worksheet["rows"][0]["finding"]["finding_id"]

    dismiss = client.post(
        f"/cases/demo/findings/{finding_id}/action",
        json={
            "action": "dismiss",
            "reason_code": "record_error_or_misattribution",
            "reason_note": "",
            "actor": "analyst.a",
        },
    )
    assert dismiss.status_code == 200

    cached_before = client.get(f"/cases/demo/findings/{finding_id}/explanation")
    assert cached_before.status_code == 200

    db_path = tmp_path / "test.duckdb"
    reconcile_case(
        demo.DEMO_CASE_ID,
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        works_fixture=demo.load_demo_works_fixture(),
        gleif_lei_file=demo.DEMO_GLEIF_LEI_FILE,
        gleif_relationships_file=demo.DEMO_GLEIF_RELATIONSHIPS_FILE,
    )

    worksheet_after = client.get("/cases/demo/worksheet").json()
    row_after = next(r for r in worksheet_after["rows"] if r["finding"]["finding_id"] == finding_id)
    assert row_after["action"] is not None
    assert row_after["action"]["action"] == "dismiss"

    cached_after = client.get(f"/cases/demo/findings/{finding_id}/explanation")
    assert cached_after.status_code == 200
    assert cached_after.json() == cached_before.json()

    conn = storage.connect(db_path)
    try:
        current_ids = {f.finding_id for f in case_store.load_findings(conn, demo.DEMO_CASE_ID)}
        current_ids |= {t.tie_id for t in case_store.load_ties(conn, demo.DEMO_CASE_ID)}
        explanation_ids = {
            row[0]
            for row in conn.execute(
                "SELECT observation_id FROM explanations WHERE case_id = ?",
                [demo.DEMO_CASE_ID],
            ).fetchall()
        }
        assert explanation_ids <= current_ids, (
            f"orphan explanation rows referencing removed ids: {explanation_ids - current_ids}"
        )
    finally:
        conn.close()


# --- S5 (state guard): reconcile refused once a case has left DISCOVERY ---


def _drive_demo_case_to_closed(client):
    """Actions every row, then ADJUDICATION -> record adjudication ->
    OUTCOME -> record outcome -> CLOSED -- the only path back to a state
    reconcile is allowed in again (CLOSED -> DISCOVERY), per S5's state
    guard's own structural note: there is no direct edge from
    WORKSHEET/ADJUDICATION/OUTCOME back to DISCOVERY."""
    body = client.get("/cases/demo/worksheet").json()
    ids = [r["finding"]["finding_id"] for r in body["rows"]]
    tie_ids = [r["tie"]["tie_id"] for r in body["tie_rows"]]
    for fid in ids:
        client.post(
            f"/cases/demo/findings/{fid}/action",
            json={
                "action": "dismiss",
                "reason_code": "record_error_or_misattribution",
                "reason_note": "",
                "actor": "analyst.a",
            },
        )
    for tid in tie_ids:
        client.post(
            f"/cases/demo/ties/{tid}/action",
            json={
                "action": "dismiss",
                "reason_code": "historical_or_divested_relationship",
                "reason_note": "",
                "actor": "analyst.a",
            },
        )
    assert client.post(
        "/cases/demo/transition", json={"target_state": "adjudication"}
    ).status_code == 200
    assert client.post(
        "/cases/demo/adjudication",
        json={"assessment": "Nothing material.", "recommendation": "Proceed.", "actor": "analyst.a"},
    ).status_code == 200
    assert client.post(
        "/cases/demo/transition", json={"target_state": "outcome"}
    ).status_code == 200
    assert client.post(
        "/cases/demo/outcome",
        json={"outcome": "cleared", "actor": "analyst.a", "note": ""},
    ).status_code == 200
    assert client.post(
        "/cases/demo/transition", json={"target_state": "closed"}
    ).status_code == 200


def test_reconcile_is_refused_once_the_case_is_in_worksheet(client):
    client.get("/cases/demo/worksheet")  # trigger self-heal -> state is worksheet

    blocked = client.post("/cases/demo/reconcile", json={})
    assert blocked.status_code == 409

    _drive_demo_case_to_closed(client)
    still_blocked = client.post("/cases/demo/reconcile", json={})
    assert still_blocked.status_code == 409

    reopened = client.post("/cases/demo/transition", json={"target_state": "discovery"})
    assert reopened.status_code == 200

    allowed = client.post("/cases/demo/reconcile", json={})
    assert allowed.status_code == 200
