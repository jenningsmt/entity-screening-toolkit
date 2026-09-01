"""Resolves a ResolvedEntity to an OpenAlex institution (Epic E).

Unlike GLEIF's resolve_entity_to_lei (a bulk 3.4M-row CSV, SQL-blocked), OpenAlex's
own /institutions?search= endpoint already ranks server-side across its whole
~110K-institution corpus in one call -- no bulk download or blocking needed here.
"""
from __future__ import annotations

from dataclasses import dataclass

from entity_screening.bibliometric.openalex_client import FetchFn, search_institutions
from entity_screening.common.schema import MatchCandidate, ResolvedEntity
from entity_screening.resolution.matcher import DEFAULT_THRESHOLD, is_candidate_match, score_pair


@dataclass(frozen=True)
class InstitutionMatch:
    """Internal to the bibliometric package, not persisted -- only ResolvedAuthor
    gets its own schema type/table (see docs/plans/2026-09-01-v3-openalex-
    bibliometric-affiliation-layer.md). Institution resolution feeds author
    disambiguation but isn't itself a queryable graph the way GLEIF's ownership
    chain is (no equivalent Epic-C-style acceptance criterion exists for it)."""

    openalex_institution_id: str
    display_name: str
    country_code: str | None
    candidate: MatchCandidate


def resolve_entity_to_openalex_institution(
    entity: ResolvedEntity,
    threshold: float = DEFAULT_THRESHOLD,
    contact_email: str | None = None,
    fetch: FetchFn | None = None,
) -> InstitutionMatch | None:
    results = search_institutions(entity.canonical_name, contact_email=contact_email, fetch=fetch)

    best_match: InstitutionMatch | None = None
    for result in results:
        variants = [result.get("display_name", "")]
        variants.extend(result.get("display_name_acronyms") or [])
        variants.extend(result.get("display_name_alternatives") or [])
        best_candidate = None
        for variant in variants:
            if not variant:
                continue
            candidate = score_pair(entity.canonical_name, variant)
            if best_candidate is None or candidate.confidence > best_candidate.confidence:
                best_candidate = candidate
        if best_candidate is None:
            continue
        if best_match is None or best_candidate.confidence > best_match.candidate.confidence:
            best_match = InstitutionMatch(
                openalex_institution_id=result["id"],
                display_name=result.get("display_name", ""),
                country_code=result.get("country_code"),
                candidate=best_candidate,
            )

    if best_match is None or not is_candidate_match(best_match.candidate, threshold):
        return None
    return best_match
