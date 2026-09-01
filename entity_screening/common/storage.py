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
    ResolvedEntity,
    ScoredEntity,
    ScreeningHit,
    SourceRecord,
)

DEFAULT_DB_PATH = Path("data/processed/entity_screening.duckdb")

SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS raw_nsf_awards (
    source_record_id VARCHAR,
    source_dataset VARCHAR,
    retrieval_date DATE,
    raw JSON
);

CREATE TABLE IF NOT EXISTS raw_opensanctions_targets (
    source_record_id VARCHAR,
    source_dataset VARCHAR,
    retrieval_date DATE,
    raw JSON
);

CREATE TABLE IF NOT EXISTS raw_dod_1260h (
    source_record_id VARCHAR,
    source_dataset VARCHAR,
    retrieval_date DATE,
    raw JSON
);

CREATE TABLE IF NOT EXISTS raw_section_117 (
    source_record_id VARCHAR,
    source_dataset VARCHAR,
    retrieval_date DATE,
    raw JSON
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
    conn: duckdb.DuckDBPyConnection, table: str, records: Iterable[SourceRecord]
) -> None:
    rows = [
        (r.source_record_id, r.source_dataset, r.retrieval_date, json.dumps(r.fields, default=str))
        for r in records
    ]
    if rows:
        conn.executemany(f"INSERT INTO {table} VALUES (?, ?, ?, ?)", rows)


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
