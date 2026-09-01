import datetime
import uuid

from entity_screening.common.schema import ResolvedEntity, SourceRecord
from entity_screening.screening.lists import OpenSanctionsList
from entity_screening.screening.section_117 import (
    LIST_NAME,
    cross_check_section_117,
    extract_named_foreign_entity,
)


def _section_117_record(record_id: str, **fields) -> SourceRecord:
    base = {
        "OPEID": "00100000",
        "State": "ZZ",
        "Transaction Type": "Restricted Contract",
        "Foreign Government Source": "Yes",
        "Attribution Country": "Fixlandia",
        "Amount": 50000,
        "Receipt Date": "2024-01-01",
    }
    base.update(fields)
    return SourceRecord(
        source_dataset="section_117_foreign_funding_disclosure",
        retrieval_date=datetime.date(2026, 1, 1),
        source_record_id=record_id,
        fields=base,
    )


def _os_record(record_id: str, name: str) -> SourceRecord:
    return SourceRecord(
        source_dataset="opensanctions_targets_simple",
        retrieval_date=datetime.date(2026, 1, 1),
        source_record_id=record_id,
        fields={"id": record_id, "schema": "Company", "name": name, "aliases": ""},
    )


def _entity(name: str) -> ResolvedEntity:
    return ResolvedEntity(
        entity_id=str(uuid.uuid4()), canonical_name=name, entity_type="organization",
        source_records=(),
    )


def test_extract_named_foreign_entity_prefers_legal_name_when_both_populated():
    """Real data: 5,569 of 5,576 real named rows have BOTH Legal Name and
    Government Name populated, and Government Name is consistently just the
    country ("Kuwait") while Legal Name is the specific entity ("Kuwait
    Embassy") -- not two competing aliases."""
    record = _section_117_record(
        "r1",
        **{
            "Restricted Transaction Foreign Government Legal Name": "Kuwait Embassy",
            "Restricted Transaction Foreign Government Name": "Kuwait",
        },
    )
    assert extract_named_foreign_entity(record) == "Kuwait Embassy"


def test_extract_named_foreign_entity_falls_back_to_government_name():
    record = _section_117_record(
        "r2", **{"Restricted Transaction Foreign Government Name": "Kuwait"}
    )
    assert extract_named_foreign_entity(record) == "Kuwait"


def test_extract_named_foreign_entity_falls_back_to_owner_name():
    record = _section_117_record("r3", **{"Foreign Source Owner Name": "Fixture Holding Co"})
    assert extract_named_foreign_entity(record) == "Fixture Holding Co"


def test_extract_named_foreign_entity_returns_none_for_country_only_row():
    record = _section_117_record("r4", **{"Transaction Type": "Gift"})
    assert extract_named_foreign_entity(record) is None


def test_cross_check_finds_a_hit_when_both_stages_clear_threshold():
    entity = _entity("Fixture State University")
    section_117_records = [
        _section_117_record(
            "r1",
            **{
                "School Name": "Fixture State University",
                "Restricted Transaction Foreign Government Legal Name": "Fixture Sovereign Wealth Fund",
                "Restricted Transaction Foreign Government Name": "Fixlandia",
            },
        )
    ]
    concern_lists = [OpenSanctionsList([_os_record("os-1", "Fixture Sovereign Wealth Fund")])]

    hits = list(cross_check_section_117(entity, section_117_records, concern_lists))

    assert len(hits) == 1
    hit = hits[0]
    assert hit.list_name == LIST_NAME
    assert hit.confidence == 1.0  # funder-match confidence, not blended with institution match
    assert hit.evidence["institution_match"]["confidence"] == 1.0
    assert hit.evidence["disclosure"]["government_name"] == "Fixlandia"


def test_cross_check_governance_affix_lets_a_legal_name_variant_still_match():
    """The entity is resolved from NSF data under its governing-board legal
    name; Section 117's School Name uses the common name. Without the
    governance-affix fix this pair scores 0.72 and lands in a different
    block (see resolution/normalize.py's strip_institutional_governance_affix
    docstring) -- this proves the cross-check's blocking/scoring stage
    actually applies that fix, not just the standalone normalize function."""
    entity = _entity("Regents of the University of Idaho")
    section_117_records = [
        _section_117_record(
            "r1",
            **{
                "School Name": "University of Idaho",
                "Restricted Transaction Foreign Government Legal Name": "Fixture Sovereign Wealth Fund",
            },
        )
    ]
    concern_lists = [OpenSanctionsList([_os_record("os-1", "Fixture Sovereign Wealth Fund")])]

    hits = list(cross_check_section_117(entity, section_117_records, concern_lists))

    assert len(hits) == 1


def test_cross_check_no_hit_when_institution_threshold_not_cleared():
    entity = _entity("Fixture State University")
    section_117_records = [
        _section_117_record(
            "r1",
            **{
                "School Name": "Nonexistent Institute of Nowhere",
                "Restricted Transaction Foreign Government Legal Name": "Fixture Sovereign Wealth Fund",
            },
        )
    ]
    concern_lists = [OpenSanctionsList([_os_record("os-1", "Fixture Sovereign Wealth Fund")])]

    hits = list(cross_check_section_117(entity, section_117_records, concern_lists))

    assert hits == []


def test_cross_check_no_hit_for_country_only_disclosure():
    """Proves the ~95% real-data case (no named entity, only a country) is
    correctly excluded, not silently mismatched against something."""
    entity = _entity("Fixture State University")
    section_117_records = [
        _section_117_record(
            "r1", **{"School Name": "Fixture State University", "Transaction Type": "Gift"}
        )
    ]
    concern_lists = [OpenSanctionsList([_os_record("os-1", "Fixture Sovereign Wealth Fund")])]

    hits = list(cross_check_section_117(entity, section_117_records, concern_lists))

    assert hits == []


def test_cross_check_no_hit_when_funder_does_not_match_any_concern_list():
    entity = _entity("Fixture State University")
    section_117_records = [
        _section_117_record(
            "r1",
            **{
                "School Name": "Fixture State University",
                "Restricted Transaction Foreign Government Legal Name": "Totally Unrelated Entity",
            },
        )
    ]
    concern_lists = [OpenSanctionsList([_os_record("os-1", "Fixture Sovereign Wealth Fund")])]

    hits = list(cross_check_section_117(entity, section_117_records, concern_lists))

    assert hits == []


def test_cross_check_owner_name_path_produces_a_hit():
    """The rare foreign-ownership-of-institution disclosure type (~5 real rows)."""
    entity = _entity("Fixture State University")
    section_117_records = [
        _section_117_record(
            "r1",
            **{
                "School Name": "Fixture State University",
                "Transaction Type": "Real Estate",
                "Institution Owned by Foreign Source": "Yes",
                "Foreign Source Owner Name": "Fixture Sovereign Wealth Fund",
            },
        )
    ]
    concern_lists = [OpenSanctionsList([_os_record("os-1", "Fixture Sovereign Wealth Fund")])]

    hits = list(cross_check_section_117(entity, section_117_records, concern_lists))

    assert len(hits) == 1
