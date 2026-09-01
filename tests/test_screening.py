import uuid

from entity_screening.common.schema import MatchStatus, ResolvedEntity, SourceRecord
from entity_screening.screening.lists import OpenSanctionsList
from entity_screening.screening.screen import screen_entity
import datetime


def _source_record(record_id: str, name: str, aliases: str = "") -> SourceRecord:
    return SourceRecord(
        source_dataset="opensanctions_targets_simple",
        retrieval_date=datetime.date(2026, 1, 1),
        source_record_id=record_id,
        fields={"id": record_id, "schema": "Company", "name": name, "aliases": aliases},
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
    concern_list = OpenSanctionsList([_source_record("os-1", "Acme Corp")])
    entity = _entity("Acme Corporation")

    hits = list(screen_entity(entity, [concern_list]))

    assert len(hits) == 1


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
