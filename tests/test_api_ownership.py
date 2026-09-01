import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from entity_screening.api.main import app

FIXTURES_DIR = Path(__file__).parent / "fixtures"
OPENSANCTIONS_FILE = str(FIXTURES_DIR / "sample_opensanctions_targets.csv")
GLEIF_LEI_FILE = str(FIXTURES_DIR / "sample_gleif_lei.csv")
GLEIF_RELATIONSHIPS_FILE = str(FIXTURES_DIR / "sample_gleif_relationships.csv")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ENTITY_SCREENING_DB_PATH", str(tmp_path / "test.duckdb"))
    monkeypatch.setenv("ENTITY_SCREENING_RUNS_DIR", str(tmp_path / "runs"))
    return TestClient(app)


@pytest.fixture
def nsf_file(tmp_path) -> str:
    path = tmp_path / "nsf_awards.json"
    path.write_text(
        json.dumps(
            {"response": {"award": [{"id": "1", "awardeeName": "Fixture Subsidiary Corp"}]}}
        ),
        encoding="utf-8",
    )
    return str(path)


def _create_run(client, nsf_file) -> str:
    response = client.post("/runs", json={"opensanctions_file": OPENSANCTIONS_FILE, "nsf_file": nsf_file})
    assert response.status_code == 200, response.text
    return response.json()["run_id"]


def test_enrich_ownership_endpoint_returns_a_summary(client, nsf_file):
    run_id = _create_run(client, nsf_file)

    response = client.post(
        f"/runs/{run_id}/ownership",
        json={"gleif_lei_file": GLEIF_LEI_FILE, "gleif_relationships_file": GLEIF_RELATIONSHIPS_FILE},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["flags_count"] == 1
    assert body["gleif_snapshot"]["lei_record_count"] == 19
    assert body["gleif_snapshot"]["run_id"] == run_id


def test_scores_reflect_ownership_flag_after_enrichment(client, nsf_file):
    run_id = _create_run(client, nsf_file)
    client.post(
        f"/runs/{run_id}/ownership",
        json={"gleif_lei_file": GLEIF_LEI_FILE, "gleif_relationships_file": GLEIF_RELATIONSHIPS_FILE},
    )

    scores = client.get(f"/runs/{run_id}/scores").json()

    assert len(scores) == 1
    entity = scores[0]
    assert entity["status"] == "candidate_match"
    assert entity["ownership_flags"][0]["ultimate_parent_jurisdiction"] == "DE"
    assert "foreign_control" in entity["factors"]


def test_scores_endpoint_accepts_a_foreign_control_weight_override(client, nsf_file):
    run_id = _create_run(client, nsf_file)
    client.post(
        f"/runs/{run_id}/ownership",
        json={"gleif_lei_file": GLEIF_LEI_FILE, "gleif_relationships_file": GLEIF_RELATIONSHIPS_FILE},
    )

    baseline = client.get(f"/runs/{run_id}/scores").json()[0]["total_score"]
    boosted = client.get(
        f"/runs/{run_id}/scores", params={"foreign_control_weight": 5000}
    ).json()[0]["total_score"]

    assert boosted > baseline


def test_ownership_chain_endpoint_returns_a_queryable_path(client, nsf_file):
    run_id = _create_run(client, nsf_file)
    client.post(
        f"/runs/{run_id}/ownership",
        json={"gleif_lei_file": GLEIF_LEI_FILE, "gleif_relationships_file": GLEIF_RELATIONSHIPS_FILE},
    )
    entity_id = client.get(f"/runs/{run_id}/scores").json()[0]["entity_id"]

    response = client.get(f"/runs/{run_id}/ownership/{entity_id}", params={"direction": "up", "depth": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["chain"] == ["LEI-DIRECT-PARENT", "LEI-ULTIMATE-DE"]
    assert body["truncated"] is False


def test_ownership_chain_endpoint_404s_for_an_entity_never_resolved(client, nsf_file):
    run_id = _create_run(client, nsf_file)
    # No POST .../ownership call at all -- no lei_matches row exists yet.
    entity_id = client.get(f"/runs/{run_id}/scores").json()[0]["entity_id"]

    response = client.get(f"/runs/{run_id}/ownership/{entity_id}")

    assert response.status_code == 404


def test_enrich_ownership_endpoint_404s_for_an_unknown_run(client):
    response = client.post(
        "/runs/does-not-exist/ownership",
        json={"gleif_lei_file": GLEIF_LEI_FILE, "gleif_relationships_file": GLEIF_RELATIONSHIPS_FILE},
    )
    assert response.status_code == 404
