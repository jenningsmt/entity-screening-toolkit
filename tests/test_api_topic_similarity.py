import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from entity_screening.api.main import app
from entity_screening.bibliometric import embeddings, openalex_client

FIXTURES_DIR = Path(__file__).parent / "fixtures"
OPENSANCTIONS_FILE = str(FIXTURES_DIR / "sample_opensanctions_targets.csv")
DIM = embeddings.EMBEDDING_DIM


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
            {"response": {"award": [
                {"id": "1", "awardeeName": "Fixture State University", "piFirstName": "Jane", "piLastName": "Doe"},
            ]}}
        ),
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture(autouse=True)
def no_live_calls(monkeypatch):
    """Never hits the live OpenAlex API or loads the real (optional, not
    necessarily installed) embedding model -- monkeypatches the actual functions
    the pipeline calls by default, same principle as every other OpenAlex test."""
    def fake_http_get(url, params):
        if url.endswith("/institutions"):
            return {"results": [{"id": "https://openalex.org/I1", "display_name": "Fixture State University"}]}
        if url.endswith("/authors"):
            return {"results": [{"id": "https://openalex.org/A1", "orcid": None, "display_name": "Jane Doe"}]}
        return {"results": []}

    def fake_embed(text):
        return [0.0] * DIM

    monkeypatch.setattr(openalex_client, "_http_get", fake_http_get)
    monkeypatch.setattr(embeddings, "embed_query", fake_embed)
    monkeypatch.setattr(embeddings, "embed_passage", fake_embed)


def _create_run(client, nsf_file) -> str:
    response = client.post("/runs", json={"opensanctions_file": OPENSANCTIONS_FILE, "nsf_file": nsf_file})
    assert response.status_code == 200, response.text
    return response.json()["run_id"]


def test_topic_similarity_endpoint_requires_bibliometric_enrichment_first(client, nsf_file):
    run_id = _create_run(client, nsf_file)

    response = client.post(f"/runs/{run_id}/topic-similarity", json={})

    assert response.status_code == 409
    assert "enrich_bibliometric" in response.json()["detail"]


def test_topic_similarity_endpoint_returns_a_summary_after_bibliometric_enrichment(client, nsf_file):
    run_id = _create_run(client, nsf_file)
    client.post(f"/runs/{run_id}/bibliometric", json={})

    response = client.post(f"/runs/{run_id}/topic-similarity", json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["flags"] == []  # no institution resolved for the fixture entity, by design
    assert body["topic_similarity_snapshot"]["run_id"] == run_id
    assert body["topic_similarity_snapshot"]["embedding_model_revision"] == embeddings.MODEL_REVISION


def test_topic_similarity_endpoint_404s_for_an_unknown_run(client):
    response = client.post("/runs/does-not-exist/topic-similarity", json={})
    assert response.status_code == 404
