"""Bibliometric co-authorship/affiliation cross-check (Epic E).

For each disambiguated PI (a ResolvedAuthor), walks their OpenAlex works and checks
two things against the existing registered concern lists (screening/lists.py),
reusing the same score_pair-based matching screen_entity already does elsewhere in
this project: (a) every co-author's own institution affiliations, and (b) the
resolved author's own institution history across their papers (not just the
institution they were originally resolved through) -- connections an institution's
own disclosures wouldn't mention, per Epic E's own framing.

Every resulting ScreeningHit inlines its producing ResolvedAuthor's tie context
directly into its own `evidence["author_resolution"]` -- not a reference requiring a
further join back to the openalex_author_matches table. This project already has a
codified bar for exactly this (test_evidence_is_self_contained_without_a_further_join,
added for Section 9a's "evidence must work as LLM retrieval context without a further
lookup"): a hit produced by walking one tied candidate out of several must not look
like a clean, single-source finding to a reviewer who only sees the exported hit.

DEFAULT_CONCERN_THRESHOLD is higher than the standard 0.80 screening threshold, for
the same reason Section 117 raised its own institution-match threshold: misattributing
a co-author's institution to the wrong concern-list entry is a worse failure mode
here than a missed match, and this stage carries a volume-multiplication risk
screen_entity() doesn't have -- every co-author's institution across every one of a
PI's papers gets checked, not just one entity's own name once. Confirmed against real
data, not assumed: a real PI's real co-authors at the legitimate, non-military
"Chinese Academy of Sciences" fuzzy-matched the bundled DoD 1260H list's "Chinese
Academy of Ordnance Science" at 0.8387 -- comfortably clearing 0.80, recurring 27
times across that PI's real papers, and confirmed a real false positive, not a
hypothetical one (docs/data_sources.md's OpenAlex entry has the full account). 0.90
excludes that false positive while still clearing every real match confirmed during
Section 117's own real-data pass (exact matches at 1.0) and acronym matches (exactly
0.9, at the boundary).
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator

from entity_screening.common.attribution import OPENALEX_PRECISION_CAVEAT, attribution_for
from entity_screening.common.schema import MatchStatus, ResolvedAuthor, ScreeningHit
from entity_screening.resolution.matcher import is_candidate_match, score_pair
from entity_screening.screening.lists import EntityOfConcernList

PAST_AFFILIATION_FIELD = "bibliometric_past_affiliation"
CO_AUTHOR_INSTITUTION_FIELD = "bibliometric_co_author_institution"
DEFAULT_CONCERN_THRESHOLD = 0.90


def _author_resolution_evidence(resolved_author: ResolvedAuthor) -> dict:
    """The tie context to inline into every hit this candidate produces -- see
    module docstring."""
    return {
        "openalex_author_id": resolved_author.openalex_author_id,
        "pi_name": resolved_author.pi_name,
        "confidence": resolved_author.confidence,
        "tied_candidate_count": resolved_author.evidence.get("tied_candidate_count"),
        "shared_orcid_with": resolved_author.evidence.get("shared_orcid_with"),
    }


def _best_concern_list_match(name: str, concern_lists: Iterable[EntityOfConcernList], block_size: int):
    for concern_list in concern_lists:
        for entry in concern_list.candidates_for(name, block_size=block_size):
            best = None
            for variant in entry.name_variants:
                candidate = score_pair(name, variant)
                if best is None or candidate.confidence > best.confidence:
                    best = candidate
            if best is not None:
                yield concern_list, entry, best


def cross_check_bibliometric(
    entity_id: str,
    resolved_authors: Iterable[ResolvedAuthor],
    concern_lists: Iterable[EntityOfConcernList],
    works_by_author_id: dict[str, list[dict]],
    threshold: float = DEFAULT_CONCERN_THRESHOLD,
    block_size: int = 3,
) -> Iterator[ScreeningHit]:
    """`works_by_author_id` is pre-fetched by the caller (pipeline.py), not
    fetched here -- Workstream 9b: enrich_bibliometric fetches (and persists)
    each resolved author's works exactly once, and enrich_topic_similarity
    reads the same persisted copy back rather than re-fetching, which used to
    double OpenAlex traffic and wall-clock for the combined path. This
    function stays a pure check against already-available data; a missing
    author_id in the dict is treated the same as "no works," never an error
    -- an author this cross-check has never seen still legitimately produces
    zero hits."""
    concern_lists = list(concern_lists)
    for resolved_author in resolved_authors:
        author_evidence = _author_resolution_evidence(resolved_author)
        works = works_by_author_id.get(resolved_author.openalex_author_id, [])
        for work in works:
            work_evidence = {
                "id": work.get("id"),
                "title": work.get("title"),
                "publication_date": work.get("publication_date"),
            }
            for authorship in work.get("authorships", []):
                author = authorship.get("author") or {}
                is_self = author.get("id") == resolved_author.openalex_author_id
                matched_field = PAST_AFFILIATION_FIELD if is_self else CO_AUTHOR_INSTITUTION_FIELD

                for institution in authorship.get("institutions", []):
                    institution_name = institution.get("display_name")
                    if not institution_name:
                        continue
                    for concern_list, entry, best in _best_concern_list_match(
                        institution_name, concern_lists, block_size
                    ):
                        if not is_candidate_match(best, threshold):
                            continue
                        evidence = {
                            "entry_id": entry.entry_id,
                            "match_basis": best.match_basis,
                            "matched_entry_fields": entry.source_fields,
                            "author_resolution": author_evidence,
                            "work": work_evidence,
                            "matched_institution": {
                                "openalex_id": institution.get("id"),
                                "display_name": institution_name,
                                "country_code": institution.get("country_code"),
                            },
                            # A bibliometric hit inherits uncertainty from both
                            # the matched concern-list entry AND OpenAlex's own
                            # affiliation data (Finding 6 / Epic E's third
                            # criterion) -- the caveat rides alongside the
                            # concern list's own attribution/license, not as a
                            # separate evidence key a consumer could miss.
                            "source_attribution": {
                                **attribution_for(concern_list.list_name),
                                "caveat": OPENALEX_PRECISION_CAVEAT,
                            },
                        }
                        if not is_self:
                            evidence["co_author"] = {
                                "openalex_author_id": author.get("id"),
                                "display_name": author.get("display_name"),
                            }
                        yield ScreeningHit(
                            entity_id=entity_id,
                            list_name=concern_list.list_name,
                            matched_variant=best.right_name,
                            matched_field=matched_field,
                            confidence=best.confidence,
                            evidence=evidence,
                            status=MatchStatus.CANDIDATE_MATCH,
                            producer="bibliometric",
                        )
