import datetime

from entity_screening.bibliometric.cross_check import cross_check_bibliometric
from entity_screening.common.schema import MatchStatus, ResolvedAuthor, SourceRecord
from entity_screening.screening.lists import OpenSanctionsList


def _os_record(record_id: str, name: str) -> SourceRecord:
    return SourceRecord(
        source_dataset="opensanctions_targets_simple",
        retrieval_date=datetime.date(2026, 1, 1),
        source_record_id=record_id,
        fields={"id": record_id, "schema": "Company", "name": name, "aliases": ""},
    )


def _resolved_author(**evidence_overrides) -> ResolvedAuthor:
    evidence = {"tied_candidate_count": 1, "shared_orcid_with": []}
    evidence.update(evidence_overrides)
    return ResolvedAuthor(
        entity_id="e1",
        pi_name="Andrew Felton",
        openalex_author_id="https://openalex.org/A5067979033",
        display_name="Andrew J. Felton",
        confidence=1.0,
        match_basis="normalized_exact",
        evidence=evidence,
        status=MatchStatus.CANDIDATE_MATCH,
    )


def _work(authorships):
    return {
        "id": "https://openalex.org/W1",
        "title": "A Fixture Paper",
        "publication_date": "2026-01-01",
        "authorships": authorships,
    }


def test_co_author_institution_match_produces_a_hit_with_inlined_tie_context():
    resolved_author = _resolved_author(tied_candidate_count=2, shared_orcid_with=["https://openalex.org/A999"])
    work = _work([
        {
            "author": {"id": "https://openalex.org/A5067979033", "display_name": "Andrew J. Felton"},
            "institutions": [{"id": "https://openalex.org/I1", "display_name": "Montana State University"}],
        },
        {
            "author": {"id": "https://openalex.org/A999", "display_name": "Co Author"},
            "institutions": [{"id": "https://openalex.org/I2", "display_name": "Fixture Sovereign Wealth Fund"}],
        },
    ])

    works_by_author_id = {resolved_author.openalex_author_id: [work]}
    concern_lists = [OpenSanctionsList([_os_record("os-1", "Fixture Sovereign Wealth Fund")])]

    hits = list(cross_check_bibliometric("e1", [resolved_author], concern_lists, works_by_author_id))

    assert len(hits) == 1
    hit = hits[0]
    assert hit.matched_field == "bibliometric_co_author_institution"
    assert hit.entity_id == "e1"
    assert hit.confidence == 1.0

    # Evidence must be self-contained -- the tie context is right here, no further
    # lookup back to openalex_author_matches required (same bar as
    # test_evidence_is_self_contained_without_a_further_join).
    assert hit.evidence["author_resolution"]["openalex_author_id"] == "https://openalex.org/A5067979033"
    assert hit.evidence["author_resolution"]["tied_candidate_count"] == 2
    assert hit.evidence["author_resolution"]["shared_orcid_with"] == ["https://openalex.org/A999"]
    assert hit.evidence["co_author"]["display_name"] == "Co Author"
    assert hit.evidence["work"]["id"] == "https://openalex.org/W1"


def test_own_past_affiliation_match_produces_a_hit_tagged_differently_from_co_author():
    resolved_author = _resolved_author()
    work = _work([
        {
            "author": {"id": "https://openalex.org/A5067979033", "display_name": "Andrew J. Felton"},
            "institutions": [{"id": "https://openalex.org/I3", "display_name": "Fixture Sovereign Wealth Fund"}],
        }
    ])

    works_by_author_id = {resolved_author.openalex_author_id: [work]}
    concern_lists = [OpenSanctionsList([_os_record("os-1", "Fixture Sovereign Wealth Fund")])]

    hits = list(cross_check_bibliometric("e1", [resolved_author], concern_lists, works_by_author_id))

    assert len(hits) == 1
    assert hits[0].matched_field == "bibliometric_past_affiliation"
    assert "co_author" not in hits[0].evidence


def test_real_false_positive_from_live_verification_is_excluded_by_the_default_threshold():
    """Real, not hypothetical: running enrich_bibliometric live against a real NSF
    PI turned up 27 hits against the bundled DoD 1260H list, every one a false
    positive -- the legitimate, non-military "Chinese Academy of Sciences" (a real
    co-author's real affiliation) fuzzy-matched DoD 1260H's real "Chinese Academy
    of Ordnance Science" entry at 0.8387 via score_pair's token-sort fallback,
    clearing the standard 0.80 screening threshold. This recurs at real scale
    specifically in bibliometric cross-checking (every co-author's institution
    across every paper gets checked, not one entity's own name once) in a way it
    doesn't in ordinary screening. DEFAULT_CONCERN_THRESHOLD=0.90 exists
    specifically to exclude this (see docs/data_sources.md's OpenAlex entry for the
    full account) -- this test guards the fix, not the general matcher (score_pair
    itself is correctly unchanged; a 0.90 bar is bibliometric-cross-check-specific)."""
    resolved_author = _resolved_author()
    work = _work([{
        "author": {"id": "https://openalex.org/A_co_author", "display_name": "Real Co-Author"},
        "institutions": [{"id": "https://openalex.org/I_cas", "display_name": "Chinese Academy of Sciences"}],
    }])

    works_by_author_id = {resolved_author.openalex_author_id: [work]}
    concern_lists = [OpenSanctionsList([_os_record("dod-1260h-style", "Chinese Academy of Ordnance Science")])]

    hits = list(cross_check_bibliometric("e1", [resolved_author], concern_lists, works_by_author_id))

    assert hits == []


def test_no_hit_when_nothing_matches_any_concern_list():
    resolved_author = _resolved_author()
    work = _work([
        {
            "author": {"id": "https://openalex.org/A5067979033", "display_name": "Andrew J. Felton"},
            "institutions": [{"id": "https://openalex.org/I1", "display_name": "Montana State University"}],
        },
        {
            "author": {"id": "https://openalex.org/A2", "display_name": "Unrelated Co Author"},
            "institutions": [{"id": "https://openalex.org/I2", "display_name": "Unrelated University"}],
        },
    ])

    works_by_author_id = {resolved_author.openalex_author_id: [work]}
    concern_lists = [OpenSanctionsList([_os_record("os-1", "Fixture Sovereign Wealth Fund")])]

    hits = list(cross_check_bibliometric("e1", [resolved_author], concern_lists, works_by_author_id))

    assert hits == []


def test_multiple_tied_resolved_authors_each_produce_hits_with_their_own_distinct_tie_context():
    """When author_resolve.py surfaces a genuine open tie (two ResolvedAuthor
    candidates), walking both must not blur which candidate produced which hit."""
    author_a = _resolved_author()
    author_b = ResolvedAuthor(
        entity_id="e1", pi_name="Andrew Felton",
        openalex_author_id="https://openalex.org/A5110303932",
        display_name="Andrew Felton", confidence=0.95, match_basis="fuzzy_token_sort",
        evidence={"tied_candidate_count": 2, "shared_orcid_with": []},
        status=MatchStatus.CANDIDATE_MATCH,
    )
    work_a = _work([{
        "author": {"id": "https://openalex.org/A5067979033", "display_name": "Andrew J. Felton"},
        "institutions": [{"id": "https://openalex.org/I3", "display_name": "Fixture Sovereign Wealth Fund"}],
    }])
    work_b = _work([{
        "author": {"id": "https://openalex.org/A5110303932", "display_name": "Andrew Felton"},
        "institutions": [{"id": "https://openalex.org/I3", "display_name": "Fixture Sovereign Wealth Fund"}],
    }])

    works_by_author_id = {
        author_a.openalex_author_id: [work_a],
        author_b.openalex_author_id: [work_b],
    }
    concern_lists = [OpenSanctionsList([_os_record("os-1", "Fixture Sovereign Wealth Fund")])]

    hits = list(cross_check_bibliometric("e1", [author_a, author_b], concern_lists, works_by_author_id))

    assert len(hits) == 2
    producing_ids = {h.evidence["author_resolution"]["openalex_author_id"] for h in hits}
    assert producing_ids == {
        "https://openalex.org/A5067979033",
        "https://openalex.org/A5110303932",
    }
