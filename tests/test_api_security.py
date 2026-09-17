"""Workstream 2's binding tests: the action-secret gate (2a) and the
data-file allowlist (2b). Both must default to "unchanged behavior" when
their env var is unset -- that's the correct trust boundary for a single
local user (dev, the CLI), and every other test in this suite relies on it
staying true.
"""
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from entity_screening.api.main import app
from entity_screening.bibliometric import openalex_client

FIXTURES_DIR = Path(__file__).parent / "fixtures"
NSF_FILE = str(FIXTURES_DIR / "sample_nsf_awards.json")
OPENSANCTIONS_FILE = str(FIXTURES_DIR / "sample_opensanctions_targets.csv")
GLEIF_LEI_FILE = str(FIXTURES_DIR / "sample_gleif_lei.csv")
GLEIF_RELATIONSHIPS_FILE = str(FIXTURES_DIR / "sample_gleif_relationships.csv")
OUTSIDE_FILE = str(FIXTURES_DIR / "sample_dod_1260h.json")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ENTITY_SCREENING_DB_PATH", str(tmp_path / "test.duckdb"))
    monkeypatch.setenv("ENTITY_SCREENING_RUNS_DIR", str(tmp_path / "runs"))
    return TestClient(app)


@pytest.fixture(autouse=True)
def no_live_openalex_calls(monkeypatch):
    """B4-followup's /cases/{id}/reconcile tests below drive a non-demo
    case through the real pipeline, which (unlike the demo path) has no
    works_fixture to short-circuit discover_from_publications -- the HTTP
    route can't accept an injectable fetch over the wire either. Monkeypatch
    the client's actual default HTTP function instead, so this suite never
    hits the live network (same principle, same fix, as
    test_api_bibliometric.py's fixture of the same name)."""
    def fake_http_get(url, params):
        return {"results": []}

    monkeypatch.setattr(openalex_client, "_http_get", fake_http_get)


def _create_run(client, **headers) -> object:
    return client.post(
        "/runs",
        json={"opensanctions_file": OPENSANCTIONS_FILE, "nsf_file": NSF_FILE},
        headers=headers,
    )


# --- 2a: action secret ------------------------------------------------------


def test_health_reports_action_gate_enabled_but_never_the_secret_value(client, monkeypatch):
    monkeypatch.setenv("MONOPS_ACTION_SECRET", "correct-horse")
    body = client.get("/health").json()
    assert body["action_gate_enabled"] is True
    assert "correct-horse" not in str(body)


def test_action_secret_unset_means_post_runs_unchanged(client):
    response = _create_run(client)
    assert response.status_code == 200


def test_action_secret_set_and_absent_refuses_post_runs(client, monkeypatch):
    monkeypatch.setenv("MONOPS_ACTION_SECRET", "correct-horse")
    response = _create_run(client)
    assert response.status_code == 403


def test_action_secret_set_and_wrong_refuses_post_runs(client, monkeypatch):
    monkeypatch.setenv("MONOPS_ACTION_SECRET", "correct-horse")
    response = _create_run(client, **{"x-monops-action-secret": "wrong"})
    assert response.status_code == 403


def test_action_secret_set_and_correct_allows_post_runs(client, monkeypatch):
    monkeypatch.setenv("MONOPS_ACTION_SECRET", "correct-horse")
    response = _create_run(client, **{"x-monops-action-secret": "correct-horse"})
    assert response.status_code == 200


def test_action_secret_gates_all_three_enrichment_routes(client, monkeypatch):
    # Create the run before the gate is armed, matching how a real deployment
    # would already have the demo run available while gating new actions.
    run_id = _create_run(client).json()["run_id"]
    monkeypatch.setenv("MONOPS_ACTION_SECRET", "correct-horse")

    ownership = client.post(
        f"/runs/{run_id}/ownership",
        json={"gleif_lei_file": GLEIF_LEI_FILE, "gleif_relationships_file": GLEIF_RELATIONSHIPS_FILE},
    )
    bibliometric = client.post(f"/runs/{run_id}/bibliometric", json={})
    topic_similarity = client.post(f"/runs/{run_id}/topic-similarity", json={})

    assert ownership.status_code == 403
    assert bibliometric.status_code == 403
    assert topic_similarity.status_code == 403

    ownership_ok = client.post(
        f"/runs/{run_id}/ownership",
        json={"gleif_lei_file": GLEIF_LEI_FILE, "gleif_relationships_file": GLEIF_RELATIONSHIPS_FILE},
        headers={"x-monops-action-secret": "correct-horse"},
    )
    assert ownership_ok.status_code == 200


# --- 2b: data-file allowlist -------------------------------------------------


def test_allowlist_unset_means_arbitrary_paths_still_work(client):
    response = _create_run(client)
    assert response.status_code == 200


def test_allowlist_set_rejects_a_path_outside_it(client, monkeypatch):
    monkeypatch.setenv("MONOPS_DATA_FILE_ALLOWLIST", os.pathsep.join([NSF_FILE, OPENSANCTIONS_FILE]))
    response = client.post(
        "/runs",
        json={"opensanctions_file": OUTSIDE_FILE, "nsf_file": NSF_FILE},
    )
    assert response.status_code == 400


def test_allowlist_set_accepts_a_path_inside_it(client, monkeypatch):
    monkeypatch.setenv("MONOPS_DATA_FILE_ALLOWLIST", os.pathsep.join([NSF_FILE, OPENSANCTIONS_FILE]))
    response = _create_run(client)
    assert response.status_code == 200


def test_allowlist_resolves_before_comparing_so_traversal_cannot_slip_past(client, monkeypatch):
    monkeypatch.setenv("MONOPS_DATA_FILE_ALLOWLIST", os.pathsep.join([NSF_FILE, OPENSANCTIONS_FILE]))
    traversal_path = str(FIXTURES_DIR / ".." / "fixtures" / "sample_dod_1260h.json")
    response = client.post(
        "/runs",
        json={"opensanctions_file": traversal_path, "nsf_file": NSF_FILE},
    )
    assert response.status_code == 400


def test_allowlist_gates_ownership_route_gleif_files(client, monkeypatch):
    run_id = _create_run(client).json()["run_id"]
    monkeypatch.setenv("MONOPS_DATA_FILE_ALLOWLIST", GLEIF_LEI_FILE)  # relationships file NOT allowlisted

    response = client.post(
        f"/runs/{run_id}/ownership",
        json={"gleif_lei_file": GLEIF_LEI_FILE, "gleif_relationships_file": GLEIF_RELATIONSHIPS_FILE},
    )

    assert response.status_code == 400


# --- B4-followup: a real GLEIF path for non-demo cases, via /cases/{id}/reconcile ---


def _create_case_with_a_declared_employer(client, case_id: str) -> None:
    resp = client.post(
        "/cases",
        json={
            "case_id": case_id,
            "subject_id": f"{case_id}-subject",
            "subject_display_name": "Test Subject",
            "coverage_basis": "151a1",
            "synthetic": True,
            "trigger": "hire",
            "access_scope": "data",
            "declaration_sources": [
                {"source_id": "cv", "kind": "cv", "present": True, "scope_kind": "full_history"},
            ],
            "declared_affiliations": [
                {
                    "affiliation_id": "aff-1",
                    "source_id": "cv",
                    "institution_name": "Fixture Subsidiary Corp",
                    "activity_kind": "employment",
                },
            ],
        },
    )
    assert resp.status_code == 200, resp.text


def test_reconcile_route_runs_real_ownership_screening_for_a_non_demo_case(client):
    """B4-followup: a caller-supplied, allowlisted GLEIF snapshot gives a
    non-demo case a real ownership-parent screening path -- mirrors Phase
    1's B4 test pattern, but through the route this time, not only at the
    pipeline layer. LEI-SUB's real ultimate parent (per the fixture) isn't
    on any concern list, so no tie is expected -- the assertion is that
    GLEIF was actually loaded and screened, not that a tie fires."""
    _create_case_with_a_declared_employer(client, "c-b4")

    response = client.post(
        "/cases/c-b4/reconcile",
        json={
            "gleif_lei_file": GLEIF_LEI_FILE,
            "gleif_relationships_file": GLEIF_RELATIONSHIPS_FILE,
        },
    )

    assert response.status_code == 200, response.text
    assert "gleif_ownership" in response.json()["discovery_sources"]


def test_allowlist_gates_reconcile_route_gleif_files(client, monkeypatch):
    _create_case_with_a_declared_employer(client, "c-b4-gated")
    monkeypatch.setenv("MONOPS_DATA_FILE_ALLOWLIST", GLEIF_LEI_FILE)  # relationships file NOT allowlisted

    response = client.post(
        "/cases/c-b4-gated/reconcile",
        json={
            "gleif_lei_file": GLEIF_LEI_FILE,
            "gleif_relationships_file": GLEIF_RELATIONSHIPS_FILE,
        },
    )

    assert response.status_code == 400


def _drive_demo_case_to_reconcile_eligible(client) -> None:
    """The only path back to a state `reconcile` is allowed in again once
    the demo case has self-healed into WORKSHEET: action every row, then
    ADJUDICATION -> OUTCOME -> CLOSED -> re-open to DISCOVERY (no direct
    edge from WORKSHEET/ADJUDICATION/OUTCOME back to DISCOVERY -- mirrors
    test_api_case.py's own _drive_demo_case_to_closed)."""
    body = client.get("/cases/demo/worksheet").json()
    for fid in [r["finding"]["finding_id"] for r in body["rows"]]:
        client.post(
            f"/cases/demo/findings/{fid}/action",
            json={"action": "dismiss", "reason_code": "record_error_or_misattribution",
                  "reason_note": "", "actor": "analyst.a"},
        )
    for tid in [r["tie"]["tie_id"] for r in body["tie_rows"]]:
        client.post(
            f"/cases/demo/ties/{tid}/action",
            json={"action": "dismiss", "reason_code": "historical_or_divested_relationship",
                  "reason_note": "", "actor": "analyst.a"},
        )
    assert client.post("/cases/demo/transition", json={"target_state": "adjudication"}).status_code == 200
    assert client.post(
        "/cases/demo/adjudication",
        json={"assessment": "Nothing material.", "recommendation": "Proceed.", "actor": "analyst.a"},
    ).status_code == 200
    assert client.post("/cases/demo/transition", json={"target_state": "outcome"}).status_code == 200
    assert client.post(
        "/cases/demo/outcome", json={"outcome": "cleared", "actor": "analyst.a", "note": ""},
    ).status_code == 200
    assert client.post("/cases/demo/transition", json={"target_state": "closed"}).status_code == 200
    assert client.post("/cases/demo/transition", json={"target_state": "discovery"}).status_code == 200


def test_reconcile_route_ignores_a_caller_supplied_gleif_path_for_the_demo_case(client):
    """Demo integrity can't be overridden by a caller -- the demo case
    always uses its own bundled, verified GLEIF fixture regardless of what
    a caller supplies."""
    _drive_demo_case_to_reconcile_eligible(client)

    response = client.post(
        "/cases/demo/reconcile",
        json={
            "gleif_lei_file": GLEIF_LEI_FILE,  # a different, non-demo GLEIF snapshot
            "gleif_relationships_file": GLEIF_RELATIONSHIPS_FILE,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "gleif_ownership" in body["discovery_sources"]
    assert body["tie_count"] == 1  # the demo's own real NIO INC. tie, unaffected

    worksheet = client.get("/cases/demo/worksheet").json()
    assert worksheet["tie_rows"][0]["tie"]["concern_entity_name"] == "NIO INC."


# --- S12: every mutating route is gated, proven structurally, not one at a time ---
#
# Individual tests above (and test_api_case.py) prove specific routes are
# gated. This walks the whole app once so a route added without
# Depends(require_action_secret)/_require_action_secret can never ship
# unnoticed -- the exact "built with no allowlist check, unnoticed until a
# UI called it" failure mode this project has already hit once
# (docs/plans/2026-09-14-restricted-party-screening-ui.md Section 2).
#
# `app.routes` on this FastAPI version doesn't hold flat APIRoute objects for
# an include_router()-mounted router -- it holds a lazy `_IncludedRouter`
# wrapper (FastAPI resolves the real, prefixed routes only when a request is
# actually dispatched or the OpenAPI schema is built). Walking the OpenAPI
# schema is the stable, public way to get the fully flattened, already-
# prefixed (method, path) list without reaching into that private structure;
# it's also strictly more black-box, which is the right level for a test
# that exists to catch "someone forgot the dependency," not to pin FastAPI's
# internals.

_MUTATING_METHODS = {"post", "put", "patch", "delete"}

# Every (method, path) pair that is allowed to be a mutating route with no
# action-secret gate. Empty today -- any future entry must be justified in
# the same commit that adds it, not inferred from what happens to pass.
_UNGATED_MUTATING_ROUTES: set[tuple[str, str]] = set()


def _mutating_operations() -> list[tuple[str, str]]:
    schema = TestClient(app).get("/openapi.json").json()
    return [
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        for method in operations
        if method in _MUTATING_METHODS
    ]


@pytest.mark.parametrize("method,path", _mutating_operations())
def test_every_mutating_route_is_gated(client, monkeypatch, method, path):
    if (method, path) in _UNGATED_MUTATING_ROUTES:
        pytest.skip(f"{(method, path)} is explicitly allowlisted as ungated")

    monkeypatch.setenv("MONOPS_ACTION_SECRET", "correct-horse")
    concrete_path = re.sub(r"\{[^}]+\}", "placeholder", path)
    response = client.request(method, concrete_path, json={})
    assert response.status_code == 403, (
        f"{method} {path} returned {response.status_code}, not 403, with no "
        "action-secret header -- either it's missing its gate, or it's "
        "rejecting the placeholder path/body before the gate runs (check "
        "manually with a real id)."
    )
