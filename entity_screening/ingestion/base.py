"""Shared ingestion contract: streaming, provenance tagging, and error logging.

Every ingester tags each record with its source dataset name, retrieval date,
and source-record identifier (Epic A) — deliberately net-new relative to the
sibling project ed-sector-surveyor, which keeps a raw_json column but no
source-id/retrieval-date columns at ingestion time. Malformed records are
logged via `logging` to a JSONL error file and counted, rather than dropped
silently — ed-sector-surveyor's actual ingestion loop does
`except json.JSONDecodeError: continue` with no log line and no counter, and
Epic A explicitly requires better than that.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from entity_screening.common.schema import SourceRecord

logger = logging.getLogger(__name__)


@dataclass
class IngestionError:
    source_dataset: str
    raw_content: str
    reason: str


class IngestionErrorLog:
    """Writes malformed records to a JSONL error log and tracks a running count."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._count = 0
        self._fh = self.path.open("a", encoding="utf-8")

    def record(self, error: IngestionError) -> None:
        self._count += 1
        logger.warning("ingestion error in %s: %s", error.source_dataset, error.reason)
        self._fh.write(
            json.dumps(
                {
                    "source_dataset": error.source_dataset,
                    "raw_content": error.raw_content,
                    "reason": error.reason,
                }
            )
            + "\n"
        )
        self._fh.flush()

    @property
    def count(self) -> int:
        return self._count

    def close(self) -> None:
        self._fh.close()


class BaseIngester(ABC):
    """Contract every source-specific ingester implements."""

    source_dataset: str

    def __init__(self, error_log: IngestionErrorLog, *, retrieval_date: date | None = None):
        self.error_log = error_log
        self.retrieval_date = retrieval_date or date.today()

    @abstractmethod
    def stream_records(self) -> Iterator[SourceRecord]:
        """Yields SourceRecord objects one at a time — never load-to-memory."""
        raise NotImplementedError
