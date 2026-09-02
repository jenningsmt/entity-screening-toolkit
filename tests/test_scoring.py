from entity_screening.common.schema import MatchStatus, ResolvedEntity, ScreeningHit
from entity_screening.scoring.rubric import STOCK_RUBRIC, rubric_from_dict, rubric_to_dict
from entity_screening.scoring.score import score_entity

ENTITY = ResolvedEntity(
    entity_id="e1", canonical_name="Acme Corp", entity_type="organization", source_records=()
)


def _hit(list_name: str, confidence: float, producer: str = "direct_name") -> ScreeningHit:
    return ScreeningHit(
        entity_id="e1",
        list_name=list_name,
        matched_variant="Acme",
        matched_field="name_variants",
        confidence=confidence,
        evidence={},
        status=MatchStatus.CANDIDATE_MATCH,
        producer=producer,
    )


def test_no_hits_scores_zero_with_no_factors():
    breakdown = score_entity(ENTITY, [])
    assert breakdown.total == 0.0
    assert breakdown.factors == {}


def test_single_hit_produces_a_decomposable_breakdown():
    breakdown = score_entity(ENTITY, [_hit("listA", 0.9)])
    assert breakdown.total > 0
    assert "screening_hit" in breakdown.factors
    assert sum(breakdown.factors.values()) == breakdown.total


def test_multiple_list_hits_add_a_bonus_factor():
    single_list = score_entity(ENTITY, [_hit("listA", 0.9), _hit("listA", 0.85)])
    multi_list = score_entity(ENTITY, [_hit("listA", 0.9), _hit("listB", 0.85)])
    assert "multiple_list_hit_bonus" not in single_list.factors
    assert "multiple_list_hit_bonus" in multi_list.factors
    assert multi_list.total > single_list.total


def test_rubric_weights_are_user_editable():
    custom = rubric_from_dict({"screening_hit_weight": 100.0})
    stock_breakdown = score_entity(ENTITY, [_hit("listA", 0.9)], rubric=STOCK_RUBRIC)
    custom_breakdown = score_entity(ENTITY, [_hit("listA", 0.9)], rubric=custom)
    assert custom_breakdown.total > stock_breakdown.total


def test_rubric_from_dict_falls_back_to_stock_for_invalid_fields():
    rubric = rubric_from_dict({"screening_hit_weight": "not a number", "unknown_field": 5})
    assert rubric == STOCK_RUBRIC


def test_rubric_round_trips_through_dict():
    as_dict = rubric_to_dict(STOCK_RUBRIC)
    assert rubric_from_dict(as_dict) == STOCK_RUBRIC


def test_bibliometric_hit_scores_via_its_own_weight_not_screening_hit_weight():
    """Workstream 5b: a bibliometric hit (a co-author's institution, or a
    PI's own past affiliation, matching a concern-list entry) is a
    second-order signal compared to a direct name match against the entity
    itself, so it scores against bibliometric_hit_weight, not
    screening_hit_weight."""
    breakdown = score_entity(ENTITY, [_hit("listA", 0.9, producer="bibliometric")])
    assert "screening_hit" not in breakdown.factors
    assert breakdown.factors["bibliometric_hit"] == STOCK_RUBRIC.bibliometric_hit_weight * 0.9


def test_direct_and_bibliometric_hits_score_independently_via_separate_factors():
    breakdown = score_entity(
        ENTITY,
        [_hit("listA", 0.9, producer="direct_name"), _hit("listB", 0.85, producer="bibliometric")],
    )
    assert breakdown.factors["screening_hit"] == (
        STOCK_RUBRIC.screening_hit_weight
        * (0.9 * STOCK_RUBRIC.screening_hit_confidence_multiplier)
    )
    assert breakdown.factors["bibliometric_hit"] == STOCK_RUBRIC.bibliometric_hit_weight * 0.85


def test_multiple_list_hit_bonus_does_not_count_bibliometric_hits():
    """A direct OpenSanctions hit plus a bibliometric co-author hit against a
    different list is one direct finding and one second-order inference, not
    'two independent lists corroborate' -- multiple_list_hit_bonus is
    specifically a direct-evidence corroboration signal."""
    mixed = score_entity(
        ENTITY,
        [_hit("listA", 0.9, producer="direct_name"), _hit("listB", 0.85, producer="bibliometric")],
    )
    both_direct = score_entity(
        ENTITY,
        [_hit("listA", 0.9, producer="direct_name"), _hit("listB", 0.85, producer="direct_name")],
    )
    assert "multiple_list_hit_bonus" not in mixed.factors
    assert "multiple_list_hit_bonus" in both_direct.factors
