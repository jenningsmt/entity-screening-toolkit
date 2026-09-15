"""Templated recitation -- most of an explanation's value, and airtight by
construction: plain Python string-building from typed fields, no LLM call
anywhere in this file. One function per `FactualBasis` member and per
`TieKind` member (six total today); `recite` dispatches on the observation's
own type and, for a `Finding`, its `factual_basis` / for a `ConcernTie`, its
`tie_kind`.

Every sentence here states a fact directly readable off the observation's
own fields -- institution names, dates, counts, list names, confidences --
and nothing else. No adjective describes the fact itself (never "a serious
gap," always "a gap of this kind"); the one place this project allows a
genuinely composed sentence is `explanation/generate.py`'s single synthesis
step, not here.
"""
from __future__ import annotations

from entity_screening.common.schema import (
    ConcernTie,
    FactualBasis,
    Finding,
    TieKind,
)


def _date_range(first: str | None, last: str | None) -> str:
    if first and last and first != last:
        return f"from {first} to {last}"
    if first or last:
        return f"as of {first or last}"
    return "with no recorded date"


def _finding_absent_from_in_scope_source(f: Finding) -> str:
    d = f.discovered
    covering = [s for s in f.declaration_search if s.covers_this_item]
    sources = ", ".join(s.source_kind for s in covering) or "a declaration source"
    return (
        f"A record from {d.source} shows an affiliation with {d.institution_name}"
        f"{f' ({d.country})' if d.country else ''}, {_date_range(d.first_observed, d.last_observed)}, "
        f"across {d.record_count} record(s). The declaration source(s) {sources} cover "
        f"this item's scope and do not declare this affiliation."
    )


def _finding_absent_outside_all_source_scopes(f: Finding) -> str:
    d = f.discovered
    return (
        f"A record from {d.source} shows an affiliation with {d.institution_name}"
        f"{f' ({d.country})' if d.country else ''}, {_date_range(d.first_observed, d.last_observed)}, "
        f"across {d.record_count} record(s). No present declaration source's stated "
        f"scope covers this item, per the declaration-search trail — its absence from "
        f"the declaration falls outside what any source was asked to disclose."
    )


def _finding_partial_match_below_threshold(f: Finding) -> str:
    d = f.discovered
    nearest = f.nearest_declared[0] if f.nearest_declared else None
    near_text = (
        f" The nearest declared affiliation is {nearest.institution_name} "
        f"(match confidence {nearest.best_confidence:.2f}, basis: {nearest.match_basis})."
        if nearest is not None
        else ""
    )
    return (
        f"A record from {d.source} shows an affiliation with {d.institution_name}"
        f"{f' ({d.country})' if d.country else ''}, {_date_range(d.first_observed, d.last_observed)}. "
        f"This item's best match against the declared affiliations falls below the "
        f"name-matching threshold used to treat two names as the same institution."
        f"{near_text}"
    )


_FINDING_SKELETONS = {
    FactualBasis.ABSENT_FROM_IN_SCOPE_SOURCE: _finding_absent_from_in_scope_source,
    FactualBasis.ABSENT_OUTSIDE_ALL_SOURCE_SCOPES: _finding_absent_outside_all_source_scopes,
    FactualBasis.PARTIAL_MATCH_BELOW_THRESHOLD: _finding_partial_match_below_threshold,
}


def _tie_declared_employer_ultimate_parent(t: ConcernTie) -> str:
    hit = t.concern_list_evidence[0] if t.concern_list_evidence else None
    list_text = f" on {hit.list_name}" if hit else ""
    flag = t.ownership_evidence[0] if t.ownership_evidence else None
    path_text = (
        f" via an ownership chain of {len(flag.relationship_path)} link(s)"
        if flag is not None
        else ""
    )
    return (
        f"A declared employer's ultimate parent, per GLEIF ownership data, is "
        f"{t.concern_entity_name}{f' ({t.country})' if t.country else ''}, which appears"
        f"{list_text}{path_text}."
    )


def _tie_declared_affiliation_direct(t: ConcernTie) -> str:
    hit = t.concern_list_evidence[0] if t.concern_list_evidence else None
    list_text = f" on {hit.list_name}" if hit else ""
    return (
        f"A declared affiliation, {t.concern_entity_name}"
        f"{f' ({t.country})' if t.country else ''}, is itself a concern-list entry"
        f"{list_text}."
    )


def _tie_own_affiliation_history(t: ConcernTie) -> str:
    hit = t.concern_list_evidence[0] if t.concern_list_evidence else None
    list_text = f" on {hit.list_name}" if hit else ""
    also_finding = (
        " This same affiliation is also recorded as an undisclosed discrepancy."
        if t.related_finding_id
        else ""
    )
    return (
        f"The subject's own affiliation history includes {t.concern_entity_name}"
        f"{f' ({t.country})' if t.country else ''}, {_date_range(t.first_observed, t.last_observed)}, "
        f"across {t.record_count} record(s), which appears{list_text}.{also_finding}"
    )


_TIE_SKELETONS = {
    TieKind.DECLARED_EMPLOYER_ULTIMATE_PARENT: _tie_declared_employer_ultimate_parent,
    TieKind.DECLARED_AFFILIATION_DIRECT: _tie_declared_affiliation_direct,
    TieKind.OWN_AFFILIATION_HISTORY: _tie_own_affiliation_history,
}


def recite(observation: Finding | ConcernTie) -> str:
    """The fully templated recitation for one Finding or ConcernTie -- the
    whole explanation when no synthesis sentence clears verification, and
    the first paragraph of it when one does."""
    if isinstance(observation, Finding):
        return _FINDING_SKELETONS[observation.factual_basis](observation)
    if isinstance(observation, ConcernTie):
        return _TIE_SKELETONS[observation.tie_kind](observation)
    raise TypeError(f"No recitation skeleton for {type(observation).__name__}")
