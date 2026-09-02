"""Cross-cutting regression: enrich_ownership, enrich_bibliometric, and
enrich_topic_similarity must each be safely re-runnable against the same
run_id -- "current state," not append-only. Findings 3 and 4 in
docs/2026-09-02-codebase-evaluation.md were each an instance of exactly one
step lacking this property (paper_embeddings had no delete-before-insert at
all; screening_hits was append-only for the bibliometric producer); this
file checks the property directly, for all three steps, so a future step
that doesn't get it right the first time is caught here rather than shipped.

For each step: run it twice against one run_id with fixed fakes and assert
(a) the returned results are equal, (b) row counts in every table the step
writes are identical after both calls, and (c) rows written by *other*
producers survive untouched.
"""
from __future__ import annotations

import json
from pathlib import Path

from entity_screening import pipeline
from entity_screening.bibliometric.topic_similarity import DOD_CORPUS_FILE, load_corpus
from entity_screening.common import storage
from entity_screening.scoring.rubric import STOCK_RUBRIC

FIXTURES_DIR = Path(__file__).parent / "fixtures"
OPENSANCTIONS_FILE = FIXTURES_DIR / "sample_opensanctions_targets.csv"
GLEIF_LEI_FILE = FIXTURES_DIR / "sample_gleif_lei.csv"
GLEIF_RELATIONSHIPS_FILE = FIXTURES_DIR / "sample_gleif_relationships.csv"

DIM = 384


def _vec(index: int) -> list[float]:
    v = [0.0] * DIM
    v[index] = 1.0
    return v


def _nsf_file(tmp_path, awards: list[dict]) -> Path:
    path = tmp_path / "nsf_awards.json"
    path.write_text(json.dumps({"response": {"award": awards}}), encoding="utf-8")
    return path


def _table_count(db_path, table: str, run_id: str) -> int:
    conn = storage.connect(db_path)
    try:
        return conn.execute(f"SELECT count(*) FROM {table} WHERE run_id = ?", [run_id]).fetchone()[0]
    finally:
        conn.close()


def test_enrich_ownership_is_idempotent_and_does_not_disturb_screening_hits(tmp_path):
    db_path = tmp_path / "test.duckdb"
    manifest, _ = pipeline.run_screening(
        nsf_file=_nsf_file(tmp_path, [{"id": "1", "awardeeName": "Fixture Subsidiary Corp"}]),
        nsf_date_start=None, nsf_date_end=None,
        opensanctions_file=OPENSANCTIONS_FILE, rubric=STOCK_RUBRIC, threshold=0.80,
        db_path=db_path, runs_dir=tmp_path,
    )
    screening_hits_before = _table_count(db_path, "screening_hits", manifest.run_id)

    _, flags_1 = pipeline.enrich_ownership(
        manifest.run_id, GLEIF_LEI_FILE, GLEIF_RELATIONSHIPS_FILE, db_path=db_path, runs_dir=tmp_path,
    )
    lei_matches_1 = _table_count(db_path, "lei_matches", manifest.run_id)
    ownership_flags_1 = _table_count(db_path, "ownership_flags", manifest.run_id)

    _, flags_2 = pipeline.enrich_ownership(
        manifest.run_id, GLEIF_LEI_FILE, GLEIF_RELATIONSHIPS_FILE, db_path=db_path, runs_dir=tmp_path,
    )
    lei_matches_2 = _table_count(db_path, "lei_matches", manifest.run_id)
    ownership_flags_2 = _table_count(db_path, "ownership_flags", manifest.run_id)

    assert flags_1 == flags_2
    assert lei_matches_1 == lei_matches_2 > 0
    assert ownership_flags_1 == ownership_flags_2 > 0
    # (c) a step this test didn't touch survives untouched.
    assert _table_count(db_path, "screening_hits", manifest.run_id) == screening_hits_before


def test_enrich_bibliometric_is_idempotent_and_does_not_disturb_ownership_flags(tmp_path):
    db_path = tmp_path / "test.duckdb"
    manifest, _ = pipeline.run_screening(
        nsf_file=_nsf_file(
            tmp_path,
            [
                {"id": "1", "awardeeName": "Fixture Subsidiary Corp"},
                {"id": "2", "awardeeName": "Montana State University", "piFirstName": "Andrew", "piLastName": "Felton"},
            ],
        ),
        nsf_date_start=None, nsf_date_end=None,
        opensanctions_file=OPENSANCTIONS_FILE, rubric=STOCK_RUBRIC, threshold=0.80,
        db_path=db_path, runs_dir=tmp_path,
    )
    pipeline.enrich_ownership(
        manifest.run_id, GLEIF_LEI_FILE, GLEIF_RELATIONSHIPS_FILE, db_path=db_path, runs_dir=tmp_path,
    )
    ownership_flags_before = _table_count(db_path, "ownership_flags", manifest.run_id)

    msu_institution = {
        "id": "https://openalex.org/I23732399",
        "display_name": "Montana State University",
        "country_code": "US",
    }
    concern_hit_work = {
        "results": [
            {
                "id": "https://openalex.org/W1",
                "title": "Fixture Paper",
                "publication_date": "2026-01-01",
                "authorships": [
                    {
                        "author": {"id": "https://openalex.org/A1", "display_name": "Andrew J. Felton"},
                        "institutions": [{"id": "https://openalex.org/I9", "display_name": "ZTE Corporation"}],
                    }
                ],
            }
        ]
    }

    def fake_fetch(url, params):
        if url.endswith("/institutions"):
            return {"results": [msu_institution]}
        if url.endswith("/authors"):
            return {"results": [{"id": "https://openalex.org/A1", "orcid": None, "display_name": "Andrew Felton"}]}
        return concern_hit_work

    _, hits_1 = pipeline.enrich_bibliometric(manifest.run_id, db_path=db_path, fetch=fake_fetch)
    screening_hits_1 = _table_count(db_path, "screening_hits", manifest.run_id)
    author_matches_1 = _table_count(db_path, "openalex_author_matches", manifest.run_id)

    _, hits_2 = pipeline.enrich_bibliometric(manifest.run_id, db_path=db_path, fetch=fake_fetch)
    screening_hits_2 = _table_count(db_path, "screening_hits", manifest.run_id)
    author_matches_2 = _table_count(db_path, "openalex_author_matches", manifest.run_id)

    assert len(hits_1) == len(hits_2) == 1
    assert screening_hits_1 == screening_hits_2
    assert author_matches_1 == author_matches_2 > 0
    # (c) a step this test didn't touch survives untouched.
    assert _table_count(db_path, "ownership_flags", manifest.run_id) == ownership_flags_before > 0


def test_enrich_topic_similarity_is_idempotent_and_does_not_disturb_bibliometric_hits(tmp_path):
    db_path = tmp_path / "test.duckdb"
    manifest, _ = pipeline.run_screening(
        nsf_file=_nsf_file(tmp_path, [{"id": "1", "awardeeName": "Fixture University", "piFirstName": "Jane", "piLastName": "Doe"}]),
        nsf_date_start=None, nsf_date_end=None,
        opensanctions_file=OPENSANCTIONS_FILE, rubric=STOCK_RUBRIC, threshold=0.80,
        db_path=db_path, runs_dir=tmp_path,
    )

    target_text = load_corpus(DOD_CORPUS_FILE)[0]["text"]
    work = {
        "id": "https://openalex.org/W1",
        "title": "Fixture Paper",
        "abstract_inverted_index": {"word": [0]},
    }

    def bib_fake_fetch(url, params):
        if url.endswith("/institutions"):
            return {"results": [{"id": "https://openalex.org/I1", "display_name": "Fixture University"}]}
        if url.endswith("/authors"):
            return {"results": [{"id": "https://openalex.org/A1", "orcid": None, "display_name": "Jane Doe"}]}
        if url.endswith("/works"):
            return {"results": [work]}
        return {"results": []}

    # Workstream 9b: enrich_bibliometric is the only place a work is ever
    # fetched now -- enrich_topic_similarity reads the same persisted copy
    # back from raw_openalex_works rather than fetching again.
    pipeline.enrich_bibliometric(manifest.run_id, db_path=db_path, fetch=bib_fake_fetch)
    bibliometric_hits_before = _table_count(db_path, "screening_hits", manifest.run_id)
    author_matches_before = _table_count(db_path, "openalex_author_matches", manifest.run_id)

    def fake_embed_passage(text):
        return _vec(0)

    def fake_embed_query(text):
        return _vec(0) if text == target_text else _vec(1)

    _, flags_1 = pipeline.enrich_topic_similarity(
        manifest.run_id, db_path=db_path,
        embed_query_fn=fake_embed_query, embed_passage_fn=fake_embed_passage,
    )
    embeddings_1 = _table_count(db_path, "paper_embeddings", manifest.run_id)
    topic_flags_1 = _table_count(db_path, "topic_similarity_flags", manifest.run_id)

    _, flags_2 = pipeline.enrich_topic_similarity(
        manifest.run_id, db_path=db_path,
        embed_query_fn=fake_embed_query, embed_passage_fn=fake_embed_passage,
    )
    embeddings_2 = _table_count(db_path, "paper_embeddings", manifest.run_id)
    topic_flags_2 = _table_count(db_path, "topic_similarity_flags", manifest.run_id)

    assert flags_1
    assert flags_1 == flags_2
    assert embeddings_1 == embeddings_2 > 0
    assert topic_flags_1 == topic_flags_2 > 0
    # (c) a step this test didn't touch survives untouched. (This fixture's
    # bibliometric enrichment produces an author match but no concern-list
    # hit -- openalex_author_matches is what actually proves survival here.)
    assert _table_count(db_path, "screening_hits", manifest.run_id) == bibliometric_hits_before
    assert _table_count(db_path, "openalex_author_matches", manifest.run_id) == author_matches_before > 0
