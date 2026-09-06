"""Discovery adapters: a discovery source in, DiscoveredAffiliation records out.

Each adapter turns one public reference source into the subject's own
affiliation history, expressed in measurable attributes only (institution,
country, date range, record count, role) -- the facts Section 4 permits the
system to state.

- discover_from_publications: OpenAlex. "Publication, or presentation" is the
  statute's exact language and OpenAlex's exact domain. Fixture-driven for
  the demo and tests (`works_fixture`); a live pull is optional and never on
  the demo's critical path.
- discover_from_ownership: the GLEIF ownership chain. Added in C3.
"""
from __future__ import annotations

from dataclasses import dataclass

import duckdb

from entity_screening.bibliometric.author_resolve import disambiguate_pi_to_openalex_author
from entity_screening.bibliometric.cross_check import DEFAULT_CONCERN_THRESHOLD
from entity_screening.bibliometric.institution_match import resolve_openalex_institution_by_name
from entity_screening.bibliometric.openalex_client import FetchFn, get_author_works
from entity_screening.common.attribution import attribution_for
from entity_screening.common.schema import (
    DeclaredAffiliation,
    DiscoveredAffiliation,
    ForeignControlFlag,
    MatchStatus,
    ScreeningHit,
)
from entity_screening.ownership.graph import DEFAULT_MAX_DEPTH, ultimate_parent
from entity_screening.ownership.match import resolve_entity_to_lei
from entity_screening.resolution.matcher import (
    DEFAULT_THRESHOLD,
    is_candidate_match,
    score_pair,
)
from entity_screening.screening.lists import EntityOfConcernList

PUBLICATION_ROLE = "publication_affiliation"
OWNERSHIP_PARENT_ROLE = "ultimate_parent_of_declared_employer"


def _year(value: str | None) -> str | None:
    if not value:
        return None
    return str(value)[:4]


def _aggregate_own_affiliations(
    works: list[dict], author_ids: set[str]
) -> list[DiscoveredAffiliation]:
    """Groups the subject's own per-paper institutional affiliations into one
    DiscoveredAffiliation per institution, with the observed date range and
    the count of supporting papers."""
    by_institution: dict[str, dict] = {}
    for work in works:
        pub_year = _year(work.get("publication_date"))
        work_id = work.get("id")
        for authorship in work.get("authorships", []):
            author = authorship.get("author") or {}
            if author.get("id") not in author_ids:
                continue
            position = authorship.get("author_position")
            for institution in authorship.get("institutions", []):
                name = institution.get("display_name")
                if not name:
                    continue
                agg = by_institution.setdefault(
                    name,
                    {
                        "country": institution.get("country_code"),
                        "years": set(),
                        "work_ids": set(),
                        "positions": set(),
                    },
                )
                if pub_year:
                    agg["years"].add(pub_year)
                if work_id:
                    agg["work_ids"].add(work_id)
                if position:
                    agg["positions"].add(position)

    discovered: list[DiscoveredAffiliation] = []
    for name, agg in by_institution.items():
        years = sorted(agg["years"])
        discovered.append(
            DiscoveredAffiliation(
                source="openalex",
                institution_name=name,
                country=agg["country"],
                country_on_adversary_list=None,  # set in step 4, never inferred here
                adversary_list_version=None,
                first_observed=years[0] if years else None,
                last_observed=years[-1] if years else None,
                record_count=len(agg["work_ids"]),
                role=(
                    PUBLICATION_ROLE
                    if not agg["positions"]
                    else f"{PUBLICATION_ROLE}:{'/'.join(sorted(agg['positions']))}"
                ),
                source_refs=tuple(sorted(agg["work_ids"])),
            )
        )
    return discovered


def discover_from_publications(
    subject_display_name: str,
    hiring_institution_name: str,
    declared_affiliations: list[DeclaredAffiliation],  # unused here; kept for a symmetric signature
    *,
    contact_email: str | None = None,
    fetch: FetchFn | None = None,
    works_fixture: list[dict] | None = None,
    author_threshold: float = DEFAULT_THRESHOLD,
) -> list[DiscoveredAffiliation]:
    """The subject's own institutional-affiliation history as OpenAlex records
    it. `works_fixture` short-circuits the live path entirely -- the demo
    subject is synthetic, so their 'publication record' is a clearly-labeled
    fixture, never a real author's works attached to a fictional name
    (use-case-01 Section 10)."""
    if works_fixture is not None:
        author_ids = {
            (a.get("author") or {}).get("id")
            for work in works_fixture
            for a in work.get("authorships", [])
        }
        author_ids.discard(None)
        # A fixture may mark the subject's own authorship explicitly.
        explicit = {
            (a.get("author") or {}).get("id")
            for work in works_fixture
            for a in work.get("authorships", [])
            if a.get("is_subject")
        }
        explicit.discard(None)
        return _aggregate_own_affiliations(
            works_fixture, explicit or author_ids
        )

    institution = resolve_openalex_institution_by_name(
        hiring_institution_name, contact_email=contact_email, fetch=fetch
    )
    if institution is None:
        return []
    resolved_authors = disambiguate_pi_to_openalex_author(
        "",  # entity_id is meaningless in the case model; the subject is the unit
        subject_display_name,
        institution.openalex_institution_id,
        author_threshold,
        contact_email,
        fetch,
    )
    if not resolved_authors:
        return []
    author_ids = {a.openalex_author_id for a in resolved_authors}
    all_works: list[dict] = []
    seen: set[str] = set()
    for author in resolved_authors:
        if author.openalex_author_id in seen:
            continue
        seen.add(author.openalex_author_id)
        all_works.extend(
            get_author_works(
                author.openalex_author_id, contact_email=contact_email, fetch=fetch
            )
        )
    return _aggregate_own_affiliations(all_works, author_ids)


# --------------------------------------------------------------------------
# Ownership discovery path (C3).
#
# The compose the spec's "Epics C and D already built -- this is wiring" left
# implicit: nothing today feeds an ownership-chain parent name into the
# concern-list screener. enrich_ownership computes only the cross-jurisdiction
# ForeignControlFlag. Here: resolve a declared employer to a GLEIF LEI, walk
# to its ultimate parent(s), and screen each parent's legal name against the
# registered concern lists -- the Section 10 headline finding shape ("a
# declared employer whose ultimate parent sits on a concern list", use-case-01
# Section 7), unreachable by name-matching the declared name alone.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class OwnershipDiscovery:
    discovered: DiscoveredAffiliation
    declared_employer_name: str
    concern_hits: tuple[ScreeningHit, ...]
    ownership_flags: tuple[ForeignControlFlag, ...]


def _screen_name_against_concern_lists(
    name: str,
    concern_lists: list[EntityOfConcernList],
    threshold: float,
    ownership_context: dict,
) -> list[ScreeningHit]:
    hits: list[ScreeningHit] = []
    for concern_list in concern_lists:
        for entry in concern_list.candidates_for(name):
            best = None
            for variant in entry.name_variants:
                candidate = score_pair(name, variant)
                if best is None or candidate.confidence > best.confidence:
                    best = candidate
            if best is None or not is_candidate_match(best, threshold):
                continue
            hits.append(
                ScreeningHit(
                    entity_id=ownership_context["declared_employer_name"],
                    list_name=concern_list.list_name,
                    matched_variant=best.right_name,
                    matched_field="ownership_ultimate_parent",
                    confidence=best.confidence,
                    evidence={
                        "entry_id": entry.entry_id,
                        "match_basis": best.match_basis,
                        "matched_entry_fields": entry.source_fields,
                        # How the screener reached this entity: the ownership
                        # chain from the declared employer, GLEIF-attributed.
                        "ownership_path": {
                            **ownership_context,
                            "source_attribution": attribution_for("gleif_golden_copy"),
                        },
                        "source_attribution": attribution_for(concern_list.list_name),
                    },
                    status=MatchStatus.CANDIDATE_MATCH,
                    producer="ownership_parent",
                )
            )
    return hits


def discover_from_ownership(
    declared_affiliations: list[DeclaredAffiliation],
    conn: duckdb.DuckDBPyConnection,
    concern_lists: list[EntityOfConcernList],
    *,
    lei_threshold: float = DEFAULT_THRESHOLD,
    concern_threshold: float = DEFAULT_CONCERN_THRESHOLD,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> list[OwnershipDiscovery]:
    """For each declared employer, resolve it to a GLEIF LEI, walk to its
    ultimate parent(s), and screen each parent's legal name against the
    concern lists. `conn` must already have GLEIF loaded (the caller does
    this via ownership.ingest.load_gleif_level1/2, exactly as enrich_ownership
    does). Returns one OwnershipDiscovery per parent that produced a
    concern-list hit -- a parent with no hit is not a finding here."""
    employers = [
        a
        for a in declared_affiliations
        if (a.activity_kind or "").lower() in ("employment", "hiring")
    ]
    results: list[OwnershipDiscovery] = []
    for employer in employers:
        match = resolve_entity_to_lei(
            conn, employer.affiliation_id, employer.institution_name, lei_threshold
        )
        if match is None:
            continue
        parents = ultimate_parent(conn, match.lei, max_depth=max_depth)
        if parents is None:
            continue
        parent_leis, truncated = parents
        for parent_lei in parent_leis:
            row = conn.execute(
                "SELECT legal_name, legal_jurisdiction FROM gleif_lei WHERE lei = ?",
                [parent_lei],
            ).fetchone()
            if row is None:
                continue
            parent_name, parent_jurisdiction = row
            ownership_context = {
                "declared_employer_name": employer.institution_name,
                "declared_employer_lei": match.lei,
                "declared_employer_lei_match_basis": match.match_basis,
                "declared_employer_lei_confidence": match.confidence,
                "ultimate_parent_lei": parent_lei,
                "chain_truncated": truncated,
            }
            hits = _screen_name_against_concern_lists(
                parent_name, concern_lists, concern_threshold, ownership_context
            )
            if not hits:
                continue

            flags: list[ForeignControlFlag] = []
            if parent_jurisdiction and parent_jurisdiction != match.legal_jurisdiction:
                flags.append(
                    ForeignControlFlag(
                        entity_id=employer.affiliation_id,
                        entity_lei=match.lei,
                        entity_jurisdiction=match.legal_jurisdiction,
                        ultimate_parent_lei=parent_lei,
                        ultimate_parent_name=parent_name,
                        ultimate_parent_jurisdiction=parent_jurisdiction,
                        relationship_path=(match.lei, parent_lei),
                        match_confidence=match.confidence,
                        evidence={
                            "lei_match_basis": match.match_basis,
                            "truncated": truncated,
                            "source_attribution": attribution_for("gleif_golden_copy"),
                        },
                        status=MatchStatus.CANDIDATE_MATCH,
                    )
                )

            results.append(
                OwnershipDiscovery(
                    discovered=DiscoveredAffiliation(
                        source="gleif_ownership",
                        institution_name=parent_name,
                        country=parent_jurisdiction or None,
                        country_on_adversary_list=None,
                        adversary_list_version=None,
                        first_observed=None,
                        last_observed=None,
                        record_count=1,
                        role=f"{OWNERSHIP_PARENT_ROLE}:{employer.institution_name}",
                        source_refs=(match.lei, parent_lei),
                    ),
                    declared_employer_name=employer.institution_name,
                    concern_hits=tuple(hits),
                    ownership_flags=tuple(flags),
                )
            )
    return results
