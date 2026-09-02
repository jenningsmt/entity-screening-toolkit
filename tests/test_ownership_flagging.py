import datetime
import uuid
from pathlib import Path

from entity_screening.common import storage
from entity_screening.common.schema import MatchStatus, ResolvedEntity
from entity_screening.ingestion.base import IngestionErrorLog
from entity_screening.ownership.flagging import compute_foreign_control_flag
from entity_screening.ownership.ingest import load_gleif_level1, load_gleif_level2
from entity_screening.ownership.match import resolve_entity_to_lei

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

    flags = compute_foreign_control_flag(conn, entity)

    assert len(flags) == 1
    flag = flags[0]
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

    flags = compute_foreign_control_flag(conn, entity)

    assert flags == []
    conn.close()


def test_no_lei_match_case(tmp_path):
    conn = _conn_with_gleif_loaded(tmp_path)
    entity = _entity("Totally Unrelated Name Zzqx")

    flags = compute_foreign_control_flag(conn, entity)

    assert flags == []
    conn.close()


def test_no_known_parent_case(tmp_path):
    conn = _conn_with_gleif_loaded(tmp_path)
    entity = _entity("Fixture No Parent Entity")

    flags = compute_foreign_control_flag(conn, entity)

    assert flags == []
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

    flags = compute_foreign_control_flag(conn, entity, max_depth=5)

    assert len(flags) == 1
    flag = flags[0]
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

    flags = compute_foreign_control_flag(conn, entity, max_depth=1)

    assert flags == []  # LEI-DIRECT-PARENT (depth 1) is US, same as entity
    conn.close()


def test_flag_from_match_emits_one_flag_per_distinct_foreign_ultimate_parent(tmp_path):
    """Finding 7's direct regression: a branching graph must produce one
    ForeignControlFlag per distinct foreign ultimate parent, not a single
    flag with an arbitrarily-picked parent and a relationship_path that is
    an ordering artifact rather than a path that exists in the data."""
    from entity_screening.ownership.flagging import flag_from_match
    from entity_screening.ownership.ingest import load_gleif_level2

    conn = storage.connect(tmp_path / "test.duckdb")
    error_log = IngestionErrorLog(tmp_path / "errors.jsonl")
    load_gleif_level1(conn, FIXTURES_DIR / "sample_gleif_lei.csv", datetime.date(2026, 8, 1), error_log)
    # load_gleif_level2 does CREATE OR REPLACE TABLE (a disposable working
    # copy, rebuilt on every call -- see its own docstring), so a second call
    # would wipe the first rather than add to it. Combine the base fixture's
    # relationships with the new branch in one CSV, loaded in one call.
    combined_csv = tmp_path / "combined_relationships.csv"
    base_rows = (FIXTURES_DIR / "sample_gleif_relationships.csv").read_text(encoding="utf-8")
    combined_csv.write_text(
        base_rows.rstrip("\n") + "\n"
        "LEI-SUB,LEI-BRANCH-P2,IS_DIRECTLY_CONSOLIDATED_BY,ACTIVE\n"
        "LEI-BRANCH-P2,LEI-BRANCH-TOPB,IS_DIRECTLY_CONSOLIDATED_BY,ACTIVE\n",
        encoding="utf-8",
    )
    load_gleif_level2(conn, combined_csv, datetime.date(2026, 8, 1), error_log)
    error_log.close()
    # Give the new branch's leaf entities a jurisdiction so a flag can fire.
    # flag_from_match only ever selects (legal_name, legal_jurisdiction) by
    # LEI for the ultimate-parent lookup, so only those columns matter here.
    conn.execute(
        "INSERT INTO gleif_lei (lei, legal_name, legal_jurisdiction) VALUES "
        "('LEI-BRANCH-P2', 'Fixture Branch Parent 2', 'US'), "
        "('LEI-BRANCH-TOPB', 'Fixture Branch Ultimate B', 'FR')"
    )

    match = resolve_entity_to_lei(conn, "e1", "Fixture Subsidiary Corp", 0.80)
    assert match is not None
    flags = flag_from_match(conn, match)

    assert len(flags) == 2
    ultimate_leis = {f.ultimate_parent_lei for f in flags}
    assert ultimate_leis == {"LEI-ULTIMATE-DE", "LEI-BRANCH-TOPB"}
    jurisdictions = {f.ultimate_parent_lei: f.ultimate_parent_jurisdiction for f in flags}
    assert jurisdictions == {"LEI-ULTIMATE-DE": "DE", "LEI-BRANCH-TOPB": "FR"}
    conn.close()
