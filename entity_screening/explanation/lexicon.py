"""The forbidden-vocabulary check for Epic J's one generated sentence.

`common/schema.py:_FORBIDDEN_OBSERVATION_FIELD_TOKENS` already bans
"severity"/"risk"/"priority"/"tier"/"disqualif..."/etc. as *field names* on an
observation type -- but a field-name check cannot see inside a free-text
string. This module is the prose equivalent: a `synthesis_sentence` is
supposed to state a fact connecting several evidence items, never evaluate
it, and the words below are exactly how that evaluation tends to leak in
even when every underlying claim is true and correctly cited.

Seeded from first-hand knowledge of how models in this family phrase
evidence-based claims when unconstrained -- NOT yet calibrated against a
real model's actual output on this project's real evidence (no
ANTHROPIC_API_KEY was available while this module was designed; see
docs/plans/<date>-epic-j-evidence-grounded-explanation.md's Real-data
research section). tests/test_explanation_real_model.py is where that
calibration actually happens, the first time it runs for real, and this
list should be revisited then rather than treated as final.
"""
from __future__ import annotations

import re

from entity_screening.common.schema import _FORBIDDEN_OBSERVATION_FIELD_TOKENS

# Multi-word and single-word evaluative phrases a synthesis sentence must
# never contain, regardless of whether every fact in it is true and cited.
# Distinct from _FORBIDDEN_OBSERVATION_FIELD_TOKENS: these are prose judgment
# markers, not field-name substrings, and several (e.g. "significant",
# "should") are only forbidden in an evaluative sense that a substring check
# cannot fully disambiguate from a measurement/procedural one -- flagged
# below, not silently assumed correct.
FORBIDDEN_EXPLANATION_PHRASES: tuple[str, ...] = (
    "concerning",
    "suspicious",
    "alarming",
    "troubling",
    "problematic",
    "significant",
    "clearly indicates",
    "clearly shows",
    "strongly suggests",
    "likely indicates",
    "raises questions about",
    "raises concerns",
    "of particular concern",
    "notably,",
    "importantly,",
    "worth noting that",
    "red flag",
    "warning sign",
)

# Judgment modals: forbidden only when the sentence's grammatical subject
# reads as the person/entity rather than a procedural next step ("the
# analyst should review" is a workflow instruction, not a judgment about the
# person -- this module does not attempt that disambiguation; it flags the
# bare token and leaves the analyst/generation-time reviewer to confirm, the
# same "state only what's checkable, don't overclaim" discipline as
# ScopeKind's HIGHEST_ONLY case in reconciliation/reconcile.py).
FORBIDDEN_JUDGMENT_MODALS: tuple[str, ...] = ("should", "warrants", "must")


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def find_violations(sentence: str) -> list[str]:
    """Every forbidden phrase/token actually present in `sentence`, for
    reporting -- not just a bool, so a rejected generation attempt can log
    *why* rather than being a silent retry."""
    lowered = sentence.lower()
    hits = [p for p in FORBIDDEN_EXPLANATION_PHRASES if p in lowered]
    words = set(_tokens(sentence))
    hits += [m for m in FORBIDDEN_JUDGMENT_MODALS if m in words]
    hits += [
        t
        for t in _FORBIDDEN_OBSERVATION_FIELD_TOKENS
        if any(t in w for w in words)
    ]
    return hits


def is_clean(sentence: str) -> bool:
    """True if `sentence` contains none of the forbidden vocabulary above.
    Deterministic, no model call -- the mechanical half of Epic J's
    grounding-and-lexicon gate (the other half is citation resolution,
    explanation/generate.py)."""
    return not find_violations(sentence)
