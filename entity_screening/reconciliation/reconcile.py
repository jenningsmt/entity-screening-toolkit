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
    reaches into the window. Anchor year minus window_years is the window's
    start; the item is covered when its last observed year is at or after
    that. An item with no observed dates cannot be placed in the window, so
    it is treated as not covered -- the conservative reading, since claiming
    coverage we can't establish would wrongly upgrade the finding."""
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
    return FactualBasis.ABSENT_ONLY_OUTSIDE_SCOPE_WINDOWS


def reconcile(
    case_id: str,
    run_id: str,
    declaration: Declaration,
    discovered: list[DiscoveredAffiliation],
    threshold: float = RECONCILIATION_THRESHOLD,
) -> list[Finding]:
    """Every discovered affiliation with no clearing declared match becomes a
    Finding. A discovered affiliation that *does* clear a declared name match
    is treated as disclosed and produces nothing -- the name match, not the
    date range, is what establishes 'same affiliation'; a within-affiliation
    date discrepancy is a weaker signal, out of this slice's scope."""
    declared = list(declaration.affiliations)
    findings: list[Finding] = []
    for item in discovered:
        best = best_declared_match(item.institution_name, declared, threshold)
        if best is not None and best.cleared:
            continue

        trail, any_in_scope = _declaration_search_trail(declaration, item)
        best_confidence = best.confidence if best is not None else 0.0
        nearest = tuple(
            NearestDeclared(
                declared_affiliation_id=m.declared.affiliation_id,
                institution_name=m.declared.institution_name,
                best_confidence=m.confidence,
                match_basis=m.match_basis,
                cleared_name=m.cleared,
                scope_compatible=True,  # scope is a source property; recorded in the trail
            )
            for m in ranked_declared_matches(item.institution_name, declared, threshold=threshold)
        )
        findings.append(
            Finding(
                finding_id=str(uuid.uuid4()),
                case_id=case_id,
                run_id=run_id,
                discovered=item,
                declaration_search=tuple(trail),
                factual_basis=_classify(any_in_scope, best_confidence),
                nearest_declared=nearest,
            )
        )
    return findings
