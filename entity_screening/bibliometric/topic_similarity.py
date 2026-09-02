"""Semantic topic-similarity layer against real critical-technology reference
corpora (deferred VSS work, docs/plans/2026-09-01-vss-topic-similarity-layer.md).

For each of a run's resolved authors, fetches their OpenAlex works, reconstructs
each paper's abstract (OpenAlex only provides `abstract_inverted_index`, a
word-to-position map -- there is no plain `abstract` field at all; ~18% of real
papers have neither), embeds it, and ranks it against two real reference corpora
independently: the primary corpus (the War Department's 6 Critical Technology
Areas, full-sentence descriptions) and the secondary corpus (the White House OSTP's
18-category CET list, bare technical terms with no prose, concatenated per category
into one passage).

**The two corpora are ranked independently, never pooled into one comparison**
(binding acceptance criterion from plan review): DoD's full-sentence descriptions
and CET's concatenated-fragment descriptions sit at different points in an
embedding-similarity distribution for reasons that have nothing to do with actual
topical relevance, so pooling both into one 24-way ranking would let a CET category
out- or under-rank a DoD category purely on this text-length artifact.

Real validation (2 true positives, 2 true negatives) showed an absolute
cosine-similarity cutoff alone doesn't cleanly separate a true match from a false
one -- a real, unrelated climate-science abstract scored 0.59 against
"Biomanufacturing," higher than either true positive's own second-best category.
What did separate cleanly was the *margin* between a paper's best and second-best
match within one corpus: true positives led their field by ~0.11-0.13; the false
positive led by only ~0.045. DEFAULT_MARGIN is set from that real but small sample
and is explicitly provisional -- see the plan's binding verification item 2 for the
larger real calibration pass still needed before trusting it further.

Every resulting TopicSimilarityFlag is advisory only: no MatchStatus, never read by
scoring/score.py.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import duckdb

from entity_screening.bibliometric.embeddings import EmbedFn, embed_passage, embed_query
from entity_screening.bibliometric.openalex_client import FetchFn, get_author_works
from entity_screening.common.schema import ResolvedAuthor, TopicSimilarityFlag

DATA_DIR = Path(__file__).resolve().parent / "data"
DOD_CORPUS_FILE = DATA_DIR / "dod_critical_technology_areas.json"
CET_CORPUS_FILE = DATA_DIR / "cet_list.json"

# Provisional -- calibrated against 2 true positives / 2 true negatives (see module
# docstring). Needs a larger real validation pass before being trusted further.
DEFAULT_MARGIN = 0.10


def reconstruct_abstract(abstract_inverted_index: dict | None) -> str | None:
    """OpenAlex has no plain `abstract` field, only a word->position-list map
    (publishers' copyright terms don't allow OpenAlex to republish plain abstract
    text). Reconstructs the original text via a positional sort-and-join. Returns
    None if there's nothing to reconstruct (a real, non-trivial gap: ~18% of real
    papers in a sampled check had no abstract at all)."""
    if not abstract_inverted_index:
        return None
    positions: dict[int, str] = {}
    for word, indices in abstract_inverted_index.items():
        for i in indices:
            positions[i] = word
    return " ".join(positions[i] for i in sorted(positions))


def load_corpus(path: Path | str) -> list[dict]:
    """Loads a bundled reference-corpus file into a flat list of
    {id, name, text, tier} dicts ready for embedding. A DoD-style entry embeds its
    own real `description`; a CET-style entry has no prose at all, so its
    subfields are concatenated into one passage per category (see module
    docstring) rather than embedded individually as 2-4 word fragments."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    tier = data["provenance"]["confidence_tier"]
    entries = []
    for area in data["technology_areas"]:
        text = area["description"] if "description" in area else (
            area["name"] + ": " + "; ".join(area["subfields"])
        )
        entries.append({"id": area["id"], "name": area["name"], "text": text, "tier": tier})
    return entries


def embed_and_persist_papers(
    conn: duckdb.DuckDBPyConnection,
    run_id: str,
    entity_id: str,
    resolved_authors: Iterable[ResolvedAuthor],
    fetch: FetchFn | None = None,
    embed_passage_fn: EmbedFn = embed_passage,
) -> int:
    """Fetches each resolved author's works, reconstructs abstracts, skips works
    with none, embeds the rest, and persists them into paper_embeddings. Returns
    the number of papers actually embedded."""
    from entity_screening.common import storage

    rows = []
    for resolved_author in resolved_authors:
        works = get_author_works(resolved_author.openalex_author_id, fetch=fetch)
        for work in works:
            abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
            if abstract is None:
                continue
            embedding = embed_passage_fn(abstract)
            rows.append(
                (
                    work.get("id"),
                    entity_id,
                    resolved_author.pi_name,
                    work.get("title"),
                    embedding,
                )
            )
    storage.insert_paper_embeddings(conn, rows, run_id, entity_id)
    return len(rows)


def _ensure_vss_loaded(conn: duckdb.DuckDBPyConnection) -> None:
    """LOAD alone succeeds once the extension has been installed at least once on
    this machine (DuckDB caches it locally); INSTALL is only attempted as a
    fallback, since it may require a network call."""
    try:
        conn.execute("LOAD vss")
    except Exception:
        conn.execute("INSTALL vss")
        conn.execute("LOAD vss")


def _rank_against_corpus(
    conn: duckdb.DuckDBPyConnection,
    run_id: str,
    entity_id: str,
    corpus: list[dict],
    margin: float,
    embed_query_fn: EmbedFn,
) -> list[TopicSimilarityFlag]:
    """Ranks every persisted paper against ONE corpus only -- never pooled with
    another corpus (see module docstring). A paper is flagged only if its best
    match leads the runner-up by at least `margin` within this corpus."""
    if not corpus:
        return []

    _ensure_vss_loaded(conn)
    conn.execute("CREATE OR REPLACE TEMP TABLE _corpus_vectors (id VARCHAR, name VARCHAR, embedding FLOAT[384])")
    conn.executemany(
        "INSERT INTO _corpus_vectors VALUES (?, ?, ?)",
        [(entry["id"], entry["name"], embed_query_fn(entry["text"])) for entry in corpus],
    )

    rows = conn.execute(
        """
        WITH sims AS (
            SELECT p.openalex_work_id, p.pi_name, p.work_title, c.id AS area_id,
                   c.name AS area_name,
                   (1 - array_cosine_distance(p.embedding, c.embedding)) AS similarity
            FROM paper_embeddings p CROSS JOIN _corpus_vectors c
            WHERE p.run_id = ? AND p.entity_id = ?
        ),
        ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY openalex_work_id ORDER BY similarity DESC
            ) AS rnk
            FROM sims
        )
        SELECT r1.openalex_work_id, r1.pi_name, r1.work_title, r1.area_name,
               r1.similarity, r2.area_name, r2.similarity
        FROM ranked r1
        LEFT JOIN ranked r2 ON r1.openalex_work_id = r2.openalex_work_id AND r2.rnk = 2
        WHERE r1.rnk = 1
        """,
        [run_id, entity_id],
    ).fetchall()
    conn.execute("DROP TABLE _corpus_vectors")

    tier = corpus[0]["tier"]
    flags = []
    for (
        openalex_work_id, pi_name, work_title, area_name, top_similarity,
        runner_up_area, runner_up_similarity,
    ) in rows:
        runner_up_similarity = runner_up_similarity if runner_up_similarity is not None else 0.0
        if top_similarity - runner_up_similarity < margin:
            continue
        flags.append(
            TopicSimilarityFlag(
                entity_id=entity_id,
                pi_name=pi_name,
                openalex_work_id=openalex_work_id,
                work_title=work_title,
                technology_area=area_name,
                corpus_tier=tier,
                similarity_score=top_similarity,
                evidence={
                    "runner_up_area": runner_up_area,
                    "runner_up_similarity": runner_up_similarity,
                    "margin": top_similarity - runner_up_similarity,
                    "embedding_model": "BAAI/bge-small-en-v1.5",
                },
            )
        )
    return flags


def compute_topic_similarity_flags(
    conn: duckdb.DuckDBPyConnection,
    run_id: str,
    entity_id: str,
    resolved_authors: Iterable[ResolvedAuthor],
    dod_corpus: list[dict],
    cet_corpus: list[dict],
    margin: float = DEFAULT_MARGIN,
    fetch: FetchFn | None = None,
    embed_query_fn: EmbedFn = embed_query,
    embed_passage_fn: EmbedFn = embed_passage,
) -> list[TopicSimilarityFlag]:
    embed_and_persist_papers(
        conn, run_id, entity_id, resolved_authors, fetch=fetch, embed_passage_fn=embed_passage_fn
    )
    primary_flags = _rank_against_corpus(conn, run_id, entity_id, dod_corpus, margin, embed_query_fn)
    secondary_flags = _rank_against_corpus(conn, run_id, entity_id, cet_corpus, margin, embed_query_fn)
    return primary_flags + secondary_flags
