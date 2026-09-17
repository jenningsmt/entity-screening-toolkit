"""The reconciliation diff: DiscoveredAffiliation x Declaration -> list[Finding].

Section 4's fact/judgment boundary governs everything here. For each
discovered affiliation the engine states:

- which declaration sources were searched and the stated scope of each
- whether the item falls inside a source's scope (its absence is a gap in a
  document that asked for it) or outside it (its absence may be a scope
  artifact)
- the measurable attributes already carried on the DiscoveredAffiliation
- the closest declared affiliations that did not clear, and why

and never states whether the omission is *substantial*, whether the person
is a risk, or any disposition. "Substantial" is undefined in statute and
unsettled in practice (use-case-01 Section 4); the analyst makes that call
and records it as a WorksheetAction.
"""
from __future__ import annotations

import uuid

from entity_screening.common.schema import (
    Declaration,
    DeclarationSearch,
    DeclarationSource,
    DiscoveredAffiliation,
    FactualBasis,
    Finding,
    NearestDeclared,
    ScopeKind,
)
from entity_screening.reconciliation.match import (
    PARTIAL_MATCH_FLOOR,
    RECONCILIATION_THRESHOLD,
    best_declared_match,
    ranked_declared_matches,
)

_EDUCATION_ACTIVITIES = {"education", "degree", "study", "training"}


def _overlaps_temporal_window(
    discovered: DiscoveredAffiliation, descriptor: dict
) -> bool:
    """A TEMPORAL_WINDOW source covers the item if the discovered affiliation
    reaches into the window AND the window's own category admits this kind
    of record. The only category value any fixture in this codebase uses is
    "employment" (a DS-160/CV-style employment window); every OpenAlex-
    sourced item's role is "publication_affiliation" (-prefixed) -- a
    publication co-affiliation is evidence of an academic address on a
    paper, not a verified employment relationship, so an employment window
    never admits one, regardless of date overlap (S4/M4). Same conservative
    principle as the missing-dates check below: claiming coverage we can't
    establish would wrongly upgrade the finding. No other category value
    exists yet to build a rule for -- add one only when a real fixture
    needs it.

    Anchor year minus window_years is the window's start; the item is
    covered when its last observed year is at or after that. An item with
    no observed dates cannot be placed in the window, so it is treated as
    not covered."""
    category = descriptor.get("category")
    role = (discovered.role or "").lower()
    if category == "employment" and role.startswith("publication_affiliation"):
        return False
    window_years = descriptor.get("window_years")
    anchor = descriptor.get("anchor")
    if not window_years or not anchor:
        return False
    try:
        anchor_year = int(str(anchor)[:4])
        window_start = anchor_year - int(window_years)
    except (TypeError, ValueError):
        return False
    last = discovered.last_observed or discovered.first_observed
    if not last:
        return False
    try:
        return int(str(last)[:4]) >= window_start
    except ValueError:
        return False


def _source_covers(
    source: DeclarationSource, discovered: DiscoveredAffiliation
) -> bool:
    """Does this declaration source's stated scope admit the discovered item."""
    if not source.present:
        return False
    if source.scope_kind == ScopeKind.FULL_HISTORY:
        return True
    if source.scope_kind == ScopeKind.TEMPORAL_WINDOW:
        return _overlaps_temporal_window(discovered, source.scope_descriptor)
    if source.scope_kind == ScopeKind.HIGHEST_ONLY:
        # Covers only an education item, and only as the single highest
        # qualification -- which the engine cannot verify, so it states the
        # weaker fact: an education item *could* fall in scope, anything else
        # cannot.
        role = (discovered.role or "").lower()
        return any(token in role for token in _EDUCATION_ACTIVITIES)
    if source.scope_kind == ScopeKind.TYPE_ENUMERATION:
        enumerated = {t.lower() for t in source.scope_descriptor.get("types", [])}
        role = (discovered.role or "").lower()
        return any(t in role for t in enumerated)
    return False


def _declared_source(
    declaration: Declaration, declared: DeclaredAffiliation
) -> DeclarationSource | None:
    """The DeclarationSource a given declared affiliation was declared
    under -- a lookup by source_id, not a name match. None only if the
    declaration data itself is inconsistent (a declared affiliation citing
    a source_id no source in the same declaration carries)."""
    for source in declaration.sources:
        if source.source_id == declared.source_id:
            return source
    return None


def _declaration_search_trail(
    declaration: Declaration, discovered: DiscoveredAffiliation
) -> tuple[list[DeclarationSearch], bool]:
    """The per-source trail, and whether any *present* source's scope covers
    the item."""
    trail: list[DeclarationSearch] = []
    any_in_scope = False
    for source in declaration.sources:
        covers = _source_covers(source, discovered)
        any_in_scope = any_in_scope or covers
        trail.append(
            DeclarationSearch(
                source_kind=source.kind,
                present=source.present,
                scope_kind=source.scope_kind,
                scope_descriptor=source.scope_descriptor,
                covers_this_item=covers,
            )
        )
    return trail, any_in_scope


def _classify(
    any_in_scope: bool, best_confidence: float
) -> FactualBasis:
    if PARTIAL_MATCH_FLOOR <= best_confidence < RECONCILIATION_THRESHOLD:
        return FactualBasis.PARTIAL_MATCH_BELOW_THRESHOLD
    if any_in_scope:
        return FactualBasis.ABSENT_FROM_IN_SCOPE_SOURCE
    return FactualBasis.ABSENT_OUTSIDE_ALL_SOURCE_SCOPES


def build_finding(
    case_id: str,
    run_id: str,
    declaration: Declaration,
    item: DiscoveredAffiliation,
    *,
    threshold: float = RECONCILIATION_THRESHOLD,
) -> Finding:
    """Assembles one Finding for a discovered affiliation that has no
    clearing declared match: the declaration-search trail, the factual
    classification, and the nearest declared affiliations that did not
    clear."""
    declared = list(declaration.affiliations)
    best = best_declared_match(item.institution_name, declared, threshold)
    trail, any_in_scope = _declaration_search_trail(declaration, item)
    best_confidence = best.confidence if best is not None else 0.0
    # S4/M4: scope_compatible is computed against the declaring source's
    # actual scope, not hard-coded True -- reusing _source_covers exactly
    # as _declaration_search_trail does above, so a candidate whose source
    # doesn't admit this item's date/role reads False, not an unqualified
    # claim of coverage. Diagnostic/trail information only: reconcile()'s
    # clearance gate below stays name-match-only, deliberately (see its
    # own docstring) -- wiring this into clearance would be correct for
    # HB-127 but wrong for a COI/outside-interest declaration, whose
    # single TYPE_ENUMERATION scope never admits a bare publication role
    # at all (see docs/plans/2026-09-17-phase-4-reconciliation-evidence-
    # correctness.md's empirical trace).
    nearest_list = []
    for m in ranked_declared_matches(item.institution_name, declared, threshold=threshold):
        source = _declared_source(declaration, m.declared)
        nearest_list.append(
            NearestDeclared(
                declared_affiliation_id=m.declared.affiliation_id,
                institution_name=m.declared.institution_name,
                best_confidence=m.confidence,
                match_basis=m.match_basis,
                cleared_name=m.cleared,
                scope_compatible=_source_covers(source, item) if source is not None else False,
            )
        )
    nearest = tuple(nearest_list)
    return Finding(
        # S5: deterministic, not uuid4 -- a re-run of reconciliation must
        # produce the same finding_id for the same (case_id, source,
        # institution_name) so analyst actions and cached explanations
        # carry forward instead of orphaning. `(source, institution_name)`
        # is unique per run (discovered_finding_map's own docstring,
        # below), so no other component is needed. Same pattern as this
        # codebase's other deterministic ids (pipeline.py's
        # resolve_entities_from_nsf: uuid5(NAMESPACE_DNS, key)).
        finding_id=str(uuid.uuid5(
            uuid.NAMESPACE_DNS, f"finding|{case_id}|{item.source}|{item.institution_name}"
        )),
        case_id=case_id,
        run_id=run_id,
        discovered=item,
        declaration_search=tuple(trail),
        factual_basis=_classify(any_in_scope, best_confidence),
        nearest_declared=nearest,
    )


def reconcile(
    case_id: str,
    run_id: str,
    declaration: Declaration,
    discovered: list[DiscoveredAffiliation],
    threshold: float = RECONCILIATION_THRESHOLD,
) -> list[Finding]:
    """Every discovered affiliation with no clearing declared match becomes a
    Finding -- the Sec. 51B.153 omission test. A discovered affiliation that
    *does* clear a declared name match is treated as disclosed and produces
    nothing here (a concern tie for the same affiliation is a separate
    matter, emitted by ties_from_own_affiliations regardless)."""
    declared = list(declaration.affiliations)
    findings: list[Finding] = []
    for item in discovered:
        best = best_declared_match(item.institution_name, declared, threshold)
        if best is not None and best.cleared:
            continue
        findings.append(build_finding(case_id, run_id, declaration, item, threshold=threshold))
    return findings


def discovered_finding_map(findings: list[Finding]) -> dict[tuple[str, str], str]:
    """`{(discovered.source, discovered.institution_name): finding_id}` -- how
    pipeline.reconcile_case pairs an OWN_AFFILIATION_HISTORY ConcernTie with
    the Finding for the same discovered affiliation (the both-at-once join).
    `_aggregate_own_affiliations` yields one DiscoveredAffiliation per
    institution within a run, so this key is unique."""
    return {
        (f.discovered.source, f.discovered.institution_name): f.finding_id for f in findings
    }
