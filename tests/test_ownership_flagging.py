import datetime
import uuid
from pathlib import Path

from entity_screening.common import storage
from entity_screening.common.schema import MatchStatus, ResolvedEntity
from entity_screening.ingestion.base import IngestionErrorLog
from entity_screening.ownership.flagging import compute_foreign_control_flag
from entity_screening.ownership.ingest import load_gleif_level1, load_gleif_level2

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _conn_with_gleif_loaded(tmp_path):
    conn = storage.connect(tmp_path / "test.duckdb")
    error_log = IngestionErrorLog(tmp_path / "errors.jsonl")
    load_gleif_level1(conn, FIXTURES_DIR / "sample_gleif_lei.csv", datetime.date(2026, 8, 1), error_log)
    load_gleif_level2(
        conn, FIXTURES_DIR / "sample_gleif_relationships.csv", datetime.date(2026, 8, 1), error_log
    )
    error_log.close()
    return conn


def _entity(name: str) -> ResolvedEntity:
    return ResolvedEntity(
        entity_id=str(uuid.uuid4()), canonical_name=name, entity_type="organization", source_records=()
    )


def test_positive_foreign_control_case(tmp_path):
    conn = _conn_with_gleif_loaded(tmp_path)
    entity = _entity("Fixture Subsidiary Corp")

    flag = compute_foreign_control_flag(conn, entity)

    assert flag is not None
    assert flag.entity_id == entity.entity_id
    assert flag.entity_jurisdiction == "US"
    assert flag.ultimate_parent_jurisdiction == "DE"
    assert flag.ultimate_parent_lei == "LEI-ULTIMATE-DE"
    assert flag.relationship_path[0] == "LEI-SUB"
    assert flag.relationship_path[-1] == "LEI-ULTIMATE-DE"
    assert flag.status is MatchStatus.CANDIDATE_MATCH
    assert flag.evidence["truncated"] is False
    conn.close()


def test_same_jurisdiction_negative_case(tmp_path):
    conn = _conn_with_gleif_loaded(tmp_path)
    entity = _entity("Fixture Same Country Sub")

    flag = compute_foreign_control_flag(conn, entity)

    assert flag is None
    conn.close()


def test_no_lei_match_case(tmp_path):
    conn = _conn_with_gleif_loaded(tmp_path)
    entity = _entity("Totally Unrelated Name Zzqx")

    flag = compute_foreign_control_flag(conn, entity)

    assert flag is None
    conn.close()


def test_no_known_parent_case(tmp_path):
    conn = _conn_with_gleif_loaded(tmp_path)
    entity = _entity("Fixture No Parent Entity")

    flag = compute_foreign_control_flag(conn, entity)

    assert flag is None
    conn.close()


def test_flag_from_a_truncated_chain_still_fires_but_says_so(tmp_path):
    """A flag from partial evidence is still evidence — but it must say so,
    not assert an unqualified 'confirmed ultimate parent' conclusion.
    LEI-CHAIN-05 (a mid-chain node, DE) differs from the entity's US
    jurisdiction; the real chain continues past it to LEI-CHAIN-11, so
    stopping the walk at depth 5 must report truncated=True even though a
    flag is still correctly produced from what was actually found."""
    conn = _conn_with_gleif_loaded(tmp_path)
    entity = _entity("Fixture Chain Start")

    flag = compute_foreign_control_flag(conn, entity, max_depth=5)

    assert flag is not None
    assert flag.ultimate_parent_lei == "LEI-CHAIN-05"
    assert flag.ultimate_parent_jurisdiction == "DE"
    assert flag.evidence["truncated"] is True
    conn.close()


def test_flag_from_a_complete_chain_reports_truncated_false(tmp_path):
    """The positive-case counterpart: LEI-DIRECT-PARENT (depth 1 from
    LEI-SUB) is US, same as the entity, so no flag fires here — the real
    foreign hit for this entity is confirmed complete (not truncated) in
    test_positive_foreign_control_case above."""
    conn = _conn_with_gleif_loaded(tmp_path)
    entity = _entity("Fixture Subsidiary Corp")

    flag = compute_foreign_control_flag(conn, entity, max_depth=1)

    assert flag is None  # LEI-DIRECT-PARENT (depth 1) is US, same as entity
    conn.close()
