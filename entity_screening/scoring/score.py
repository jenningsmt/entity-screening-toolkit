"""Per-entity scoring: every total decomposes into its contributing factors
on demand (Epic F acceptance criterion) — never an opaque single number.

Every factor below contributes only its single highest-confidence hit, not a
sum or count -- an entity with 1 hit at 0.95 confidence and an entity with 40
hits at 0.95 confidence score identically. This is deliberate, not an
oversight: it stops the bibliometric layer's volume-multiplication (every
co-author's institution across every one of a PI's papers gets checked, not
one entity's own name once) from dominating the ranked table, at the cost of
the table not distinguishing "one strong signal" from "a recurring pattern."
"""
from __future__ import annotations

from collections.abc import Iterable

from entity_screening.common.schema import ForeignControlFlag, ResolvedEntity, ScoreBreakdown, ScreeningHit
from entity_screening.scoring.rubric import STOCK_RUBRIC, ScoringRubric


def score_entity(
    entity: ResolvedEntity,
    hits: Iterable[ScreeningHit],
    rubric: ScoringRubric = STOCK_RUBRIC,
    ownership_flags: Iterable[ForeignControlFlag] = (),
) -> ScoreBreakdown:
    hits = list(hits)
    ownership_flags = list(ownership_flags)
    factors: dict[str, float] = {}

    # Bibliometric hits (a co-author's institution, or a PI's own past
    # affiliation, matching a concern-list entry -- producer="bibliometric")
    # are a second-order signal compared to a direct name match against the
    # entity itself, so they score against their own rubric weight rather
    # than riding screening_hit_weight -- see ScoringRubric.bibliometric_hit_weight.
    direct_hits = [h for h in hits if h.producer != "bibliometric"]
    bibliometric_hits = [h for h in hits if h.producer == "bibliometric"]

    if direct_hits:
        best_hit = max(direct_hits, key=lambda h: h.confidence)
        factors["screening_hit"] = rubric.screening_hit_weight * (
            best_hit.confidence * rubric.screening_hit_confidence_multiplier
        )
        # Counts distinct lists among direct hits only: a direct OpenSanctions
        # hit plus a bibliometric co-author hit against 1260H is one direct
        # finding and one second-order inference, not "two independent lists
        # corroborate" -- multiple_list_hit_bonus is specifically a
        # direct-evidence corroboration signal.
        distinct_lists = {hit.list_name for hit in direct_hits}
        if len(distinct_lists) > 1:
            factors["multiple_list_hit_bonus"] = rubric.multiple_list_hit_bonus

    if bibliometric_hits:
        best_bibliometric_hit = max(bibliometric_hits, key=lambda h: h.confidence)
        factors["bibliometric_hit"] = rubric.bibliometric_hit_weight * best_bibliometric_hit.confidence

    if ownership_flags:
        best_flag = max(ownership_flags, key=lambda f: f.match_confidence)
        # Weighted by the LEI-match confidence itself (Epic C) — a shaky name
        # match to a GLEIF record contributes less than a clean one.
        factors["foreign_control"] = rubric.foreign_control_weight * best_flag.match_confidence

    total = sum(factors.values())
    return ScoreBreakdown(total=total, factors=factors)
