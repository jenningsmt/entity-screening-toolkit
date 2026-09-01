"""Per-entity scoring: every total decomposes into its contributing factors
on demand (Epic F acceptance criterion) — never an opaque single number."""
from __future__ import annotations

from collections.abc import Iterable

from entity_screening.common.schema import ResolvedEntity, ScoreBreakdown, ScreeningHit
from entity_screening.scoring.rubric import STOCK_RUBRIC, ScoringRubric


def score_entity(
    entity: ResolvedEntity,
    hits: Iterable[ScreeningHit],
    rubric: ScoringRubric = STOCK_RUBRIC,
) -> ScoreBreakdown:
    hits = list(hits)
    factors: dict[str, float] = {}

    if hits:
        best_hit = max(hits, key=lambda h: h.confidence)
        factors["screening_hit"] = rubric.screening_hit_weight * (
            best_hit.confidence * rubric.screening_hit_confidence_multiplier
        )
        distinct_lists = {hit.list_name for hit in hits}
        if len(distinct_lists) > 1:
            factors["multiple_list_hit_bonus"] = rubric.multiple_list_hit_bonus

    total = sum(factors.values())
    return ScoreBreakdown(total=total, factors=factors)
