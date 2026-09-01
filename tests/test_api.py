from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from entity_screening.api.main import app

FIXTURES_DIR = Path(__file__).parent / "fixtures"
NSF_FILE = str(FIXTURES_DIR / "sample_nsf_awards.json")
OPENSANCTIONS_FILE = str(FIXTURES_DIR / "sample_opensanctions_targets.csv")


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Isolates each test's DB and manifest/export output under tmp_path so
    API tests never touch the real data/processed/ directory or interfere
    with each other."""
    monkeypatch.setenv("ENTITY_SCREENING_DB_PATH", str(tmp_path / "test.duckdb"))
    monkeypatch.setenv("ENTITY_SCREENING_RUNS_DIR", str(tmp_path / "runs"))
    return TestClient(app)


def _create_run(client) -> str:
    response = client.post(
        "/runs",
        json={"opensanctions_file": OPENSANCTIONS_FILE, "nsf_file": NSF_FILE},
    )
    assert response.status_code == 200, response.text
    return response.json()["run_id"]


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_rubric_default(client):
    body = client.get("/rubric/default").json()
    assert "screening_hit_weight" in body


def test_create_run_returns_summary(client):
    response = client.post(
        "/runs",
        json={"opensanctions_file": OPENSANCTIONS_FILE, "nsf_file": NSF_FILE},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["entities_count"] == 2
    assert body["hits_count"] == 1
    assert body["ingestion_error_count"] == 2


def test_unknown_run_id_404s(client):
    assert client.get("/runs/does-not-exist/manifest").status_code == 404
    assert client.get("/runs/does-not-exist/scores").status_code == 404


def test_get_run_manifest_reflects_the_run(client):
    run_id = _create_run(client)
    body = client.get(f"/runs/{run_id}/manifest").json()
    assert body["run_id"] == run_id
    assert len(body["dataset_snapshots"]) == 2


def test_scores_endpoint_never_writes_to_the_database(client, tmp_path):
    from entity_screening.common import storage

    run_id = _create_run(client)
    db_path = tmp_path / "test.duckdb"

    conn = storage.connect(db_path)
    before = conn.execute("SELECT count(*) FROM scored_entities").fetchone()[0]
    conn.close()

    for _ in range(3):
        response = client.get(f"/runs/{run_id}/scores", params={"screening_hit_weight": 500})
        assert response.status_code == 200

    conn = storage.connect(db_path)
    after = conn.execute("SELECT count(*) FROM scored_entities").fetchone()[0]
    conn.close()

    assert after == before


def test_scores_endpoint_reflects_rubric_override(client):
    run_id = _create_run(client)

    default_scores = client.get(f"/runs/{run_id}/scores").json()
    boosted_scores = client.get(
        f"/runs/{run_id}/scores", params={"screening_hit_weight": 5000}
    ).json()

    default_by_id = {s["entity_id"]: s for s in default_scores}
    boosted_by_id = {s["entity_id"]: s for s in boosted_scores}
    hit_ids = [eid for eid, s in default_by_id.items() if s["screening_hits"]]

    assert hit_ids
    for entity_id in hit_ids:
        assert boosted_by_id[entity_id]["total_score"] > default_by_id[entity_id]["total_score"]


def test_export_csv_returns_a_file_with_export_id_header(client):
    run_id = _create_run(client)
    response = client.get(f"/runs/{run_id}/export.csv")
    assert response.status_code == 200
    assert "X-Export-Id" in response.headers
    assert "export_id" in response.text.splitlines()[0]


def test_two_exports_under_different_rubrics_get_distinct_export_ids(client):
    run_id = _create_run(client)

    response_a = client.get(f"/runs/{run_id}/export.csv")
    response_b = client.get(f"/runs/{run_id}/export.csv", params={"screening_hit_weight": 5000})

    export_id_a = response_a.headers["X-Export-Id"]
    export_id_b = response_b.headers["X-Export-Id"]
    assert export_id_a != export_id_b

    rows_a = response_a.text.splitlines()
    rows_b = response_b.text.splitlines()
    assert export_id_a in rows_a[1]
    assert export_id_b in rows_b[1]
