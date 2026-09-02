"""User-editable scoring rubric — mirrors the sibling project ed-colony-scout's
dataclass rubric pattern (frozen dataclass of weights, dict round-trip for
user overrides), adapted from that project's Tkinter dialog to this project's
Streamlit sliders / JSON override file.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace


@dataclass(frozen=True)
class ScoringRubric:
    """Weights are the only thing a user edits; the scoring formula itself
    (scoring/score.py) is fixed code."""

    screening_hit_weight: float = 50.0
    screening_hit_confidence_multiplier: float = 1.0
    multiple_list_hit_bonus: float = 20.0
    foreign_control_weight: float = 30.0
    # Half of screening_hit_weight by default -- a bibliometric hit (a
    # co-author's institution, or a PI's past affiliation, matching a
    # concern-list entry) is a second-order signal compared to a direct
    # name match against the entity itself, and Epic F's "change the
    # weighting if I disagree with it" needs its own adjustable weight to
    # let an analyst express exactly that disagreement (scoring/score.py
    # partitions hits by producer to apply this separately). 25.0 is a
    # defensible starting point, not a claimed-correct value -- the point
    # is that it's now adjustable at all.
    bibliometric_hit_weight: float = 25.0


STOCK_RUBRIC = ScoringRubric()


def rubric_to_dict(rubric: ScoringRubric) -> dict:
    return asdict(rubric)


def rubric_from_dict(data: dict) -> ScoringRubric:
    """Builds a rubric from a partial dict, falling back to stock defaults for
    any missing or invalid field (defensive coercion, mirroring ed-colony-scout)."""
    kwargs = {}
    for f in fields(STOCK_RUBRIC):
        value = data.get(f.name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            kwargs[f.name] = float(value)
    return replace(STOCK_RUBRIC, **kwargs)
