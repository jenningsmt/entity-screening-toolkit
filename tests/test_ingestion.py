import datetime
import json
from pathlib import Path

from entity_screening.ingestion.base import IngestionErrorLog
from entity_screening.ingestion.dod_1260h import DEFAULT_DATA_FILE, DoD1260HIngester
from entity_screening.ingestion.nsf import NSFAwardIngester
from entity_screening.ingestion.opensanctions import OpenSanctionsTargetsIngester

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_nsf_ingester_streams_records_and_tags_provenance(tmp_path):
    error_log = IngestionErrorLog(tmp_path / "errors.jsonl")
    ingester = NSFAwardIngester(
        error_log,
        local_file=FIXTURES_DIR / "sample_nsf_awards.json",
        retrieval_date=datetime.date(2026, 8, 31),
    )

    records = list(ingester.stream_records())
    error_log.close()

    # 4 awards in the fixture, 1 malformed (missing awardeeName) -> 3 good records
    assert len(records) == 3
    assert all(r.source_dataset == "nsf_award_search" for r in records)
    assert all(r.retrieval_date == datetime.date(2026, 8, 31) for r in records)
    assert all(r.source_record_id for r in records)


def test_nsf_ingester_logs_malformed_records_instead_of_dropping_silently(tmp_path):
    error_log = IngestionErrorLog(tmp_path / "errors.jsonl")
    ingester = NSFAwardIngester(
        error_log,
        local_file=FIXTURES_DIR / "sample_nsf_awards.json",
    )

    list(ingester.stream_records())
    error_log.close()

    assert error_log.count == 1
    logged = [json.loads(line) for line in (tmp_path / "errors.jsonl").read_text().splitlines()]
    assert len(logged) == 1
    assert logged[0]["source_dataset"] == "nsf_award_search"
    assert "missing required field" in logged[0]["reason"]


def test_opensanctions_ingester_streams_and_tags_provenance(tmp_path):
    error_log = IngestionErrorLog(tmp_path / "errors.jsonl")
    ingester = OpenSanctionsTargetsIngester(
        error_log,
        csv_path=FIXTURES_DIR / "sample_opensanctions_targets.csv",
        retrieval_date=datetime.date(2026, 8, 31),
    )

    records = list(ingester.stream_records())
    error_log.close()

    # 3 rows in the fixture, 1 missing `name` -> 2 good records
    assert len(records) == 2
    assert all(r.source_dataset == "opensanctions_targets_simple" for r in records)
    assert error_log.count == 1


def test_dod_1260h_ingester_streams_and_tags_provenance(tmp_path):
    error_log = IngestionErrorLog(tmp_path / "errors.jsonl")
    ingester = DoD1260HIngester(
        error_log, data_file=FIXTURES_DIR / "sample_dod_1260h.json"
    )

    records = list(ingester.stream_records())
    error_log.close()

    # 3 entities in the fixture, 1 missing clean_name -> 2 good records
    assert len(records) == 2
    assert all(r.source_dataset == "dod_section_1260h" for r in records)
    assert error_log.count == 1


def test_dod_1260h_ingester_retrieval_date_defaults_to_curated_at_not_today(tmp_path):
    """This is a static, dated snapshot — the manifest should say when the
    snapshot was captured, not when the pipeline happened to run."""
    error_log = IngestionErrorLog(tmp_path / "errors.jsonl")
    ingester = DoD1260HIngester(
        error_log, data_file=FIXTURES_DIR / "sample_dod_1260h.json"
    )
    error_log.close()

    assert ingester.retrieval_date == datetime.date(2026, 1, 15)


def test_dod_1260h_default_bundled_file_exists_and_parses(tmp_path):
    """Guards against the real, shipped curated list ever going missing or
    developing a syntax error."""
    error_log = IngestionErrorLog(tmp_path / "errors.jsonl")
    ingester = DoD1260HIngester(error_log, data_file=DEFAULT_DATA_FILE)

    records = list(ingester.stream_records())
    error_log.close()

    assert len(records) > 100
    assert error_log.count == 0
