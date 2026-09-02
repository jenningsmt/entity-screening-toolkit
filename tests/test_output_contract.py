"""Cross-cutting regression: asserts the output *contract* at the outermost
artifacts an analyst or an API consumer actually sees -- the parsed CSV row
and the API's `/scores` JSON -- not the internal objects that build them.

Four of the nine findings in docs/2026-09-02-codebase-evaluation.md were
invisible to a 167-test suite because the suite tested the function that
implements a guarantee (e.g. matched_field being populated on ScreeningHit)
rather than the boundary that's supposed to deliver it (e.g. matched_field
actually reaching the CSV a reviewer opens). This file exists to prevent
that class of gap recurring -- for matched_field/producer (Finding 5),
attribution/license/caveat (Finding 6), and the "never confirmed" language
discipline (Section 10) all at once, not one regression test per instance.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from entity_screening.api.main import app
from entity_screening.common import storage
from entity_screening.common.attribution import OPENALEX_PRECISION_CAVEAT, attribution_for
from entity_screening.common.schema import ForeignControlFlag, MatchStatus, ScreeningHit

FIXTURES_DIR = Path(__file__).parent / "fixtures"
NSF_FILE = str(FIXTURES_DIR / "sample_nsf_awards.json")
OPENSANCTIONS_FILE = str(FIXTURES_DIR / "sample_opensanctions_targets.csv")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ENTITY_SCREENING_DB_PATH", str(tmp_path / "test.duckdb"))
    monkeypatch.setenv("ENTITY_SCREENING_RUNS_DIR", str(tmp_path / "runs"))
    return TestClient(app)


def _create_run(client) -> str:
    response = client.post("/runs", json={"opensanctions_file": OPENSANCTIONS_FILE, "nsf_file": NSF_FILE})
    assert response.status_code == 200, response.text
    return response.json()["run_id"]


def _hit(entity_id: str, list_name: str, producer: str, confidence: float = 0.95) -> ScreeningHit:
    """Builds evidence["source_attribution"] the same way the real producers
    do (screen.py/section_117.py/cross_check.py), rather than hand-typing
    fake attribution text, so this test exercises the real contract."""
    source_attribution = attribution_for(list_name)
    if producer == "bibliometric":
        source_attribution = {**source_attribution, "caveat": OPENALEX_PRECISION_CAVEAT}
    return ScreeningHit(
        entity_id=entity_id,
        list_name=list_name,
        matched_variant="Fixture Matched Variant",
        matched_field="name_variants",
        confidence=confidence,
        evidence={"entry_id": "fixture-entry-1", "source_attribution": source_attribution},
        status=MatchStatus.CANDIDATE_MATCH,
        producer=producer,
    )


def test_output_contract_at_the_csv_and_api_boundaries(client, tmp_path):
    run_id = _create_run(client)
    entity_id = client.get(f"/runs/{run_id}/scores").json()[0]["entity_id"]

    hits = [
        _hit(entity_id, "opensanctions_consolidated", "direct_name"),
        _hit(entity_id, "section_117_foreign_funding_disclosure", "section_117"),
        _hit(entity_id, "dod_section_1260h", "bibliometric"),
    ]
    flag = ForeignControlFlag(
        entity_id=entity_id,
        entity_lei="LEI-FIXTURE-1",
        entity_jurisdiction="US",
        ultimate_parent_lei="LEI-FIXTURE-2",
        ultimate_parent_name="Fixture Foreign Parent",
        ultimate_parent_jurisdiction="DE",
        relationship_path=("LEI-FIXTURE-1", "LEI-FIXTURE-2"),
        match_confidence=0.9,
        evidence={"lei_match_basis": "normalized_exact", "relationship_path": ["LEI-FIXTURE-1", "LEI-FIXTURE-2"], "truncated": False},
        status=MatchStatus.CANDIDATE_MATCH,
    )

    conn = storage.connect(tmp_path / "test.duckdb")
    storage.insert_screening_hits(conn, hits, run_id)
    storage.insert_ownership_flags(conn, [flag], run_id)
    conn.close()

    # ---- API boundary: GET /runs/{id}/scores ----
    scores = client.get(f"/runs/{run_id}/scores").json()
    entity = next(s for s in scores if s["entity_id"] == entity_id)
    assert entity["status"] == "candidate_match"
    assert len(entity["screening_hits"]) == 3
    _assert_hits_carry_the_full_contract(entity["screening_hits"])

    # ---- CSV boundary: GET /runs/{id}/export.csv ----
    csv_response = client.get(f"/runs/{run_id}/export.csv")
    assert csv_response.status_code == 200
    reader = csv.DictReader(io.StringIO(csv_response.text))
    row = next(r for r in reader if r["entity_id"] == entity_id)
    assert row["status"] == "candidate_match"
    csv_hits = json.loads(row["screening_hits"])
    assert len(csv_hits) == 3
    _assert_hits_carry_the_full_contract(csv_hits)

    # ---- Language discipline (Section 10): never "confirmed" anywhere ----
    assert "confirmed" not in csv_response.text.lower()
    assert "confirmed" not in json.dumps(scores).lower()

    # ---- status is candidate_match iff hits or ownership flags exist ----
    for s in scores:
        has_evidence = bool(s["screening_hits"]) or bool(s["ownership_flags"])
        assert s["status"] == ("candidate_match" if has_evidence else "no_hit")


def _assert_hits_carry_the_full_contract(hits: list[dict]) -> None:
    seen_producers = set()
    for hit in hits:
        assert hit["matched_field"], "matched_field must reach every hit output (Finding 5)"
        assert hit["producer"] in ("direct_name", "section_117", "bibliometric")
        assert hit["list_name"]
        assert hit["matched_variant"]
        assert isinstance(hit["confidence"], float)
        assert hit["status"]
        seen_producers.add(hit["producer"])

        source_attribution = hit["evidence"]["source_attribution"]
        assert source_attribution["attribution"], "attribution must reach every hit's evidence (Finding 6)"
        assert source_attribution["license"], "license must reach every hit's evidence (Section 10)"
        if hit["producer"] == "bibliometric":
            assert source_attribution.get("caveat"), (
                "every bibliometric hit's evidence must carry the OpenAlex precision caveat"
            )
        else:
            assert "caveat" not in source_attribution, (
                "only a bibliometric hit inherits OpenAlex's own uncertainty -- a direct_name "
                "or section_117 hit's attribution should not carry a caveat it didn't earn"
            )
    assert seen_producers == {"direct_name", "section_117", "bibliometric"}
