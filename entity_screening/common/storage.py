"""Thin DuckDB connection and schema helpers.

DuckDB (not SQLite) per docs/requirements.md Section 7: embedded, single-file,
no-server, but columnar and built for the join/aggregate patterns this
project's larger sources (GLEIF, OpenAlex, in later phases) need.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import duckdb

from entity_screening.common.schema import (
    ForeignControlFlag,
    MatchStatus,
    OwnershipMatch,
    ResolvedAuthor,
    ResolvedEntity,
    ScoredEntity,
    ScreeningHit,
    SourceRecord,
    TopicSimilarityFlag,
)

DEFAULT_DB_PATH = Path("data/processed/entity_screening.duckdb")

SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS raw_nsf_awards (
    source_record_id VARCHAR,
    source_dataset VARCHAR,
    retrieval_date DATE,
    raw JSON,
    -- Added for Epic E: enrich_bibliometric re-derives each entity's PI names
    -- from this table for a specific run (raw_nsf_awards has no other way to
    -- scope a query to "records ingested during run X" without it) -- see
    -- docs/plans/2026-09-01-v3-openalex-bibliometric-affiliation-layer.md's
    -- Finding 4. Added to all four raw_* tables for consistency even though
    -- only raw_nsf_awards is queried back today.
    run_id VARCHAR
);

CREATE TABLE IF NOT EXISTS raw_opensanctions_targets (
    source_record_id VARCHAR,
    source_dataset VARCHAR,
    retrieval_date DATE,
    raw JSON,
    run_id VARCHAR
);

CREATE TABLE IF NOT EXISTS raw_dod_1260h (
    source_record_id VARCHAR,
    source_dataset VARCHAR,
    retrieval_date DATE,
    raw JSON,
    run_id VARCHAR
);

CREATE TABLE IF NOT EXISTS raw_section_117 (
    source_record_id VARCHAR,
    source_dataset VARCHAR,
    retrieval_date DATE,
    raw JSON,
    run_id VARCHAR
);

CREATE TABLE IF NOT EXISTS resolved_entities (
    entity_id VARCHAR,
    canonical_name VARCHAR,
    entity_type VARCHAR,
    run_id VARCHAR,
    -- entity_id is a deterministic hash of the normalized name (see
    -- pipeline.py:resolve_entities_from_nsf), so the same real-world entity
    -- legitimately recurs across separate runs with the same entity_id —
    -- the key must be scoped per-run, not entity_id alone, or a second call
    -- to run_screening against the same DB file (exactly what a long-lived
    -- API server does) raises a primary-key violation.
    PRIMARY KEY (entity_id, run_id)
);

CREATE TABLE IF NOT EXISTS screening_hits (
    entity_id VARCHAR,
    list_name VARCHAR,
    matched_variant VARCHAR,
    matched_field VARCHAR,
    confidence DOUBLE,
    evidence JSON,
    status VARCHAR,
    run_id VARCHAR
);

CREATE TABLE IF NOT EXISTS scored_entities (
    entity_id VARCHAR,
    canonical_name VARCHAR,
    total_score DOUBLE,
    factors JSON,
    run_id VARCHAR
);

-- gleif_lei and gleif_relationships are NOT declared here: ownership/ingest.py
-- bulk-loads them directly via CREATE OR REPLACE TABLE ... AS SELECT ... FROM
-- read_csv_auto(...), a disposable shared working copy rebuilt on every
-- enrich_ownership call (see GleifSnapshotManifest's docstring for why the
-- durable per-run record lives elsewhere, not in these tables).

CREATE TABLE IF NOT EXISTS lei_matches (
    entity_id VARCHAR,
    run_id VARCHAR,
    lei VARCHAR,
    legal_name VARCHAR,
    legal_jurisdiction VARCHAR,
    confidence DOUBLE,
    match_basis VARCHAR,
    status VARCHAR,
    -- "Current state" table like resolved_entities/scored_entities, not
    -- append-only: re-running enrich_ownership for the same run_id deletes
    -- and replaces these rows (see insert_lei_matches).
    PRIMARY KEY (entity_id, run_id)
);

CREATE TABLE IF NOT EXISTS openalex_author_matches (
    entity_id VARCHAR,
    run_id VARCHAR,
    pi_name VARCHAR,
    openalex_author_id VARCHAR,
    display_name VARCHAR,
    confidence DOUBLE,
    match_basis VARCHAR,
    evidence JSON,
    status VARCHAR
    -- No PRIMARY KEY here (unlike lei_matches' (entity_id, run_id)): a single
    -- entity can legitimately have multiple PIs, and a single PI can
    -- legitimately resolve to multiple tied ResolvedAuthor candidates (see
    -- docs/plans/2026-09-01-v3-openalex-bibliometric-affiliation-layer.md's
    -- Finding 3) -- (entity_id, run_id) alone isn't unique here.
);

CREATE TABLE IF NOT EXISTS paper_embeddings (
    openalex_work_id VARCHAR,
    run_id VARCHAR,
    entity_id VARCHAR,
    pi_name VARCHAR,
    work_title VARCHAR,
    -- BAAI/bge-small-en-v1.5 produces 384-dim vectors. Persisted as plain data
    -- (safe -- no custom-index WAL risk), not via a persisted HNSW index: DuckDB's
    -- own current docs flag on-disk HNSW persistence as experimental specifically
    -- because WAL crash-recovery isn't implemented for custom indexes. An HNSW
    -- index is built ephemerally in memory per query call instead -- see
    -- bibliometric/topic_similarity.py.
    embedding FLOAT[384]
);

CREATE TABLE IF NOT EXISTS topic_similarity_flags (
    entity_id VARCHAR,
    run_id VARCHAR,
    pi_name VARCHAR,
    openalex_work_id VARCHAR,
    work_title VARCHAR,
    technology_area VARCHAR,
    corpus_tier VARCHAR,
    similarity_score DOUBLE,
    evidence JSON,
    recommendation VARCHAR
    -- No PRIMARY KEY: a single paper can legitimately clear both the primary
    -- (DoD) and secondary (CET) corpus's margin rule independently (see the V3
    -- VSS plan's binding acceptance criterion 1 -- the two corpora are ranked
    -- separately, never pooled), producing two distinct rows for one paper.
);

CREATE TABLE IF NOT EXISTS ownership_flags (
    entity_id VARCHAR,
    run_id VARCHAR,
    entity_lei VARCHAR,
    entity_jurisdiction VARCHAR,
    ultimate_parent_lei VARCHAR,
    ultimate_parent_name VARCHAR,
    ultimate_parent_jurisdiction VARCHAR,
    relationship_path JSON,
    match_confidence DOUBLE,
    evidence JSON,
    status VARCHAR,
    PRIMARY KEY (entity_id, run_id)
);
"""


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    """Opens (creating if needed) the project's DuckDB file and ensures the schema exists."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path))
    conn.execute(SCHEMA_DDL)
    return conn


def insert_source_records(
    conn: duckdb.DuckDBPyConnection, table: str, records: Iterable[SourceRecord], run_id: str
) -> None:
    rows = [
        (
            r.source_record_id,
            r.source_dataset,
            r.retrieval_date,
            json.dumps(r.fields, default=str),
            run_id,
        )
        for r in records
    ]
    if rows:
        conn.executemany(f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?)", rows)


def load_raw_record_fields(
    conn: duckdb.DuckDBPyConnection, table: str, run_id: str
) -> list[dict]:
    """Reads back the raw `fields` dicts ingested into `table` for a specific run --
    e.g. enrich_bibliometric (Epic E) re-deriving each entity's PI names from
    raw_nsf_awards, since resolved_entities itself doesn't retain that detail (see
    load_resolved_entities' docstring)."""
    rows = conn.execute(f"SELECT raw FROM {table} WHERE run_id = ?", [run_id]).fetchall()
    return [json.loads(raw) for (raw,) in rows]


def load_raw_records(conn: duckdb.DuckDBPyConnection, table: str, run_id: str) -> list[SourceRecord]:
    """Like load_raw_record_fields, but reconstructs full SourceRecords -- e.g.
    enrich_bibliometric rebuilding the same OpenSanctionsList/DoD1260HList a run's
    original screen_entity call used, from what's already persisted, rather than
    requiring the caller to re-supply file paths for a source that hasn't changed."""
    rows = conn.execute(
        f"SELECT source_record_id, source_dataset, retrieval_date, raw FROM {table} WHERE run_id = ?",
        [run_id],
    ).fetchall()
    return [
        SourceRecord(
            source_dataset=source_dataset,
            retrieval_date=retrieval_date,
            source_record_id=source_record_id,
            fields=json.loads(raw),
        )
        for source_record_id, source_dataset, retrieval_date, raw in rows
    ]


def insert_resolved_entities(
    conn: duckdb.DuckDBPyConnection, entities: Iterable[ResolvedEntity], run_id: str
) -> None:
    rows = [(e.entity_id, e.canonical_name, e.entity_type, run_id) for e in entities]
    if rows:
        conn.executemany("INSERT INTO resolved_entities VALUES (?, ?, ?, ?)", rows)


def insert_screening_hits(
    conn: duckdb.DuckDBPyConnection, hits: Iterable[ScreeningHit], run_id: str
) -> None:
    rows = [
        (
            h.entity_id,
            h.list_name,
            h.matched_variant,
            h.matched_field,
            h.confidence,
            json.dumps(h.evidence, default=str),
            h.status.value,
            run_id,
        )
        for h in hits
    ]
    if rows:
        conn.executemany(
            "INSERT INTO screening_hits VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows
        )


def insert_scored_entities(
    conn: duckdb.DuckDBPyConnection, scored_entities: Iterable[ScoredEntity]
) -> None:
    rows = [
        (
            s.entity_id,
            s.canonical_name,
            s.score.total,
            json.dumps(s.score.factors, default=str),
            s.run_id,
        )
        for s in scored_entities
    ]
    if rows:
        conn.executemany("INSERT INTO scored_entities VALUES (?, ?, ?, ?, ?)", rows)


def load_resolved_entities(conn: duckdb.DuckDBPyConnection, run_id: str) -> list[ResolvedEntity]:
    """Reconstructs the ResolvedEntity rows persisted for a run.

    `source_records` always comes back empty: the resolved_entities table
    doesn't persist which raw records fed into each entity, only the entity
    itself. Scoring (`scoring/score.py:score_entity`) doesn't read that field,
    so this is sufficient for re-scoring; a deeper join back to
    raw_nsf_awards by source_record_id would be needed for anything that
    does.
    """
    rows = conn.execute(
        "SELECT entity_id, canonical_name, entity_type FROM resolved_entities WHERE run_id = ?",
        [run_id],
    ).fetchall()
    return [
        ResolvedEntity(
            entity_id=entity_id,
            canonical_name=canonical_name,
            entity_type=entity_type,
            source_records=(),
        )
        for entity_id, canonical_name, entity_type in rows
    ]


def insert_lei_matches(
    conn: duckdb.DuckDBPyConnection, matches: Iterable[OwnershipMatch], run_id: str
) -> None:
    """Deletes any existing rows for this run_id first — enrich_ownership is
    re-runnable for the same run (a deliberate "current state" model, see
    GleifSnapshotManifest's docstring), not append-only, so a second call must
    replace rather than duplicate/collide with the first."""
    conn.execute("DELETE FROM lei_matches WHERE run_id = ?", [run_id])
    rows = [
        (
            m.entity_id,
            run_id,
            m.lei,
            m.legal_name,
            m.legal_jurisdiction,
            m.confidence,
            m.match_basis,
            m.status.value,
        )
        for m in matches
    ]
    if rows:
        conn.executemany("INSERT INTO lei_matches VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)


def load_lei_match(
    conn: duckdb.DuckDBPyConnection, run_id: str, entity_id: str
) -> OwnershipMatch | None:
    row = conn.execute(
        "SELECT entity_id, lei, legal_name, legal_jurisdiction, confidence, match_basis, "
        "status FROM lei_matches WHERE run_id = ? AND entity_id = ?",
        [run_id, entity_id],
    ).fetchone()
    if row is None:
        return None
    entity_id, lei, legal_name, legal_jurisdiction, confidence, match_basis, status = row
    return OwnershipMatch(
        entity_id=entity_id,
        lei=lei,
        legal_name=legal_name,
        legal_jurisdiction=legal_jurisdiction,
        confidence=confidence,
        match_basis=match_basis,
        status=MatchStatus(status),
    )


def insert_ownership_flags(
    conn: duckdb.DuckDBPyConnection, flags: Iterable[ForeignControlFlag], run_id: str
) -> None:
    """Same re-runnable "current state" semantics as insert_lei_matches."""
    conn.execute("DELETE FROM ownership_flags WHERE run_id = ?", [run_id])
    rows = [
        (
            f.entity_id,
            run_id,
            f.entity_lei,
            f.entity_jurisdiction,
            f.ultimate_parent_lei,
            f.ultimate_parent_name,
            f.ultimate_parent_jurisdiction,
            json.dumps(list(f.relationship_path)),
            f.match_confidence,
            json.dumps(f.evidence, default=str),
            f.status.value,
        )
        for f in flags
    ]
    if rows:
        conn.executemany(
            "INSERT INTO ownership_flags VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
        )


def load_ownership_flags(conn: duckdb.DuckDBPyConnection, run_id: str) -> list[ForeignControlFlag]:
    rows = conn.execute(
        "SELECT entity_id, entity_lei, entity_jurisdiction, ultimate_parent_lei, "
        "ultimate_parent_name, ultimate_parent_jurisdiction, relationship_path, "
        "match_confidence, evidence, status FROM ownership_flags WHERE run_id = ?",
        [run_id],
    ).fetchall()
    return [
        ForeignControlFlag(
            entity_id=entity_id,
            entity_lei=entity_lei,
            entity_jurisdiction=entity_jurisdiction,
            ultimate_parent_lei=ultimate_parent_lei,
            ultimate_parent_name=ultimate_parent_name,
            ultimate_parent_jurisdiction=ultimate_parent_jurisdiction,
            relationship_path=tuple(json.loads(relationship_path)),
            match_confidence=match_confidence,
            evidence=json.loads(evidence),
            status=MatchStatus(status),
        )
        for (
            entity_id,
            entity_lei,
            entity_jurisdiction,
            ultimate_parent_lei,
            ultimate_parent_name,
            ultimate_parent_jurisdiction,
            relationship_path,
            match_confidence,
            evidence,
            status,
        ) in rows
    ]


def insert_openalex_author_matches(
    conn: duckdb.DuckDBPyConnection, matches: Iterable[ResolvedAuthor], run_id: str
) -> None:
    """Deletes any existing rows for this run_id first -- same re-runnable
    "current state" semantics as insert_lei_matches: enrich_bibliometric is
    re-runnable for the same run, not append-only."""
    conn.execute("DELETE FROM openalex_author_matches WHERE run_id = ?", [run_id])
    rows = [
        (
            m.entity_id,
            run_id,
            m.pi_name,
            m.openalex_author_id,
            m.display_name,
            m.confidence,
            m.match_basis,
            json.dumps(m.evidence, default=str),
            m.status.value,
        )
        for m in matches
    ]
    if rows:
        conn.executemany(
            "INSERT INTO openalex_author_matches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
        )


def load_openalex_author_matches(
    conn: duckdb.DuckDBPyConnection, run_id: str
) -> list[ResolvedAuthor]:
    rows = conn.execute(
        "SELECT entity_id, pi_name, openalex_author_id, display_name, confidence, "
        "match_basis, evidence, status FROM openalex_author_matches WHERE run_id = ?",
        [run_id],
    ).fetchall()
    return [
        ResolvedAuthor(
            entity_id=entity_id,
            pi_name=pi_name,
            openalex_author_id=openalex_author_id,
            display_name=display_name,
            confidence=confidence,
            match_basis=match_basis,
            evidence=json.loads(evidence),
            status=MatchStatus(status),
        )
        for (
            entity_id,
            pi_name,
            openalex_author_id,
            display_name,
            confidence,
            match_basis,
            evidence,
            status,
        ) in rows
    ]


def insert_paper_embeddings(
    conn: duckdb.DuckDBPyConnection,
    embeddings: Iterable[tuple[str, str, str, str, list[float]]],
    run_id: str,
) -> None:
    """Each item is (openalex_work_id, entity_id, pi_name, work_title, embedding)."""
    rows = [
        (openalex_work_id, run_id, entity_id, pi_name, work_title, embedding)
        for openalex_work_id, entity_id, pi_name, work_title, embedding in embeddings
    ]
    if rows:
        conn.executemany("INSERT INTO paper_embeddings VALUES (?, ?, ?, ?, ?, ?)", rows)


def load_paper_embeddings(conn: duckdb.DuckDBPyConnection, run_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT openalex_work_id, entity_id, pi_name, work_title, embedding "
        "FROM paper_embeddings WHERE run_id = ?",
        [run_id],
    ).fetchall()
    return [
        {
            "openalex_work_id": openalex_work_id,
            "entity_id": entity_id,
            "pi_name": pi_name,
            "work_title": work_title,
            "embedding": list(embedding),
        }
        for openalex_work_id, entity_id, pi_name, work_title, embedding in rows
    ]


def insert_topic_similarity_flags(
    conn: duckdb.DuckDBPyConnection, flags: Iterable[TopicSimilarityFlag], run_id: str
) -> None:
    """Deletes any existing rows for this run_id first -- same re-runnable
    "current state" semantics as insert_lei_matches/insert_openalex_author_matches."""
    conn.execute("DELETE FROM topic_similarity_flags WHERE run_id = ?", [run_id])
    rows = [
        (
            f.entity_id,
            run_id,
            f.pi_name,
            f.openalex_work_id,
            f.work_title,
            f.technology_area,
            f.corpus_tier,
            f.similarity_score,
            json.dumps(f.evidence, default=str),
            f.recommendation,
        )
        for f in flags
    ]
    if rows:
        conn.executemany(
            "INSERT INTO topic_similarity_flags VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
        )


def load_topic_similarity_flags(
    conn: duckdb.DuckDBPyConnection, run_id: str
) -> list[TopicSimilarityFlag]:
    rows = conn.execute(
        "SELECT entity_id, pi_name, openalex_work_id, work_title, technology_area, "
        "corpus_tier, similarity_score, evidence, recommendation "
        "FROM topic_similarity_flags WHERE run_id = ?",
        [run_id],
    ).fetchall()
    return [
        TopicSimilarityFlag(
            entity_id=entity_id,
            pi_name=pi_name,
            openalex_work_id=openalex_work_id,
            work_title=work_title,
            technology_area=technology_area,
            corpus_tier=corpus_tier,
            similarity_score=similarity_score,
            evidence=json.loads(evidence),
            recommendation=recommendation,
        )
        for (
            entity_id,
            pi_name,
            openalex_work_id,
            work_title,
            technology_area,
            corpus_tier,
            similarity_score,
            evidence,
            recommendation,
        ) in rows
    ]


def load_screening_hits(conn: duckdb.DuckDBPyConnection, run_id: str) -> list[ScreeningHit]:
    rows = conn.execute(
        "SELECT entity_id, list_name, matched_variant, matched_field, confidence, "
        "evidence, status FROM screening_hits WHERE run_id = ?",
        [run_id],
    ).fetchall()
    return [
        ScreeningHit(
            entity_id=entity_id,
            list_name=list_name,
            matched_variant=matched_variant,
            matched_field=matched_field,
            confidence=confidence,
            evidence=json.loads(evidence),
            status=MatchStatus(status),
        )
        for entity_id, list_name, matched_variant, matched_field, confidence, evidence, status in rows
    ]
