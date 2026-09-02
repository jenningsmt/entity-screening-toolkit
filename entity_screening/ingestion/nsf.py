"""NSF Award Search ingester.

Live API docs: https://www.research.gov/common/webapi/awardapisearch-v1.htm
Streams page by page rather than pulling the full result set into memory.
Also supports a pre-downloaded local JSON file (the same response shape),
which is how the demo/test fixtures run fully offline and is also the
"size-capped demo dataset" pattern docs/requirements.md Section 9 calls for.

`API_URL` was previously `https://api.research.gov/common/webapi/awardapisearch-v1/
awards.json`, a hostname that no longer resolves in DNS at all -- a pre-existing bug
first flagged in docs/plans/2026-09-01-section-117-foreign-gift-disclosure-cross-check.md
(surfaced there while verifying a different feature against real data, not actually
fixed at the time). Confirmed directly (2026-09-02): the dead host fails DNS resolution;
`api.nsf.gov` below is live and returns real award data.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path
from typing import Any

import requests

from entity_screening.common.schema import SourceRecord
from entity_screening.ingestion.base import BaseIngester, IngestionError, IngestionErrorLog

API_URL = "https://api.nsf.gov/services/v1/awards.json"
DEFAULT_PAGE_SIZE = 25
REQUIRED_FIELDS = ("id", "awardeeName")


class NSFAwardIngester(BaseIngester):
    source_dataset = "nsf_award_search"

    def __init__(
        self,
        error_log: IngestionErrorLog,
        *,
        date_start: str | None = None,
        date_end: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        local_file: Path | str | None = None,
        retrieval_date: date | None = None,
        fetch_page: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(error_log, retrieval_date=retrieval_date)
        self.date_start = date_start
        self.date_end = date_end
        self.page_size = page_size
        self.local_file = Path(local_file) if local_file else None
        self._local_file_served = False
        if fetch_page is not None:
            self._fetch_page = fetch_page
        elif self.local_file is not None:
            self._fetch_page = self._local_file_fetch_page
        else:
            self._fetch_page = self._http_fetch_page

    def _http_fetch_page(self, params: dict) -> dict:
        response = requests.get(API_URL, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def _local_file_fetch_page(self, params: dict) -> dict:
        if self._local_file_served:
            return {"response": {"award": []}}
        self._local_file_served = True
        data = json.loads(self.local_file.read_text(encoding="utf-8"))
        awards = data.get("response", {}).get("award", []) if isinstance(data, dict) else data
        return {"response": {"award": awards}}

    def location(self) -> str:
        return str(self.local_file) if self.local_file else API_URL

    def stream_records(self) -> Iterator[SourceRecord]:
        offset = 1
        while True:
            params = {
                "dateStart": self.date_start,
                "dateEnd": self.date_end,
                "offset": offset,
                "rpp": self.page_size,
            }
            try:
                payload = self._fetch_page(params)
            except Exception as exc:
                self.error_log.record(
                    IngestionError(
                        source_dataset=self.source_dataset,
                        raw_content=json.dumps(params, default=str),
                        reason=f"API request failed: {exc}",
                    )
                )
                return

            awards = payload.get("response", {}).get("award", [])
            if not awards:
                return

            for award in awards:
                if not isinstance(award, dict):
                    self.error_log.record(
                        IngestionError(
                            source_dataset=self.source_dataset,
                            raw_content=json.dumps(award, default=str)[:2000],
                            reason=f"expected an award object, got {type(award).__name__}",
                        )
                    )
                    continue
                missing = [k for k in REQUIRED_FIELDS if k not in award]
                if missing:
                    self.error_log.record(
                        IngestionError(
                            source_dataset=self.source_dataset,
                            raw_content=json.dumps(award, default=str)[:2000],
                            reason="missing required field(s): " + ", ".join(missing),
                        )
                    )
                    continue
                yield SourceRecord(
                    source_dataset=self.source_dataset,
                    retrieval_date=self.retrieval_date,
                    source_record_id=str(award["id"]),
                    fields=award,
                )

            if len(awards) < self.page_size or self.local_file is not None:
                return
            offset += self.page_size
