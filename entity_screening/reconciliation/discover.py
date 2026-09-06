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

from collections import defaultdict

from entity_screening.bibliometric.author_resolve import disambiguate_pi_to_openalex_author
from entity_screening.bibliometric.institution_match import resolve_openalex_institution_by_name
from entity_screening.bibliometric.openalex_client import FetchFn, get_author_works
from entity_screening.common.schema import DeclaredAffiliation, DiscoveredAffiliation
from entity_screening.resolution.matcher import DEFAULT_THRESHOLD

PUBLICATION_ROLE = "publication_affiliation"


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
