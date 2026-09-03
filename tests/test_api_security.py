"""Workstream 2's binding tests: the action-secret gate (2a) and the
data-file allowlist (2b). Both must default to "unchanged behavior" when
their env var is unset -- that's the correct trust boundary for a single
local user (dev, the CLI), and every other test in this suite relies on it
staying true.
"""
import os
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
