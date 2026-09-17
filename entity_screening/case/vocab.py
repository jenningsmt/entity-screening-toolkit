"""Controlled vocabularies for the case worksheet.

`reason_code` on a WorksheetAction is a controlled vocabulary from the first
commit, not free text, so the office's accumulated dismissal bases can be
aggregated -- the "how does your institution define substantial?" by-product
(use-case-01 Section 4.1). Free-text nuance still goes in `reason_note`; the
code is what makes the corpus of real adjudications queryable.

The list is deliberately small and descriptive of a *factual* basis for the
action, never an evaluation. "Substantial" does not appear -- that is the
analyst's judgment, expressed in the note, not a code the system offers.
"""
from __future__ import annotations

DISMISS_REASON_CODES: dict[str, str] = {
    "outside_declaration_scope": (
        "The item falls outside every declaration source's stated scope "
        "(e.g. older than the DS-160 five-year employment window, with no "
        "full-history source present)."
    ),
    "same_affiliation_declared_under_variant_name": (
        "The item is the same affiliation as a declared one; the names differ "
        "only by a spelling, abbreviation or transliteration variant."
    ),
    "record_error_or_misattribution": (
        "The discovered record is a data-quality error -- a misattributed "
        "author, a wrong institution on a paper, a stale affiliation."
    ),
    "clarified_by_subject": (
        "The subject was asked and provided an account the analyst accepts; "
        "the substance of that account is in the note."
    ),
    "known_and_previously_reviewed": (
        "This item was reviewed in a prior case or disclosure cycle and its "
        "disposition is on record."
    ),
    "analyst_judgment_not_material": (
        "In the analyst's judgment the item is not a substantial omission for "
        "this person in this role. The reasoning is in the note -- this code "
        "records only that the basis was the analyst's own materiality call."
    ),
    "other": "A basis not covered above; see the note.",
}

# Actions other than `dismiss` also take a reason_code, from a shorter set.
ESCALATION_REASON_CODES: dict[str, str] = {
    "needs_supervisor_review": "Beyond the analyst's authority to dispose of alone.",
    "needs_export_control_review": "Implicates export-control / restricted-party questions.",
    "needs_subject_clarification": "Cannot be dispositioned without input from the subject.",
    "possible_nondisclosure_for_certification": (
        "Appears to meet the Sec. 51B.153 threshold; routed for a department-head "
        "certification decision."
    ),
    "other": "See the note.",
}

# --------------------------------------------------------------------------
# ConcernTie vocabularies (Sec. 51B.151(b)). `outside_declaration_scope` is
# meaningful for a discrepancy and meaningless for a tie -- a tie's dismissal
# turns on the relationship's currency, the designation's timing, or its
# materiality to the requested access scope.
# --------------------------------------------------------------------------

TIE_DISMISS_REASON_CODES: dict[str, str] = {
    "historical_or_divested_relationship": (
        "The tie is to a relationship that has ended -- the ownership link or the "
        "subject's involvement is no longer current."
    ),
    "designation_postdates_the_relationship": (
        "The concern-list designation took effect after the subject's involvement "
        "ended (cite both dates in the note)."
    ),
    "immaterial_to_requested_access_scope": (
        "The tie does not touch the research data or systems this access request "
        "concerns. The access scope and the reasoning are in the note."
    ),
    "misidentified_entity": (
        "The name match is to a different entity than the concern-listed one "
        "(the 'Chinese Academy of Sciences' / 'Ordnance Science' shape)."
    ),
    "known_and_previously_reviewed": (
        "Reviewed in a prior case or disclosure cycle; disposition on record."
    ),
    "analyst_judgment_tie_does_not_impair": (
        "In the analyst's judgment the tie would not prevent this person, in this "
        "role, from maintaining the security or integrity of the research. The "
        "reasoning is in the note -- this code records only that the basis was the "
        "analyst's own Sec. 51B.151(b) judgment. (This value states the human's "
        "conclusion, which is the right side of the fact/judgment line; the "
        "forbidden-token guard in common/schema.py applies to field names on the "
        "observation types, not to reason-code values.)"
    ),
    "other": "A basis not covered above; see the note.",
}

TIE_ESCALATION_REASON_CODES: dict[str, str] = {
    "needs_supervisor_review": "Beyond the analyst's authority to dispose of alone.",
    "needs_export_control_review": "Implicates export-control / restricted-party questions.",
    "needs_counterintelligence_referral": (
        "Meets the office's threshold for referral to the institution's research "
        "security / counterintelligence point of contact."
    ),
    "needs_subject_clarification": "Cannot be dispositioned without input from the subject.",
    "recommend_access_scope_limitation": (
        "Route to the department with a recommendation to limit what the person can "
        "access, rather than to block employment."
    ),
    "other": "See the note.",
}


# --------------------------------------------------------------------------
# Restricted-party-screening (RPS) vocabularies -- Use Case 02, step 5.
# A ScreeningMatch's disposition is RESEC's call, not a research-security
# analyst's -- its own reason vocabulary, not TIE_*'s, keeps the two roles'
# accumulated dispositions from being conflated in aggregate reporting.
# --------------------------------------------------------------------------

RPS_DISMISS_REASON_CODES: dict[str, str] = {
    "coincidental_name_match": (
        "The name match is to a different, unrelated person or organization "
        "than the restricted-party-list entry (the same 'Chinese Academy of "
        "Sciences' / 'Ordnance Science' shape ConcernTie's "
        "'misidentified_entity' guards against)."
    ),
    "delisted_or_no_longer_current": (
        "The restricted-party-list entry has since been removed or the "
        "designation is no longer current as of the snapshot date consulted."
    ),
    "known_and_previously_reviewed": (
        "This party was screened in a prior event and its disposition is on "
        "record."
    ),
    "other": "A basis not covered above; see the note.",
}

RPS_ESCALATION_REASON_CODES: dict[str, str] = {
    "needs_resec_determination": (
        "The match survived secondary review and requires an export control "
        "officer's determination (TAMU's own described RPS procedure -- "
        "docs/use-case-02-restricted-party-screening.md Section 4)."
    ),
    "needs_supervisor_review": "Beyond the screener's authority to dispose of alone.",
    "needs_party_clarification": (
        "Cannot be dispositioned without additional identifying detail from "
        "the requesting department."
    ),
    "other": "See the note.",
}


# --------------------------------------------------------------------------
# COI annual-disclosure vocabularies -- Use Case 03, step 6. `dismiss` reuses
# DISMISS_REASON_CODES unmodified (already statute-agnostic factual bases);
# only escalation needs its own set, since ESCALATION_REASON_CODES'
# `possible_nondisclosure_for_certification` routes to a Sec. 51B.153
# department-head certification that does not exist for a COI case.
# --------------------------------------------------------------------------

COI_ESCALATION_REASON_CODES: dict[str, str] = {
    "needs_supervisor_review": "Beyond the analyst's authority to dispose of alone.",
    "needs_subject_clarification": "Cannot be dispositioned without input from the subject.",
    "needs_coi_committee_referral": (
        "Appears to meet the institution's conflict-of-interest threshold; routed "
        "to the COI committee for a management-plan decision."
    ),
    "other": "See the note.",
}


def is_valid_reason_code(action: str, reason_code: str) -> bool:
    if action == "dismiss":
        return reason_code in DISMISS_REASON_CODES
    return reason_code in ESCALATION_REASON_CODES


def is_valid_tie_reason_code(action: str, reason_code: str) -> bool:
    if action == "dismiss":
        return reason_code in TIE_DISMISS_REASON_CODES
    return reason_code in TIE_ESCALATION_REASON_CODES


def is_valid_rps_reason_code(action: str, reason_code: str) -> bool:
    """M15: an explicit dismiss/escalate allowlist, not "dismiss vs.
    everything else" -- WorksheetActionKind has two other members
    (request_clarification, certification_required) that are meaningless
    for RPS (certification_required in particular is a Sec. 51B.153/
    HB127-only concept), and the old "not dismiss" shape silently
    accepted both as if they were "escalate."""
    if action == "dismiss":
        return reason_code in RPS_DISMISS_REASON_CODES
    if action == "escalate":
        return reason_code in RPS_ESCALATION_REASON_CODES
    return False


def is_valid_coi_reason_code(action: str, reason_code: str) -> bool:
    if action == "dismiss":
        return reason_code in DISMISS_REASON_CODES
    return reason_code in COI_ESCALATION_REASON_CODES
