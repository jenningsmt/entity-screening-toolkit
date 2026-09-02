import uuid

from entity_screening.common.schema import MatchStatus, ResolvedEntity, SourceRecord
from entity_screening.screening.lists import DoD1260HList, OpenSanctionsList
from entity_screening.screening.screen import screen_entity
import datetime


def _source_record(record_id: str, name: str, aliases: str = "") -> SourceRecord:
    return SourceRecord(
        source_dataset="opensanctions_targets_simple",
        retrieval_date=datetime.date(2026, 1, 1),
        source_record_id=record_id,
        fields={"id": record_id, "schema": "Company", "name": name, "aliases": aliases},
    )


def _dod_1260h_record(record_id: str, clean_name: str, aliases: list | None = None) -> SourceRecord:
    return SourceRecord(
        source_dataset="dod_section_1260h",
        retrieval_date=datetime.date(2026, 1, 1),
        source_record_id=record_id,
        fields={
            "id": record_id,
            "clean_name": clean_name,
            "aliases": aliases or [],
            "parent_name": "",
            "earliest_start_date": "2021-06-03",
        },
    )


def _entity(name: str) -> ResolvedEntity:
    return ResolvedEntity(
        entity_id=str(uuid.uuid4()), canonical_name=name, entity_type="organization",
        source_records=(),
    )


def test_screen_entity_finds_a_hit_via_alias():
    concern_list = OpenSanctionsList(
        [_source_record("os-1", "ZTE Corporation", aliases="Zhongxing Telecommunication Equipment Corporation")]
    )
    entity = _entity("Zhongxing Telecommunication Equipment Corporation")

    hits = list(screen_entity(entity, [concern_list]))

    assert len(hits) == 1
    hit = hits[0]
    assert hit.list_name == "opensanctions_consolidated"
    assert hit.status is MatchStatus.CANDIDATE_MATCH
    assert hit.evidence["entry_id"] == "os-1"


def test_screen_entity_no_hit_for_unrelated_name():
    concern_list = OpenSanctionsList([_source_record("os-1", "ZTE Corporation")])
    entity = _entity("Springfield State University")

    hits = list(screen_entity(entity, [concern_list]))

    assert hits == []


def test_screen_entity_never_produces_a_confirmed_status():
    concern_list = OpenSanctionsList([_source_record("os-1", "Springfield State University")])
    entity = _entity("Springfield State University")

    hits = list(screen_entity(entity, [concern_list]))

    assert len(hits) == 1
    assert all(hit.status is MatchStatus.CANDIDATE_MATCH for hit in hits)


def test_blocking_does_not_drop_a_true_match_outside_default_block():
    """Regression for Finding 1: 'Acme Corp' vs 'Acme Corporation' normalize to
    the *same* 3-char block ('acm...'), so the original version of this test
    passed even with the acronym-blocking defect fully present -- it never
    exercised the cross-block case its name promised. A genuine acronym pair
    shares no name-prefix at all ('int...' vs 'ibm'), which is exactly the
    case that was unreachable before this workstream's fix to
    screening/lists.py's block index."""
    concern_list = OpenSanctionsList([_source_record("os-1", "IBM")])
    entity = _entity("International Business Machines Corporation")

    hits = list(screen_entity(entity, [concern_list]))

    assert len(hits) == 1
    assert hits[0].evidence["match_basis"] == "acronym"


def test_evidence_is_self_contained_without_a_further_join():
    """docs/requirements.md Section 9a: evidence must be usable as LLM retrieval
    context (Epic J) without a separate lookup back to the source list."""
    concern_list = OpenSanctionsList([_source_record("os-1", "ZTE Corporation")])
    entity = _entity("ZTE Corporation")

    hits = list(screen_entity(entity, [concern_list]))

    assert len(hits) == 1
    matched_fields = hits[0].evidence["matched_entry_fields"]
    assert matched_fields["name"] == "ZTE Corporation"
    assert matched_fields["id"] == "os-1"


def test_dod_1260h_list_finds_a_hit_via_alias():
    concern_list = DoD1260HList(
        [_dod_1260h_record("1260h-1", "Huawei Technologies Co., Ltd.", aliases=["Huawei"])]
    )
    entity = _entity("Huawei")

    hits = list(screen_entity(entity, [concern_list]))

    assert len(hits) == 1
    assert hits[0].list_name == "dod_section_1260h"
    assert hits[0].status is MatchStatus.CANDIDATE_MATCH


def test_dod_1260h_list_evidence_is_self_contained():
    concern_list = DoD1260HList(
        [_dod_1260h_record("1260h-1", "Huawei Technologies Co., Ltd.", aliases=["Huawei"])]
    )
    entity = _entity("Huawei Technologies Co., Ltd.")

    hits = list(screen_entity(entity, [concern_list]))

    assert len(hits) == 1
    matched_fields = hits[0].evidence["matched_entry_fields"]
    assert matched_fields["clean_name"] == "Huawei Technologies Co., Ltd."
    assert matched_fields["id"] == "1260h-1"


def test_screening_checks_both_registered_lists_and_tags_which_produced_each_hit():
    opensanctions_list = OpenSanctionsList([_source_record("os-1", "Springfield State University")])
    dod_list = DoD1260HList([_dod_1260h_record("1260h-1", "Huawei Technologies Co., Ltd.", aliases=["Huawei"])])
    entity = _entity("Huawei")

    hits = list(screen_entity(entity, [opensanctions_list, dod_list]))

    assert len(hits) == 1
    assert hits[0].list_name == "dod_section_1260h"
