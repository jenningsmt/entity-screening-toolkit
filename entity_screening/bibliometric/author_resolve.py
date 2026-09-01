"""Disambiguates an NSF PI name to an OpenAlex author identity (Epic E).

Real data confirmed this is genuinely hard, not boilerplate caution (see
docs/plans/2026-09-01-v3-openalex-bibliometric-affiliation-layer.md's Finding 3):
searching a real PI, even after narrowing server-side to authors ever affiliated
with the exact target institution, returned three distinct author records for one
real person -- two of which shared an identical ORCID (a real, confirmed OpenAlex
duplicate-author-record issue, not a hypothetical). So this returns a *list* of
ResolvedAuthor candidates, every one clearing the threshold, never a forced single
pick: a shared ORCID collapses to one identity (the two records are almost certainly
the same real person, unmerged in OpenAlex), while distinct ORCIDs (or one/both
missing) surface as a genuine open tie for a reviewer to see, not silently resolved.
"""
from __future__ import annotations

from collections import defaultdict

from entity_screening.bibliometric.openalex_client import FetchFn, search_authors
from entity_screening.common.schema import MatchStatus, ResolvedAuthor
from entity_screening.resolution.matcher import DEFAULT_THRESHOLD, is_candidate_match, score_pair


def _collapse_by_orcid(candidates: list[dict]) -> list[dict]:
    """Groups candidates sharing a non-null ORCID into one representative each,
    keeping the highest works_count (most complete record) as primary and
    recording the rest as `_merged_ids` on it. Candidates with no ORCID are
    never collapsed -- there is nothing to safely group them on."""
    by_orcid: dict[str, list[dict]] = defaultdict(list)
    standalone: list[dict] = []
    for candidate in candidates:
        orcid = candidate.get("orcid")
        if orcid:
            by_orcid[orcid].append(candidate)
        else:
            standalone.append(candidate)

    collapsed: list[dict] = []
    for orcid, group in by_orcid.items():
        primary = max(group, key=lambda c: c.get("works_count", 0) or 0)
        merged_ids = sorted({c["id"] for c in group if c["id"] != primary["id"]})
        collapsed.append({**primary, "_merged_ids": merged_ids})
    for candidate in standalone:
        collapsed.append({**candidate, "_merged_ids": []})
    return collapsed


def disambiguate_pi_to_openalex_author(
    entity_id: str,
    pi_name: str,
    institution_openalex_id: str,
    threshold: float = DEFAULT_THRESHOLD,
    contact_email: str | None = None,
    fetch: FetchFn | None = None,
) -> list[ResolvedAuthor]:
    raw_candidates = search_authors(
        pi_name, institution_openalex_id=institution_openalex_id,
        contact_email=contact_email, fetch=fetch,
    )
    collapsed = _collapse_by_orcid(raw_candidates)

    scored: list[tuple[dict, object]] = []
    for candidate in collapsed:
        variants = [candidate.get("display_name", "")]
        variants.extend(candidate.get("raw_author_names") or [])
        best = None
        for variant in variants:
            if not variant:
                continue
            match_candidate = score_pair(pi_name, variant)
            if best is None or match_candidate.confidence > best.confidence:
                best = match_candidate
        if best is not None and is_candidate_match(best, threshold):
            scored.append((candidate, best))

    tied_candidate_count = len(scored)
    resolved_authors = []
    for candidate, match_candidate in scored:
        resolved_authors.append(
            ResolvedAuthor(
                entity_id=entity_id,
                pi_name=pi_name,
                openalex_author_id=candidate["id"],
                display_name=candidate.get("display_name", ""),
                confidence=match_candidate.confidence,
                match_basis=match_candidate.match_basis,
                evidence={
                    "orcid": candidate.get("orcid"),
                    "shared_orcid_with": candidate.get("_merged_ids", []),
                    "tied_candidate_count": tied_candidate_count,
                    "tied_candidate_ids": sorted(c["id"] for c, _ in scored),
                    "institution_openalex_id": institution_openalex_id,
                },
                status=MatchStatus.CANDIDATE_MATCH,
            )
        )
    return resolved_authors
