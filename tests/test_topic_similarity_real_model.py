"""Real-model regression guard (mirrors
test_dod_1260h_default_bundled_file_exists_and_parses's "guard the real bundled
artifact" role): loads the actual pinned BAAI/bge-small-en-v1.5 revision and
re-runs the exact real validation pairs found while designing this feature (see
docs/plans/2026-09-01-vss-topic-similarity-layer.md's Finding 4) -- a real
hypersonics-vehicle abstract and a real quantum-computing abstract, both true
positives, against the real bundled DoD corpus. A future model/revision change
that silently breaks real discrimination should fail this test, not surface only
as a quiet accuracy regression in production.

Downloads/loads the real ~130MB pinned model on first run -- slower than the rest
of the suite, kept in its own file for that reason.
"""
from __future__ import annotations

from entity_screening.bibliometric.embeddings import embed_passage, embed_query
from entity_screening.bibliometric.topic_similarity import DOD_CORPUS_FILE, load_corpus

HYPERSONICS_ABSTRACT = (
    "Hypersonic vehicles with turbojet, ramjet, and scramjet engines are expected "
    "to be widely applied to future transportation systems. Due to high-speed "
    "flight in the atmosphere, body outer surfaces suffer strong aerodynamic "
    "heating, and on the other hand, combustion chamber inter walls are under "
    "extremely high temperature and heat flux. Therefore, more efficient and "
    "stable active cooling technologies are required in hypersonic vehicles, such "
    "as regenerative cooling, film cooling, and transpiration cooling."
)

QUANTUM_ABSTRACT = (
    "Noisy Intermediate-Scale Quantum (NISQ) technology will be available in the "
    "near future. Quantum computers with 50-100 qubits may be able to perform "
    "tasks which surpass the capabilities of today's classical digital computers, "
    "but noise in quantum gates will limit the size of quantum circuits that can "
    "be executed reliably."
)

CLIMATE_ABSTRACT_1 = (
    "Climate change drives shifts in species composition, but turnover in many "
    "communities lags behind the current pace of change. We analyzed plant "
    "community composition and function data from ~60,000 rangeland monitoring "
    "sites across the western US to measure how community-climate disequilibrium "
    "contributes to spatial and temporal variation in net primary productivity."
)


def _best_and_margin(abstract: str, corpus: list[dict]) -> tuple[str, float, float]:
    passage_vec = embed_passage(abstract)
    scored = []
    for entry in corpus:
        query_vec = embed_query(entry["text"])
        similarity = sum(a * b for a, b in zip(passage_vec, query_vec))
        scored.append((entry["name"], similarity))
    scored.sort(key=lambda x: -x[1])
    best_name, best_score = scored[0]
    runner_up_score = scored[1][1] if len(scored) > 1 else 0.0
    return best_name, best_score, best_score - runner_up_score


def test_real_hypersonics_abstract_ranks_scaled_hypersonics_highest():
    corpus = load_corpus(DOD_CORPUS_FILE)
    best_name, best_score, margin = _best_and_margin(HYPERSONICS_ABSTRACT, corpus)
    assert best_name == "Scaled Hypersonics"
    assert margin > 0.05


def test_real_quantum_abstract_ranks_quantum_and_bid_highest():
    corpus = load_corpus(DOD_CORPUS_FILE)
    best_name, best_score, margin = _best_and_margin(QUANTUM_ABSTRACT, corpus)
    assert best_name == "Quantum and Battlefield Information Dominance"
    assert margin > 0.05


def test_real_unrelated_climate_abstract_does_not_cleanly_win_a_defense_category():
    """Documents the real false-positive risk found during design (see the
    module docstring in topic_similarity.py): an absolute cosine-similarity
    cutoff alone is not reliable, which is exactly why the margin rule exists."""
    corpus = load_corpus(DOD_CORPUS_FILE)
    best_name, best_score, margin = _best_and_margin(CLIMATE_ABSTRACT_1, corpus)
    # Real finding: this scores highest against an unrelated category with only a
    # small margin -- asserting the margin stays below the true positives' margins
    # confirms the discriminating signal is still the margin, not the raw score.
    assert margin < 0.08
