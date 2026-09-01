import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from entity_screening.api.main import app
from entity_screening.bibliometric import openalex_client

FIXTURES_DIR = Path(__file__).parent / "fixtures"
OPENSANCTIONS_FILE = str(FIXTURES_DIR / "sample_opensanctions_targets.csv")


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
            {
                "response": {
                    "award": [
                        {
                            "id": "1",
                            "awardeeName": "Fixture State University",
                            "piFirstName": "Jane",
                            "piLastName": "Doe",
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture(autouse=True)
def no_live_openalex_calls(monkeypatch):
    """The API route can't accept an injectable fetch over HTTP -- monkeypatch the
    client's actual default HTTP function instead, so this test suite never hits
    the live network (same principle as every other OpenAlex test)."""
    def fake_http_get(url, params):
        return {"results": []}

    monkeypatch.setattr(openalex_client, "_http_get", fake_http_get)


def _create_run(client, nsf_file) -> str:
    response = client.post("/runs", json={"opensanctions_file": OPENSANCTIONS_FILE, "nsf_file": nsf_file})
    assert response.status_code == 200, response.text
    return response.json()["run_id"]


def test_enrich_bibliometric_endpoint_returns_a_summary(client, nsf_file):
    run_id = _create_run(client, nsf_file)

    response = client.post(f"/runs/{run_id}/bibliometric", json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["hits_count"] == 0  # no institution found for a fixture entity, by design
    assert body["bibliometric_snapshot"]["run_id"] == run_id
    assert body["bibliometric_snapshot"]["openalex_api_base_url"] == openalex_client.API_BASE_URL


def test_enrich_bibliometric_endpoint_404s_for_an_unknown_run(client):
    response = client.post("/runs/does-not-exist/bibliometric", json={})
    assert response.status_code == 404
