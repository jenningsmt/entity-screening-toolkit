"""Restricted-party screening (RPS) types -- Use Case 02, step 5.

A deliberately separate object graph from the HB 127 case model
(`common/schema.py`'s `Case`/`Subject`/`Declaration`/`Finding`/`ConcernTie`),
not a reuse of it. Two structural reasons, both load-bearing (see
`docs/use-case-02-restricted-party-screening.md` and
`docs/plans/2026-09-14-restricted-party-screening.md`):

1. RPS's real trigger population (a hire, a visiting-scholar invitation, a
   purchase/payment) is broader than HB 127's single "hire a covered person"
   trigger -- purchasing/financial has no case, no subject, no declaration,
   just a one-off counterparty. Reusing `Case`/`Subject`/`Declaration` would
   either force a fake case onto a purchase or quietly narrow the type back
   toward the two triggers that do happen to look case-shaped.
2. `ConcernTie`'s own docstring ties it explicitly to Sec. 51B.151(b) --
   reusing it here would misdescribe what the field means.

**Explicit scope boundary, stated here so it cannot be silently
rediscovered:** `ScreeningParty.country` is captured for display and
evidence only. It is **never** checked against OFAC's comprehensively
embargoed countries (Cuba, Iran, North Korea, Syria, Venezuela) or any other
country-level gate. Restricted-party screening, as built here, is
name-against-entity-list matching only -- a person or organization *name*
against the government's restricted/denied/debarred-party lists. OFAC
country-of-nationality screening is a structurally different legal test
(use-case-02 Section 1, Section 6) and stays entirely unimplemented, not
partially covered under a misleading label.

**Also out of scope, permanently, not deferred:** export-control
jurisdiction, classification, and licensing determinations (whether an item
is EAR/ITAR-controlled, whether the Fundamental Research Exclusion applies,
whether a license is required) -- a case-by-case legal/technical judgment
call for a trained export control officer, not a fact this system can state
(use-case-02 Section 1, "problem (2)").
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from entity_screening.common.schema import MatchStatus, WorksheetActionKind


class ScreeningTrigger(Enum):
    """Which real-world event created this ScreeningEvent. A separate enum
    from HB 127's CoverageBasis -- CoverageBasis is a legal coverage basis
    under Sec. 51B.151(a); this is a trigger-event type, a different kind of
    fact entirely."""

    FOREIGN_PERSON_HIRE = "foreign_person_hire"
    VISITING_SCHOLAR = "visiting_scholar"
    PURCHASING_FINANCIAL = "purchasing_financial"


class PartyKind(Enum):
    PERSON = "person"
    ORGANIZATION = "organization"


@dataclass(frozen=True)
class ScreeningEvent:
    """One trigger event requiring restricted-party screening.

    `case_id` links to an existing HB 127 `Case` when the same real-world
    event already created one (a hire, a visiting-scholar invitation --
    TAMU's own Form 5VS triggers both processes, per use-case-02 Section 5);
    always `None` for purchasing/financial, which has no case-shaped
    counterpart at all. This is a **display-only join key** -- it does not
    fold RPS matches into the HB 127 worksheet, and no code should treat it
    as one.

    `synthetic` mirrors `Subject`/`Declaration`'s "no real PII by
    construction" guard: this build handles no real screening data of any
    kind (see `__post_init__`).
    """

    event_id: str
    trigger: ScreeningTrigger
    case_id: str | None
    requested_by: str
    requested_at: str
    synthetic: bool

    def __post_init__(self) -> None:
        if self.synthetic is not True:
            raise ValueError(
                "ScreeningEvent.synthetic must be True -- this build handles no "
                "real restricted-party-screening data (use-case-01 Section 9's "
                "no-real-PII-by-construction discipline, extended here)."
            )


@dataclass(frozen=True)
class ScreeningParty:
    """One person or organization name to screen within one ScreeningEvent.

    A hire produces at least two rows (the person; their current employer)
    and up to several more (prior affiliations going back five years,
    personal/professional references) -- TAMU's real documented practice,
    not a hypothetical -- each independently screened and each with its own
    match history, never a list buried in one field."""

    party_id: str
    event_id: str
    kind: PartyKind
    name: str
    country: str | None
    role_in_event: str  # "subject" | "current_employer" | "prior_affiliation" | "reference" | "counterparty"


@dataclass(frozen=True)
class ScreeningMatch:
    """A candidate match between a ScreeningParty and a restricted-party-list
    entry. Same shape as `common.schema.ScreeningHit`/`ConcernTie`'s
    evidence -- confidence-scored, evidence-carrying, `MatchStatus`-typed,
    never a bare boolean. `list_name` and `evidence["matched_entry_fields"]`
    carry the OpenSanctions `program_ids` value (e.g. `"US-BIS-EL"`) so a
    match states which specific government list produced it, not just
    "OpenSanctions" -- see `entity_screening/screening/rps_screen.py`.

    `matched_field` (M14, Epic D's "matched name variant, matched field"
    acceptance criterion) is the matched party's own `role_in_event`
    ("subject" | "current_employer" | "prior_affiliation" | "reference" |
    "counterparty") -- RPS's structural equivalent of
    `common.schema.ScreeningHit.matched_field`, telling a reviewer which
    real-world role produced the match without a separate join back to
    the party record."""

    match_id: str
    party_id: str
    matched_variant: str
    matched_field: str
    list_name: str
    confidence: float
    evidence: dict[str, Any]
    status: MatchStatus


# The fact/judgment boundary (use-case-01 Section 4, extended to RPS by
# use-case-02 Section 3): ScreeningMatch states an observable fact -- a name
# matched a list entry at some confidence -- and never evaluates it. Checked
# by cli.py `validate`, the same mechanism common/schema.py's
# _OBSERVATION_GRAPH_ALLOWED_FIELDS uses for Finding/ConcernTie, kept as its
# own dict here rather than added to that one so common/schema.py never has
# to import from screening/ (see this module's docstring). ScreeningDisposition
# is deliberately NOT covered by this guard -- like WorksheetAction/TieAction,
# it is where the human's own conclusion is recorded (in reason_code/
# reason_note), the right side of the fact/judgment line.
RPS_OBSERVATION_ALLOWED_FIELDS: dict[str, frozenset[str]] = {
    "ScreeningMatch": frozenset(
        {
            "match_id", "party_id", "matched_variant", "matched_field",
            "list_name", "confidence", "evidence", "status",
        }
    ),
}


@dataclass(frozen=True)
class ScreeningDisposition:
    """One RESEC-equivalent disposition of one ScreeningMatch. Reuses
    `WorksheetActionKind` (dismiss/escalate/etc. -- the action vocabulary
    itself is not RPS-specific) with its own reason-code vocabulary
    (`case/vocab.py`: `RPS_DISMISS_REASON_CODES` / `RPS_ESCALATION_REASON_CODES`),
    mirroring `TIE_DISMISS_REASON_CODES`'s structure. No field here (or
    anywhere in this module) asserts a transaction is lawful, that a license
    is required, or that a match is a true positive -- those are RESEC's
    judgment calls, recorded in `reason_note`, never a code the system
    offers as if it were a fact."""

    match_id: str
    action: WorksheetActionKind
    reason_code: str
    reason_note: str
    actor: str
    recorded_at: str
