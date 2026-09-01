import json
from pathlib import Path

from entity_screening import pipeline
from entity_screening.common import storage
from entity_screening.scoring.rubric import STOCK_RUBRIC

FIXTURES_DIR = Path(__file__).parent / "fixtures"
OPENSANCTIONS_FILE = FIXTURES_DIR / "sample_opensanctions_targets.csv"

MSU_INSTITUTION = {
    "id": "https://openalex.org/I23732399",
    "display_name": "Montana State University",
    "country_code": "US",
    "display_name_acronyms": ["MSU"],
    "display_name_alternatives": [],
}


def _nsf_file(tmp_path, awards):
    path = tmp_path / "nsf_awards.json"
    path.write_text(json.dumps({"response": {"award": awards}}), encoding="utf-8")
    return path


def _run(tmp_path, awards, db_path):
    return pipeline.run_screening(
        nsf_file=_nsf_file(tmp_path, awards),
        nsf_date_start=None,
        nsf_date_end=None,
        opensanctions_file=OPENSANCTIONS_FILE,
        rubric=STOCK_RUBRIC,
        threshold=0.80,
        db_path=db_path,
    )


def _fake_fetch_factory(institution_payload, works_payload, call_log, *, author_id_prefix="A"):
    """Author search responses are built dynamically from the request so the
    returned candidate's display_name actually matches whichever PI was searched
    (score_pair needs a real name match to produce a ResolvedAuthor candidate at
    all) -- distinct PIs get distinct, stable synthetic author IDs."""

    def fake_fetch(url, params):
        call_log.append((url, params))
        if url.endswith("/institutions"):
            return institution_payload
        if url.endswith("/authors"):
            query = params["filter"].split("display_name.search:")[1].split(",")[0]
            author_id = f"https://openalex.org/{author_id_prefix}-{query.replace(' ', '_')}"
            return {
                "results": [{"id": author_id, "orcid": None, "display_name": query}]
            }
        return works_payload

    return fake_fetch


def test_enrich_bibliometric_deduplicates_spelling_variant_entities_sharing_one_institution(tmp_path):
    """Resolved-during-review binding criterion: two NSF awardee spellings that
    resolve to the same OpenAlex institution ID must trigger exactly one
    author-resolution/cross-check pass, not one per entity."""
    db_path = tmp_path / "test.duckdb"
    manifest, scored_entities = _run(
        tmp_path,
        [
            {"id": "1", "awardeeName": "Montana State University", "piFirstName": "Andrew", "piLastName": "Felton"},
            {"id": "2", "awardeeName": "Montana State University-Bozeman", "piFirstName": "Jane", "piLastName": "Doe"},
        ],
        db_path,
    )
    assert len(scored_entities) == 2  # confirms Epic B's exact-match grouping really did split these

    call_log = []
    fake_fetch = _fake_fetch_factory({"results": [MSU_INSTITUTION]}, {"results": []}, call_log)

    bib_manifest, hits = pipeline.enrich_bibliometric(manifest.run_id, db_path=db_path, fetch=fake_fetch)

    author_search_calls = [c for c in call_log if c[0].endswith("/authors")]
    works_calls = [c for c in call_log if c[0].endswith("/works")]
    # Institution resolution still runs once per entity (2 calls)...
    institution_calls = [c for c in call_log if c[0].endswith("/institutions")]
    assert len(institution_calls) == 2
    # ...but author-resolution/works-fetching for the pooled PI set runs once per
    # distinct PI per institution, not once per (entity, PI) pair: 2 distinct PIs
    # (Andrew Felton, Jane Doe) pooled under the one shared institution -> 2 author
    # searches and 2 works fetches total, not 4.
    assert len(author_search_calls) == 2
    assert len(works_calls) == 2

    conn = storage.connect(db_path)
    matches = storage.load_openalex_author_matches(conn, manifest.run_id)
    conn.close()
    # Both entities share the same institution -> both get the pooled result
    # stamped onto them (2 PIs x 2 entities = 4 rows).
    assert len(matches) == 4
    assert {m.entity_id for m in matches} == {s.entity_id for s in scored_entities}


def test_enrich_bibliometric_does_not_touch_scored_entities(tmp_path):
    db_path = tmp_path / "test.duckdb"
    manifest, _ = _run(
        tmp_path,
        [{"id": "1", "awardeeName": "Fixture University", "piFirstName": "Jane", "piLastName": "Doe"}],
        db_path,
    )

    conn = storage.connect(db_path)
    before = conn.execute("SELECT count(*) FROM scored_entities").fetchone()[0]
    conn.close()

    call_log = []
    fake_fetch = _fake_fetch_factory({"results": []}, {"results": []}, call_log)
    pipeline.enrich_bibliometric(manifest.run_id, db_path=db_path, fetch=fake_fetch)

    conn = storage.connect(db_path)
    after = conn.execute("SELECT count(*) FROM scored_entities").fetchone()[0]
    conn.close()
    assert after == before


def test_enrich_bibliometric_writes_a_manifest_and_hits_score_via_existing_rubric(tmp_path):
    db_path = tmp_path / "test.duckdb"
    manifest, _ = _run(
        tmp_path,
        [{"id": "1", "awardeeName": "Montana State University", "piFirstName": "Andrew", "piLastName": "Felton"}],
        db_path,
    )

    expected_author_id = "https://openalex.org/A-Andrew_Felton"
    concern_hit_work = {
        "results": [
            {
                "id": "https://openalex.org/W1",
                "title": "Fixture Paper",
                "publication_date": "2026-01-01",
                "authorships": [
                    {
                        "author": {"id": expected_author_id, "display_name": "Andrew J. Felton"},
                        "institutions": [{"id": "https://openalex.org/I9", "display_name": "ZTE Corporation"}],
                    }
                ],
            }
        ]
    }
    call_log = []
    fake_fetch = _fake_fetch_factory({"results": [MSU_INSTITUTION]}, concern_hit_work, call_log)

    bib_manifest, hits = pipeline.enrich_bibliometric(manifest.run_id, db_path=db_path, fetch=fake_fetch)

    assert bib_manifest.run_id == manifest.run_id
    assert bib_manifest.resolved_author_count == 1
    assert len(hits) == 1
    assert hits[0].list_name == "opensanctions_consolidated"
    assert hits[0].evidence["author_resolution"]["openalex_author_id"] == expected_author_id

    rescored = pipeline.rescore_run(manifest.run_id, STOCK_RUBRIC, db_path=db_path)
    scored = next(s for s in rescored if s.entity_id == hits[0].entity_id)
    assert scored.score.factors["screening_hit"] == (
        STOCK_RUBRIC.screening_hit_weight
        * (hits[0].confidence * STOCK_RUBRIC.screening_hit_confidence_multiplier)
    )
