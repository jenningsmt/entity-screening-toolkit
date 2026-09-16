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
