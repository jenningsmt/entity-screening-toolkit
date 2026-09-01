"""Screens resolved entities against every registered entity-of-concern list.

Every hit is tagged with which list produced it and the specific matched
name variant (Epic D acceptance criteria), and every hit's status is
MatchStatus.CANDIDATE_MATCH — common/schema.py's MatchStatus enum makes any
other status unrepresentable.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator

from entity_screening.common.schema import MatchStatus, ResolvedEntity, ScreeningHit
from entity_screening.resolution.matcher import DEFAULT_THRESHOLD, is_candidate_match, score_pair
from entity_screening.screening.lists import EntityOfConcernList


def screen_entity(
    entity: ResolvedEntity,
    concern_lists: Iterable[EntityOfConcernList],
    threshold: float = DEFAULT_THRESHOLD,
) -> Iterator[ScreeningHit]:
    for concern_list in concern_lists:
        for entry in concern_list.candidates_for(entity.canonical_name):
            best_candidate = None
            for variant in entry.name_variants:
                candidate = score_pair(entity.canonical_name, variant)
                if best_candidate is None or candidate.confidence > best_candidate.confidence:
                    best_candidate = candidate
            if best_candidate is None or not is_candidate_match(best_candidate, threshold):
                continue
            yield ScreeningHit(
                entity_id=entity.entity_id,
                list_name=concern_list.list_name,
                matched_variant=best_candidate.right_name,
                matched_field="name_variants",
                confidence=best_candidate.confidence,
                evidence={
                    "entry_id": entry.entry_id,
                    "match_basis": best_candidate.match_basis,
                    "entity_type": entry.entity_type,
                },
                status=MatchStatus.CANDIDATE_MATCH,
            )
