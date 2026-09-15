"""Epic J's types -- evidence-grounded explanation of a flagged match.

A new capability layer over the existing observation graph
(`Finding`/`ConcernTie` in `common/schema.py`, `ScreeningMatch` in
`screening/rps_schema.py`), not a new member of it -- kept in its own module
for the same reason `screening/` is separate from `common/schema.py`: this
project's layering has `common/schema.py` stay ignorant of anything built on
top of it.

The fact/judgment boundary applies here with one addition the rest of the
observation graph doesn't need, because this is the first type in this
project whose fields hold free text rather than only structured data:
`MatchExplanation.recitation` is fully templated in Python
(`explanation/skeletons.py`) from typed fields and carries no risk of
evaluative drift by construction, the same as everything else in this
codebase. `synthesis_sentence` is the one field that did not come from a
template -- a short, LLM-generated sentence connecting several evidence
items. Its risk is content-level, not field-name-level, so
`EXPLANATION_ALLOWED_FIELDS` below (checked by `cli.py validate`, mirroring
`_OBSERVATION_GRAPH_ALLOWED_FIELDS`/`RPS_OBSERVATION_ALLOWED_FIELDS`) guards
against a new *field* like `severity`/`disposition` being added later, but it
cannot see inside a string. The content guarantee is enforced here instead,
in `__post_init__`, the same "unrepresentable, not merely discouraged"
discipline `Subject.synthetic`/`Declaration.synthetic` already use: a
`MatchExplanation` whose `synthesis_sentence` fails
`explanation/lexicon.py:is_clean`, or that carries a `synthesis_sentence`
with no supporting `citations`, cannot be constructed at all. A caller with a
sentence that doesn't clear this bar must pass `synthesis_sentence=None`
(recitation-only is a complete, valid explanation, not a failure state) --
see `explanation/generate.py` for where that decision is made.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from entity_screening.explanation.lexicon import is_clean


class ObservationKind(Enum):
    """Which observation-graph type a MatchExplanation is about. Extending
    this to `screening_match`/`screening_hit` (RPS, the batch pipeline) is
    the deferred UI/route wiring this plan's Scope decision describes --
    the generation/verification core below already takes any of the four,
    unmodified."""

    FINDING = "finding"
    CONCERN_TIE = "concern_tie"


@dataclass(frozen=True)
class Citation:
    """One resolved citation from a synthesis sentence back into the
    evidence document Claude was given -- computed by the Claude API's own
    document-citation feature against the literal document text, not
    self-reported by the model (explanation/generate.py)."""

    cited_text: str
    start_char: int
    end_char: int


@dataclass(frozen=True)
class MatchExplanation:
    """One explanation of one flagged match: `case_id`'s `observation_kind`/
    `observation_id` (a `finding_id` or `tie_id`), a fully templated
    `recitation`, and at most one LLM-generated `synthesis_sentence` with
    its resolved `citations`. `evidence_hash` is this explanation's cache
    key (`explanation/service.py`) -- a re-run of reconciliation
    regenerates `finding_id`/`tie_id` (uuid4) on every run, so a stale
    explanation is never looked up again by construction, the same
    current-state-per-case discipline `case/store.py:replace_findings`
    already relies on.

    `synthetic` is propagated from the case/subject, exactly like
    `case/export.py`'s `PROVENANCE_NOTICE` -- a free-text paragraph about a
    fabricated demo subject needs this marker *more*, not less, than the
    JSON export does (use-case-01 Section 10's "no fabricated publications
    attached to a real name" concern is sharper in prose than in a JSON
    blob).
    """

    explanation_id: str
    observation_kind: ObservationKind
    observation_id: str
    case_id: str
    recitation: str
    synthesis_sentence: str | None
    citations: tuple[Citation, ...]
    evidence_hash: str
    model: str
    prompt_version: str
    generated_at: str
    synthetic: bool

    def __post_init__(self) -> None:
        if self.synthesis_sentence is None:
            if self.citations:
                raise ValueError(
                    "MatchExplanation.citations must be empty when "
                    "synthesis_sentence is None -- a citation with nothing to "
                    "ground is not representable."
                )
            return
        if not is_clean(self.synthesis_sentence):
            raise ValueError(
                "MatchExplanation.synthesis_sentence failed the forbidden-"
                "vocabulary check (explanation/lexicon.py) -- a non-conforming "
                "sentence must never be constructed, not stored with a warning "
                "flag. Pass synthesis_sentence=None instead (see "
                "explanation/generate.py)."
            )
        if not self.citations:
            raise ValueError(
                "MatchExplanation.synthesis_sentence is set but citations is "
                "empty -- an ungrounded sentence must never be constructed. "
                "Pass synthesis_sentence=None instead."
            )


# Frozen allowlist, checked by cli.py validate alongside
# _OBSERVATION_GRAPH_ALLOWED_FIELDS/RPS_OBSERVATION_ALLOWED_FIELDS -- guards
# against a future field-name regression (a `severity`/`disposition` field
# added later); the content-level guarantee for `synthesis_sentence` itself
# lives in __post_init__ above, not here.
EXPLANATION_ALLOWED_FIELDS: dict[str, frozenset[str]] = {
    "MatchExplanation": frozenset(
        {
            "explanation_id",
            "observation_kind",
            "observation_id",
            "case_id",
            "recitation",
            "synthesis_sentence",
            "citations",
            "evidence_hash",
            "model",
            "prompt_version",
            "generated_at",
            "synthetic",
        }
    ),
    "Citation": frozenset({"cited_text", "start_char", "end_char"}),
}
