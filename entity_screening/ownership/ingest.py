"""Bulk GLEIF ingestion into DuckDB.

GLEIF's Level 1 (LEI-CDF) concatenated file is ~3.3M records (~490MB CSV) —
too large to materialize as individual Python SourceRecord objects the way
NSF/OpenSanctions/DoD 1260H do via `BaseIngester.stream_records()`. This
module deliberately does NOT implement `BaseIngester` and does not live in
`entity_screening/ingestion/` (that would wrongly imply it does); it
bulk-loads directly into DuckDB via `read_csv_auto`, which is both simpler
and far faster at this scale.

GLEIF is also a shared reference dataset, not a per-run ingestion source:
`gleif_lei`/`gleif_relationships` are a disposable working copy, replaced by
*any* call to these functions, for *any* run — see
`common/manifest.py:GleifSnapshotManifest` for how a specific run's
provenance survives that.

Column names below are verified against a real downloaded GLEIF Golden Copy
CSV (goldencopy.gleif.org/api/v2/golden-copies/publishes/{lei2,rr}/latest.csv
— note this is a *different* host/endpoint from GLEIF's "Concatenated
Files" API at leidata.gleif.org, which serves XML, not CSV, despite both
being described as "LEI-CDF"/"RR-CDF" format in GLEIF's own docs). The
column names GLEIF's general documentation implies (`EntityStatus`,
`EntityCategory`, `StartNode`, `EndNode`, `RelationshipType`,
`RelationshipStatus`) are each actually nested one level deeper in the real
file (`Entity.EntityStatus`, `Entity.EntityCategory`,
`Relationship.StartNode.NodeID`, `Relationship.EndNode.NodeID`,
`Relationship.RelationshipType`, `Relationship.RelationshipStatus`) — this
was caught only by downloading and inspecting the actual file, not by
reading GLEIF's documentation, which describes the field concepts but not
the flattened CSV header spelling.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb

from entity_screening.ingestion.base import IngestionError, IngestionErrorLog

LEI_SOURCE_DATASET = "gleif_lei_level1"
RELATIONSHIPS_SOURCE_DATASET = "gleif_relationships_level2"
DEFAULT_BLOCK_SIZE = 3

# Only these matter for Epic C's ultimate-parent/foreign-control scope. The
# other four RelationshipType values (fund/branch/feeder relationships) and
# the separate "Level 2 Reporting Exceptions" file are explicitly out of scope.
_RELEVANT_RELATIONSHIP_TYPES = ("IS_DIRECTLY_CONSOLIDATED_BY", "IS_ULTIMATELY_CONSOLIDATED_BY")


def load_gleif_level1(
    conn: duckdb.DuckDBPyConnection,
    csv_path: Path | str,
    retrieval_date: date,
    error_log: IngestionErrorLog,
    block_size: int = DEFAULT_BLOCK_SIZE,
) -> int:
    """Bulk-loads the GLEIF Level 1 (LEI-CDF) concatenated CSV into `gleif_lei`.

    Returns the loaded record count. Malformed/incomplete rows aren't logged
    one at a time (impractical at millions of rows) — one aggregate
    IngestionError entry records the count of rows missing a LEI, appended to
    the same `error_log` the rest of a run's ingestion writes to.
    """
    csv_path = Path(csv_path)
    conn.execute(
        """
        CREATE OR REPLACE TABLE gleif_lei AS
        SELECT
            LEI AS lei,
            "Entity.LegalName" AS legal_name,
            "Entity.LegalJurisdiction" AS legal_jurisdiction,
            "Entity.HeadquartersAddress.Country" AS hq_country,
            "Entity.EntityStatus" AS entity_status,
            "Entity.EntityCategory" AS entity_category,
            substr(
                regexp_replace(lower("Entity.LegalName"), '[^a-z0-9]', '', 'g'), 1, ?
            ) AS normalized_name_prefix,
            ? AS source_dataset,
            ? AS retrieval_date
        FROM read_csv_auto(?, header=true, sample_size=-1, ignore_errors=true)
        """,
        [block_size, LEI_SOURCE_DATASET, retrieval_date, str(csv_path)],
    )
    total = conn.execute("SELECT count(*) FROM gleif_lei").fetchone()[0]
    null_lei = conn.execute("SELECT count(*) FROM gleif_lei WHERE lei IS NULL").fetchone()[0]
    if null_lei:
        error_log.record(
            IngestionError(
                source_dataset=LEI_SOURCE_DATASET,
                raw_content=str(csv_path),
                reason=f"{null_lei} row(s) missing LEI after bulk load "
                "(aggregate count, not per-row — see module docstring)",
            )
        )
    return total


def load_gleif_level2(
    conn: duckdb.DuckDBPyConnection,
    csv_path: Path | str,
    retrieval_date: date,
    error_log: IngestionErrorLog,
) -> int:
    """Bulk-loads the GLEIF Level 2 (RR-CDF) concatenated CSV into
    `gleif_relationships`, keeping only ACTIVE `IS_DIRECTLY_CONSOLIDATED_BY` /
    `IS_ULTIMATELY_CONSOLIDATED_BY` rows — the only ones
    `ownership/graph.py`'s traversal needs for Epic C's scope."""
    csv_path = Path(csv_path)
    placeholders = ", ".join("?" for _ in _RELEVANT_RELATIONSHIP_TYPES)
    conn.execute(
        f"""
        CREATE OR REPLACE TABLE gleif_relationships AS
        SELECT
            "Relationship.StartNode.NodeID" AS start_lei,
            "Relationship.EndNode.NodeID" AS end_lei,
            "Relationship.RelationshipType" AS relationship_type,
            "Relationship.RelationshipStatus" AS relationship_status,
            ? AS source_dataset,
            ? AS retrieval_date
        FROM read_csv_auto(?, header=true, sample_size=-1, ignore_errors=true)
        WHERE "Relationship.RelationshipType" IN ({placeholders})
          AND "Relationship.RelationshipStatus" = 'ACTIVE'
        """,
        [RELATIONSHIPS_SOURCE_DATASET, retrieval_date, str(csv_path), *_RELEVANT_RELATIONSHIP_TYPES],
    )
    total = conn.execute("SELECT count(*) FROM gleif_relationships").fetchone()[0]
    missing = conn.execute(
        "SELECT count(*) FROM gleif_relationships WHERE start_lei IS NULL OR end_lei IS NULL"
    ).fetchone()[0]
    if missing:
        error_log.record(
            IngestionError(
                source_dataset=RELATIONSHIPS_SOURCE_DATASET,
                raw_content=str(csv_path),
                reason=f"{missing} row(s) missing start/end LEI after bulk load "
                "(aggregate count, not per-row — see module docstring)",
            )
        )
    return total
