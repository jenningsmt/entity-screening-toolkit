"""Discovery adapters: a discovery source in, DiscoveredAffiliation records out.

Each adapter turns one public reference source into the subject's own
affiliation history, expressed in measurable attributes only (institution,
country, date range, record count, role) -- the facts Section 4 permits the
system to state.

- discover_from_publications: OpenAlex. "Publication, or presentation" is the
  statute's exact language and OpenAlex's exact domain. Fixture-driven for
  the demo and tests (`works_fixture`); a live pull is optional and never on
  the demo's critical path. Feeds the Sec. 51B.153 omission test.
- tie_from_ownership / ties_from_own_affiliations: the Sec. 51B.151(b) tie
  test -- emit ConcernTie observations, a distinct row type from a Finding.
"""
from __future__ import annotations

import uuid

import duckdb

from entity_screening.bibliometric.author_resolve import disambiguate_pi_to_openalex_author
from entity_screening.bibliometric.cross_check import DEFAULT_CONCERN_THRESHOLD
from entity_screening.bibliometric.institution_match import resolve_openalex_institution_by_name
from entity_screening.bibliometric.openalex_client import FetchFn, get_author_works
from entity_screening.common.attribution import attribution_for
from entity_screening.common.schema import (
    ConcernTie,
    DeclaredAffiliation,
    DiscoveredAffiliation,
    ForeignControlFlag,
    MatchStatus,
    ScreeningHit,
    TieKind,
)
from entity_screening.ownership.graph import DEFAULT_MAX_DEPTH, ultimate_parent
from entity_screening.ownership.match import resolve_entity_to_lei
from entity_screening.resolution.matcher import (
    DEFAULT_THRESHOLD,
    is_candidate_match,
    score_pair,
)
from entity_screening.screening.adversary_list import AdversaryCountryList
from entity_screening.screening.lists import EntityOfConcernList

PUBLICATION_ROLE = "publication_affiliation"


def _year(value: str | None) -> str | None:
    if not value:
        return None
    return str(value)[:4]


def _aggregate_own_affiliations(
    works: list[dict], author_ids: set[str], adversary_list: AdversaryCountryList
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
                country_on_adversary_list=adversary_list.contains(agg["country"]),
                adversary_list_version=adversary_list.list_version,
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
    adversary_list: AdversaryCountryList,
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
            works_fixture, explicit or author_ids, adversary_list
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
    return _aggregate_own_affiliations(all_works, author_ids, adversary_list)


# --------------------------------------------------------------------------
# Concern-tie discovery paths (Sec. 51B.151(b)).
#
# A tie to a concern-listed entity is not a non-disclosure -- it is the
# subject of the statute's separate background check. These adapters emit
# ConcernTie observations, a distinct row type from a Finding. See
# docs/plans/2026-09-06-concern-ties-as-a-distinct-observation.md.
# --------------------------------------------------------------------------


def _screen_name_against_concern_lists(
    name: str,
    concern_lists: list[EntityOfConcernList],
    threshold: float,
    *,
    anchor_entity_id: str,
    matched_field: str,
    producer: str,
    ownership_path: dict | None = None,
) -> list[ScreeningHit]:
    """Screens one name against every registered concern list.

    `anchor_entity_id` is the subject-side id (a declared affiliation_id, or
    "" for the subject's own affiliation history) -- NOT an entity name; that
    field is a UUID everywhere else in the codebase. The concern entity's own
    name is carried in `matched_variant` and `evidence["matched_entry_fields"]`.
    """
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
            evidence = {
                "entry_id": entry.entry_id,
                "match_basis": best.match_basis,
                "matched_entry_fields": entry.source_fields,
                "source_attribution": attribution_for(concern_list.list_name),
            }
            if ownership_path is not None:
                evidence["ownership_path"] = {
                    **ownership_path,
                    "source_attribution": attribution_for("gleif_golden_copy"),
                }
            hits.append(
                ScreeningHit(
                    entity_id=anchor_entity_id,
                    list_name=concern_list.list_name,
                    matched_variant=best.right_name,
                    matched_field=matched_field,
                    confidence=best.confidence,
                    evidence=evidence,
                    status=MatchStatus.CANDIDATE_MATCH,
                    producer=producer,
                )
            )
    return hits


def tie_from_ownership(
    case_id: str,
    run_id: str,
    declared_affiliations: list[DeclaredAffiliation],
    conn: duckdb.DuckDBPyConnection,
    concern_lists: list[EntityOfConcernList],
    adversary_list: AdversaryCountryList,
    *,
    lei_threshold: float = DEFAULT_THRESHOLD,
    concern_threshold: float = DEFAULT_CONCERN_THRESHOLD,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> list[ConcernTie]:
    """For each declared employer, resolve it to a GLEIF LEI, walk to its
    ultimate parent(s), and screen each parent's legal name against the
    concern lists. `conn` must already have GLEIF loaded (the caller does this
    via ownership.ingest.load_gleif_level1/2, exactly as enrich_ownership
    does). One ConcernTie per parent that produced a concern-list hit --
    emitted **whether or not** the parent is itself declared, because
    disclosure is the Sec. 51B.153 question and this is a Sec. 51B.151(b)
    tie."""
    employers = [
        a
        for a in declared_affiliations
        if (a.activity_kind or "").lower() in ("employment", "hiring")
    ]
    ties: list[ConcernTie] = []
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
            ownership_path = {
                "declared_employer_name": employer.institution_name,
                "declared_employer_lei": match.lei,
                "declared_employer_lei_match_basis": match.match_basis,
                "declared_employer_lei_confidence": match.confidence,
                "ultimate_parent_lei": parent_lei,
                "chain_truncated": truncated,
            }
            hits = _screen_name_against_concern_lists(
                parent_name,
                concern_lists,
                concern_threshold,
                anchor_entity_id=employer.affiliation_id,
                matched_field="ownership_ultimate_parent",
                producer="ownership_parent",
                ownership_path=ownership_path,
            )
            if not hits:
                continue

            flags: tuple[ForeignControlFlag, ...] = ()
            if parent_jurisdiction and parent_jurisdiction != match.legal_jurisdiction:
                flags = (
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
                    ),
                )

            ties.append(
                ConcernTie(
                    tie_id=str(uuid.uuid4()),
                    case_id=case_id,
                    run_id=run_id,
                    tie_kind=TieKind.DECLARED_EMPLOYER_ULTIMATE_PARENT,
                    anchor_affiliation_id=employer.affiliation_id,
                    related_finding_id=None,  # an ownership tie has no corresponding finding
                    concern_entity_name=parent_name,
                    country=parent_jurisdiction or None,
                    country_on_adversary_list=adversary_list.contains(parent_jurisdiction),
                    adversary_list_version=adversary_list.list_version,
                    first_observed=None,
                    last_observed=None,
                    record_count=1,
                    concern_list_evidence=tuple(hits),
                    ownership_evidence=flags,
                )
            )
    return ties


def ties_from_own_affiliations(
    case_id: str,
    run_id: str,
    discovered_affiliations: list[DiscoveredAffiliation],
    concern_lists: list[EntityOfConcernList],
    *,
    concern_threshold: float = DEFAULT_CONCERN_THRESHOLD,
) -> list[ConcernTie]:
    """Screens each of the subject's own discovered affiliations against the
    concern lists. Emits a ConcernTie(OWN_AFFILIATION_HISTORY) per match --
    **regardless** of whether that affiliation is also an undisclosed Finding
    (the both-at-once case, deliberately two artifacts). `related_finding_id`
    is stamped by the caller (pipeline.reconcile_case) from the
    DiscoveredAffiliation -> finding_id map; here it is left None.

    No `adversary_list` parameter here -- `country_on_adversary_list`/
    `adversary_list_version` below are inherited from each `da`, already
    resolved by `discover_from_publications`/`_aggregate_own_affiliations`
    against the same list; re-deriving them from a second parameter would be
    a redundant lookup that could only ever agree or silently disagree with
    the value already sitting on `da`."""
    ties: list[ConcernTie] = []
    for da in discovered_affiliations:
        hits = _screen_name_against_concern_lists(
            da.institution_name,
            concern_lists,
            concern_threshold,
            anchor_entity_id="",
            matched_field="own_affiliation_history",
            producer="own_affiliation",
        )
        if not hits:
            continue
        ties.append(
            ConcernTie(
                tie_id=str(uuid.uuid4()),
                case_id=case_id,
                run_id=run_id,
                tie_kind=TieKind.OWN_AFFILIATION_HISTORY,
                anchor_affiliation_id=None,
                related_finding_id=None,  # set by reconcile_case
                concern_entity_name=da.institution_name,
                country=da.country,
                # Inherited from the DiscoveredAffiliation `da` itself, not a
                # second independent lookup -- `_aggregate_own_affiliations`
                # already resolved this against the same adversary_list.
                country_on_adversary_list=da.country_on_adversary_list,
                adversary_list_version=da.adversary_list_version,
                first_observed=da.first_observed,
                last_observed=da.last_observed,
                record_count=da.record_count,
                concern_list_evidence=tuple(hits),
                ownership_evidence=(),
            )
        )
    return ties
