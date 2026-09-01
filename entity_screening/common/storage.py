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

from entity_screening.common.schema import ResolvedEntity, ScoredEntity, ScreeningHit, SourceRecord

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

CREATE TABLE IF NOT EXISTS resolved_entities (
    entity_id VARCHAR PRIMARY KEY,
    canonical_name VARCHAR,
    entity_type VARCHAR,
    run_id VARCHAR
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
