"""DoD Section 1260H entity-of-concern list ingester.

Unlike NSF/OpenSanctions, this is a small (~200-entity), annually-updated,
hand-curated static list — the underlying source is a Federal Register PDF
notice, not machine-native data (see docs/requirements.md's data source
table), so building streaming/PDF-parsing infrastructure for it wouldn't be
proportional to its size. The curated snapshot lives at
screening/data/dod_1260h.json (see that file's own "provenance" field for
exactly how and from what it was compiled) and ships bundled with the
package — there's no per-run file path a user needs to supply, unlike NSF
or OpenSanctions.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path

from entity_screening.common.schema import SourceRecord
from entity_screening.ingestion.base import BaseIngester, IngestionError, IngestionErrorLog

DEFAULT_DATA_FILE = Path(__file__).resolve().parent.parent / "screening" / "data" / "dod_1260h.json"
REQUIRED_FIELDS = ("id", "clean_name")


class DoD1260HIngester(BaseIngester):
    source_dataset = "dod_section_1260h"

    def __init__(
        self,
        error_log: IngestionErrorLog,
        *,
        data_file: Path | str = DEFAULT_DATA_FILE,
        retrieval_date: date | None = None,
    ) -> None:
        self.data_file = Path(data_file)
        # Defaults to the curated file's own "curated_at" date, not today —
        # this is a static, dated snapshot, and the manifest should say when
        # that snapshot was captured, not when the pipeline happened to run.
        super().__init__(error_log, retrieval_date=retrieval_date or self._read_curated_at())

    def _read_curated_at(self) -> date | None:
        try:
            payload = json.loads(self.data_file.read_text(encoding="utf-8"))
            curated_at = payload.get("curated_at")
            return date.fromisoformat(curated_at) if curated_at else None
        except Exception:
            return None

    def stream_records(self) -> Iterator[SourceRecord]:
        try:
            payload = json.loads(self.data_file.read_text(encoding="utf-8"))
        except Exception as exc:
            self.error_log.record(
                IngestionError(
                    source_dataset=self.source_dataset,
                    raw_content=str(self.data_file),
                    reason=f"failed to read/parse curated data file: {exc}",
                )
            )
            return

        for entity in payload.get("entities", []):
            if not isinstance(entity, dict):
                self.error_log.record(
                    IngestionError(
                        source_dataset=self.source_dataset,
                        raw_content=json.dumps(entity, default=str)[:2000],
                        reason=f"expected an entity object, got {type(entity).__name__}",
                    )
                )
                continue
            missing = [k for k in REQUIRED_FIELDS if not entity.get(k)]
            if missing:
                self.error_log.record(
                    IngestionError(
                        source_dataset=self.source_dataset,
                        raw_content=json.dumps(entity, default=str)[:2000],
                        reason="missing required field(s): " + ", ".join(missing),
                    )
                )
                continue
            yield SourceRecord(
                source_dataset=self.source_dataset,
                retrieval_date=self.retrieval_date,
                source_record_id=str(entity["id"]),
                fields=entity,
            )
