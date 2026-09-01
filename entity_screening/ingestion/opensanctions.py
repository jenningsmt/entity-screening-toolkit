"""OpenSanctions consolidated targets ingester.

Streams targets.simple.csv through DuckDB's native CSV reader — columnar,
never loads the whole file into a Python list — and yields one SourceRecord
per row via chunked `fetchmany` batches. V1's largest file (434MB) doesn't
need ed-sector-surveyor's hand-rolled ijson chunking; that pattern is the
one to reach for if a future phase adds a large single-file JSON dump
(e.g. targets.nested.json or an OpenAlex subset).
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import duckdb

from entity_screening.common.schema import SourceRecord
from entity_screening.ingestion.base import BaseIngester, IngestionError, IngestionErrorLog

REQUIRED_COLUMNS = ("id", "schema", "name")
FETCH_BATCH_SIZE = 5000


class OpenSanctionsTargetsIngester(BaseIngester):
    source_dataset = "opensanctions_targets_simple"

    def __init__(
        self,
        error_log: IngestionErrorLog,
        *,
        csv_path: Path | str,
        retrieval_date: date | None = None,
    ) -> None:
        super().__init__(error_log, retrieval_date=retrieval_date)
        self.csv_path = Path(csv_path)

    def stream_records(self) -> Iterator[SourceRecord]:
        conn = duckdb.connect(":memory:")
        try:
            relation = conn.execute(
                "SELECT * FROM read_csv_auto(?, header=true, sample_size=-1)",
                [str(self.csv_path)],
            )
            columns = [desc[0] for desc in relation.description]

            while True:
                batch = relation.fetchmany(FETCH_BATCH_SIZE)
                if not batch:
                    break
                for row in batch:
                    record = dict(zip(columns, row))
                    missing = [col for col in REQUIRED_COLUMNS if not record.get(col)]
                    if missing:
                        self.error_log.record(
                            IngestionError(
                                source_dataset=self.source_dataset,
                                raw_content=json.dumps(record, default=str)[:2000],
                                reason="missing required column(s): " + ", ".join(missing),
                            )
                        )
                        continue
                    yield SourceRecord(
                        source_dataset=self.source_dataset,
                        retrieval_date=self.retrieval_date,
                        source_record_id=str(record["id"]),
                        fields=record,
                    )
        finally:
            conn.close()
