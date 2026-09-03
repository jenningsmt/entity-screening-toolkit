"""Tests the self-healing, screening-only public-demo run (the re-scoped
Workstream 8b -- see docs/plans/2026-09-02-remediation-pass.md's Status
header for why it's screening-only rather than the originally-planned
enrichment-inclusive run: Workstream 8a already means a screening-only run
shows a real, non-blank, explained table on load, which is what actually
unblocks gating run-creation behind the action secret (Workstream 2))."""
import pytest
from fastapi.testclient import TestClient

from entity_screening.api.main import DEMO_RUN_ID, app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ENTITY_SCREENING_DB_PATH", str(tmp_path / "test.duckdb"))
    monkeypatch.setenv("ENTITY_SCREENING_RUNS_DIR", str(tmp_path / "runs"))
    return TestClient(app)


def test_demo_run_self_heals_on_first_manifest_request(client):
    response = client.get(f"/runs/{DEMO_RUN_ID}/manifest")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == DEMO_RUN_ID
    assert {s["source_dataset"] for s in body["dataset_snapshots"]} == {
        "nsf_award_search",
        "opensanctions_targets_simple",
        "dod_section_1260h",
    }


def test_demo_run_is_idempotent_not_rebuilt_on_second_request(client):
    first = client.get(f"/runs/{DEMO_RUN_ID}/manifest").json()
    second = client.get(f"/runs/{DEMO_RUN_ID}/manifest").json()

    assert first["started_at"] == second["started_at"]


def test_demo_run_self_heals_via_the_scores_route_directly(client):
    """Every run-scoped route calls _load_manifest first (its own 404 guard),
    so self-healing isn't specific to the /manifest route -- confirm a
    caller that never hits /manifest at all still gets a working demo."""
    response = client.get(f"/runs/{DEMO_RUN_ID}/scores")

    assert response.status_code == 200
    scores = response.json()
    assert len(scores) > 0


def test_demo_run_scores_show_real_screened_entities_with_no_direct_hits(client):
    """Documents the actual, verified shape of the baked-in demo result --
    real NSF awardees screened against a real OpenSanctions subset, zero
    direct hits (the structural NSF-only-funds-US-recipients finding, not a
    fixture artifact -- see app.py's info panel for the full explanation)."""
    scores = client.get(f"/runs/{DEMO_RUN_ID}/scores").json()

    assert len(scores) == 53
    assert all(s["status"] == "no_hit" for s in scores)
