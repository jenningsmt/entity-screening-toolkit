import datetime
import uuid

from entity_screening.bibliometric.topic_similarity import (
    CET_CORPUS_FILE,
    DOD_CORPUS_FILE,
    compute_topic_similarity_flags,
    load_corpus,
    reconstruct_abstract,
)
from entity_screening.common import storage
from entity_screening.common.schema import MatchStatus, ResolvedAuthor

DIM = 384


def _vec(*weighted_indices: tuple[int, float]) -> list[float]:
    """Builds a 384-dim vector with the given (index, weight) pairs set, all
    others zero -- lets tests construct known cosine similarities precisely."""
    v = [0.0] * DIM
    for i, w in weighted_indices:
        v[i] = w
    return v


def _resolved_author(entity_id="e1", author_id="A1", pi_name="Jane Doe") -> ResolvedAuthor:
    return ResolvedAuthor(
        entity_id=entity_id, pi_name=pi_name, openalex_author_id=author_id,
        display_name=pi_name, confidence=1.0, match_basis="normalized_exact",
        evidence={"tied_candidate_count": 1, "shared_orcid_with": []},
        status=MatchStatus.CANDIDATE_MATCH,
    )


def test_reconstruct_abstract_from_real_shaped_inverted_index():
    aii = {"Abstract": [0], "Climate": [1], "change": [2], "is": [3], "real": [4]}
    assert reconstruct_abstract(aii) == "Abstract Climate change is real"


def test_reconstruct_abstract_returns_none_for_missing_abstract():
    assert reconstruct_abstract(None) is None
    assert reconstruct_abstract({}) is None


def test_load_corpus_reads_the_real_bundled_dod_file():
    corpus = load_corpus(DOD_CORPUS_FILE)
    assert len(corpus) == 6
    assert all(entry["tier"] == "primary" for entry in corpus)
    names = {entry["name"] for entry in corpus}
    assert "Scaled Hypersonics" in names
    hypersonics = next(e for e in corpus if e["name"] == "Scaled Hypersonics")
    assert "hypersonic" in hypersonics["text"].lower()


def test_load_corpus_reads_the_real_bundled_cet_file_and_concatenates_subfields():
    corpus = load_corpus(CET_CORPUS_FILE)
    assert len(corpus) == 18
    assert all(entry["tier"] == "secondary" for entry in corpus)
    ai_entry = next(e for e in corpus if e["name"] == "Artificial Intelligence")
    assert "Foundation models" in ai_entry["text"]
    assert "Machine learning" in ai_entry["text"]


def test_compute_topic_similarity_flags_fires_when_margin_is_cleared(tmp_path):
    conn = storage.connect(tmp_path / "test.duckdb")
    resolved_author = _resolved_author()

    work = {
        "id": "https://openalex.org/W1",
        "title": "Fixture Paper",
        "abstract_inverted_index": {"word": [0]},
    }

    def fake_fetch(url, params):
        return {"results": [work]}

    # Paper embedding points mostly at dim 0; "Area A" points exactly at dim 0
    # (similarity 1.0), "Area B" points at dim 1 (similarity 0.0) -- a clean margin.
    dod_corpus = [
        {"id": "a", "name": "Area A", "text": "area a", "tier": "primary"},
        {"id": "b", "name": "Area B", "text": "area b", "tier": "primary"},
    ]

    def fake_embed_passage(text):
        return _vec((0, 1.0))

    def fake_embed_query(text):
        return _vec((0, 1.0)) if text == "area a" else _vec((1, 1.0))

    flags = compute_topic_similarity_flags(
        conn, "run-1", "e1", [resolved_author], dod_corpus, [],
        margin=0.10, fetch=fake_fetch,
        embed_query_fn=fake_embed_query, embed_passage_fn=fake_embed_passage,
    )
    conn.close()

    assert len(flags) == 1
    flag = flags[0]
    assert flag.technology_area == "Area A"
    assert flag.corpus_tier == "primary"
    assert flag.similarity_score == 1.0
    assert flag.evidence["runner_up_area"] == "Area B"
    assert flag.evidence["margin"] == 1.0
    assert "consult a subject-matter expert" in flag.recommendation.lower()


def test_compute_topic_similarity_flags_does_not_fire_when_margin_too_small(tmp_path):
    conn = storage.connect(tmp_path / "test.duckdb")
    resolved_author = _resolved_author()
    work = {"id": "https://openalex.org/W1", "title": "Fixture", "abstract_inverted_index": {"w": [0]}}

    def fake_fetch(url, params):
        return {"results": [work]}

    # Two near-identical corpus vectors -- top and runner-up are almost tied.
    dod_corpus = [
        {"id": "a", "name": "Area A", "text": "a", "tier": "primary"},
        {"id": "b", "name": "Area B", "text": "b", "tier": "primary"},
    ]

    def fake_embed_passage(text):
        return _vec((0, 1.0))

    def fake_embed_query(text):
        return _vec((0, 1.0)) if text == "a" else _vec((0, 0.95), (1, 0.05))

    flags = compute_topic_similarity_flags(
        conn, "run-1", "e1", [resolved_author], dod_corpus, [],
        margin=0.10, fetch=fake_fetch,
        embed_query_fn=fake_embed_query, embed_passage_fn=fake_embed_passage,
    )
    conn.close()

    assert flags == []


def test_corpora_are_ranked_independently_not_pooled(tmp_path):
    """Resolved-during-review binding criterion: construct a case where a CET
    (secondary) entry would out-rank the correct DoD (primary) entry under a
    pooled comparison -- the DoD-side flag must still fire on its own within-DoD
    margin regardless, proving pooling never actually happens."""
    conn = storage.connect(tmp_path / "test.duckdb")
    resolved_author = _resolved_author()
    work = {"id": "https://openalex.org/W1", "title": "Fixture", "abstract_inverted_index": {"w": [0]}}

    def fake_fetch(url, params):
        return {"results": [work]}

    dod_corpus = [
        {"id": "dod_correct", "name": "DoD Correct Match", "text": "dod_correct", "tier": "primary"},
        {"id": "dod_other", "name": "DoD Other", "text": "dod_other", "tier": "primary"},
    ]
    cet_corpus = [
        {"id": "cet_high", "name": "CET High Scorer", "text": "cet_high", "tier": "secondary"},
        {"id": "cet_low", "name": "CET Low", "text": "cet_low", "tier": "secondary"},
    ]

    def fake_embed_passage(text):
        return _vec((0, 1.0))

    # The paper matches "dod_correct" at 0.9 (a real, clear within-DoD margin over
    # "dod_other" at 0.3) -- but "cet_high" is engineered to score 0.99, which
    # WOULD outrank "dod_correct" if all 4 entries were pooled into one ranking.
    def fake_embed_query(text):
        vectors = {
            "dod_correct": _vec((0, 0.9), (2, 0.436)),
            "dod_other": _vec((0, 0.3), (2, 0.954)),
            "cet_high": _vec((0, 0.99), (2, 0.141)),
            "cet_low": _vec((1, 1.0)),
        }
        return vectors[text]

    flags = compute_topic_similarity_flags(
        conn, "run-1", "e1", [resolved_author], dod_corpus, cet_corpus,
        margin=0.10, fetch=fake_fetch,
        embed_query_fn=fake_embed_query, embed_passage_fn=fake_embed_passage,
    )
    conn.close()

    primary_flags = [f for f in flags if f.corpus_tier == "primary"]
    assert len(primary_flags) == 1
    assert primary_flags[0].technology_area == "DoD Correct Match"


def test_flags_never_carry_a_match_status():
    from entity_screening.common.schema import TopicSimilarityFlag

    assert not hasattr(TopicSimilarityFlag, "status")
