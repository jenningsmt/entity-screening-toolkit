import json
from pathlib import Path

import pytest

from entity_screening import pipeline
from entity_screening.common import storage
from entity_screening.scoring.rubric import STOCK_RUBRIC

FIXTURES_DIR = Path(__file__).parent / "fixtures"
OPENSANCTIONS_FILE = FIXTURES_DIR / "sample_opensanctions_targets.csv"

DIM = 384


def _vec(index: int) -> list[float]:
    v = [0.0] * DIM
    v[index] = 1.0
    return v


def _nsf_file(tmp_path):
    path = tmp_path / "nsf_awards.json"
    path.write_text(
        json.dumps({"response": {"award": [
            {"id": "1", "awardeeName": "Fixture University", "piFirstName": "Jane", "piLastName": "Doe"},
        ]}}),
        encoding="utf-8",
    )
    return path


def _run_and_enrich_bibliometric(tmp_path):
    db_path = tmp_path / "test.duckdb"
    manifest, _ = pipeline.run_screening(
        nsf_file=_nsf_file(tmp_path), nsf_date_start=None, nsf_date_end=None,
        opensanctions_file=OPENSANCTIONS_FILE, rubric=STOCK_RUBRIC, threshold=0.80,
        db_path=db_path,
    )

    def fake_fetch(url, params):
        if url.endswith("/institutions"):
            return {"results": [{"id": "https://openalex.org/I1", "display_name": "Fixture University"}]}
        if url.endswith("/authors"):
            return {"results": [{"id": "https://openalex.org/A1", "orcid": None, "display_name": "Jane Doe"}]}
        return {"results": []}

    pipeline.enrich_bibliometric(manifest.run_id, db_path=db_path, fetch=fake_fetch)
    return manifest, db_path


def test_enrich_topic_similarity_requires_bibliometric_enrichment_first(tmp_path):
    db_path = tmp_path / "test.duckdb"
    manifest, _ = pipeline.run_screening(
        nsf_file=_nsf_file(tmp_path), nsf_date_start=None, nsf_date_end=None,
        opensanctions_file=OPENSANCTIONS_FILE, rubric=STOCK_RUBRIC, threshold=0.80,
        db_path=db_path,
    )

    with pytest.raises(ValueError, match="enrich_bibliometric"):
        pipeline.enrich_topic_similarity(manifest.run_id, db_path=db_path)


def test_enrich_topic_similarity_never_touches_scored_entities_or_screening_hits(tmp_path):
    manifest, db_path = _run_and_enrich_bibliometric(tmp_path)

    conn = storage.connect(db_path)
    scored_before = conn.execute("SELECT count(*) FROM scored_entities").fetchone()[0]
    hits_before = conn.execute("SELECT count(*) FROM screening_hits").fetchone()[0]
    conn.close()

    def fake_fetch(url, params):
        return {"results": []}

    pipeline.enrich_topic_similarity(
        manifest.run_id, db_path=db_path, fetch=fake_fetch,
        embed_query_fn=lambda t: _vec(0), embed_passage_fn=lambda t: _vec(0),
    )

    conn = storage.connect(db_path)
    scored_after = conn.execute("SELECT count(*) FROM scored_entities").fetchone()[0]
    hits_after = conn.execute("SELECT count(*) FROM screening_hits").fetchone()[0]
    conn.close()

    assert scored_after == scored_before
    assert hits_after == hits_before


def test_enrich_topic_similarity_writes_manifest_with_pinned_model_revision(tmp_path):
    manifest, db_path = _run_and_enrich_bibliometric(tmp_path)

    def fake_fetch(url, params):
        return {"results": []}

    topic_manifest, flags = pipeline.enrich_topic_similarity(
        manifest.run_id, db_path=db_path, fetch=fake_fetch,
        embed_query_fn=lambda t: _vec(0), embed_passage_fn=lambda t: _vec(0),
    )

    assert topic_manifest.run_id == manifest.run_id
    assert topic_manifest.embedding_model == "BAAI/bge-small-en-v1.5"
    assert topic_manifest.embedding_model_revision == "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
    assert topic_manifest.flags_count == len(flags)
