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


def is_valid_reason_code(action: str, reason_code: str) -> bool:
    if action == "dismiss":
        return reason_code in DISMISS_REASON_CODES
    return reason_code in ESCALATION_REASON_CODES
