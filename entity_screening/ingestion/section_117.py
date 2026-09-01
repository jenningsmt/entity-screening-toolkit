"""Section 117 foreign gift & contract disclosure ingester (V2's final piece).

Reads the U.S. Department of Education's Section 117 bulk-download .xlsx file
via openpyxl -- already a dependency (added earlier for Excel *export*), no
new one needed. Confirmed against the real 117,152-row Feb 2025 file (see
docs/plans/2026-09-01-section-117-foreign-gift-disclosure-cross-check.md):
row 1 is a merged title/description cell, not the header -- the real header
is row 2.

`source_record_id` hashes each row's content *and* its ordinal position in
the file, not content alone: ~11% of real rows (12,856 of 117,152) are exact
content duplicates of another row, plausibly genuine repeated disclosures
(e.g. recurring gift amounts of the same size), not file artifacts. A pure
content hash would silently collapse those into a single record.

Known gap, same category as GLEIF's CSV-vs-XML trap: the Section 117 portal
relaunched in January/February 2026 with "11 additional data elements" per
ED's own press release; this ingester was built and verified against the
legacy bulk-download file, not whatever the current post-relaunch download
looks like. Re-verify the current download URL and schema before trusting
this against a freshly-downloaded file.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import openpyxl

from entity_screening.common.schema import SourceRecord
from entity_screening.ingestion.base import BaseIngester, IngestionError, IngestionErrorLog

REQUIRED_FIELDS = ("School Name", "Transaction Type")
TITLE_ROW_COUNT = 1  # row 1 is a merged title/description cell, not the header


class Section117Ingester(BaseIngester):
    source_dataset = "section_117_foreign_funding_disclosure"

    def __init__(
        self,
        error_log: IngestionErrorLog,
        *,
        xlsx_path: Path | str,
        retrieval_date: date | None = None,
    ) -> None:
        super().__init__(error_log, retrieval_date=retrieval_date)
        self.xlsx_path = Path(xlsx_path)

    def stream_records(self) -> Iterator[SourceRecord]:
        try:
            workbook = openpyxl.load_workbook(self.xlsx_path, read_only=True, data_only=True)
            worksheet = workbook.active
            rows = worksheet.iter_rows(values_only=True)
            for _ in range(TITLE_ROW_COUNT):
                next(rows)
            columns = [str(c).strip() if c is not None else "" for c in next(rows)]
        except Exception as exc:
            self.error_log.record(
                IngestionError(
                    source_dataset=self.source_dataset,
                    raw_content=str(self.xlsx_path),
                    reason=f"failed to open/read workbook: {exc}",
                )
            )
            return

        for row_index, row in enumerate(rows):
            fields = dict(zip(columns, row))
            missing = [f for f in REQUIRED_FIELDS if not fields.get(f)]
            if missing:
                self.error_log.record(
                    IngestionError(
                        source_dataset=self.source_dataset,
                        raw_content=json.dumps(fields, default=str)[:2000],
                        reason="missing required field(s): " + ", ".join(missing),
                    )
                )
                continue
            yield SourceRecord(
                source_dataset=self.source_dataset,
                retrieval_date=self.retrieval_date,
                source_record_id=_row_id(fields, row_index),
                fields=fields,
            )


def _row_id(fields: dict, row_index: int) -> str:
    """Content + ordinal position, not content alone -- see module docstring."""
    canonical = json.dumps(fields, sort_keys=True, default=str)
    digest = hashlib.sha256(f"{row_index}:{canonical}".encode("utf-8")).hexdigest()
    return f"sec117-{digest[:16]}"
