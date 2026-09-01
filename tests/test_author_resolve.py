import json
from pathlib import Path

from entity_screening.bibliometric.author_resolve import disambiguate_pi_to_openalex_author

FIXTURES_DIR = Path(__file__).parent / "fixtures"
RESPONSES = json.loads((FIXTURES_DIR / "sample_openalex_responses.json").read_text(encoding="utf-8"))

MONTANA_STATE_ID = "https://openalex.org/I23732399"


def test_real_tied_orcid_case_collapses_to_one_identity_and_surfaces_the_open_tie():
    """Real data (Finding 3): 3 candidates for "Andrew Felton" at Montana State
    University -- A5067979033 and A5140693917 share an ORCID (collapse to one
    identity), A5110303932 has no ORCID (a genuine, separate open tie)."""
    def fake_fetch(url, params):
        return RESPONSES["authors_search_andrew_felton_montana_state"]

    resolved = disambiguate_pi_to_openalex_author(
        entity_id="e1", pi_name="Andrew Felton",
        institution_openalex_id=MONTANA_STATE_ID, fetch=fake_fetch,
    )

    # 3 raw candidates collapse to 2 distinct identities (ORCID-shared pair -> 1).
    assert len(resolved) == 2
    ids = {r.openalex_author_id for r in resolved}
    assert ids == {"https://openalex.org/A5067979033", "https://openalex.org/A5110303932"}

    primary = next(r for r in resolved if r.openalex_author_id == "https://openalex.org/A5067979033")
    assert primary.evidence["shared_orcid_with"] == ["https://openalex.org/A5140693917"]
    assert primary.evidence["tied_candidate_count"] == 2

    no_orcid_candidate = next(r for r in resolved if r.openalex_author_id == "https://openalex.org/A5110303932")
    assert no_orcid_candidate.evidence["shared_orcid_with"] == []
    assert no_orcid_candidate.evidence["tied_candidate_count"] == 2


def test_single_unambiguous_candidate_returns_one_resolved_author():
    def fake_fetch(url, params):
        return {
            "results": [
                {
                    "id": "https://openalex.org/A1",
                    "orcid": "https://orcid.org/0000-0000-0000-0001",
                    "display_name": "Jane Q. Researcher",
                    "raw_author_names": ["Jane Researcher"],
                }
            ]
        }

    resolved = disambiguate_pi_to_openalex_author(
        entity_id="e1", pi_name="Jane Researcher",
        institution_openalex_id="https://openalex.org/I1", fetch=fake_fetch,
    )

    assert len(resolved) == 1
    assert resolved[0].evidence["tied_candidate_count"] == 1
    assert resolved[0].confidence == 1.0


def test_no_candidates_clear_threshold_returns_empty_list():
    def fake_fetch(url, params):
        return {
            "results": [
                {"id": "https://openalex.org/A1", "orcid": None, "display_name": "Someone Else Entirely"}
            ]
        }

    resolved = disambiguate_pi_to_openalex_author(
        entity_id="e1", pi_name="Jane Researcher",
        institution_openalex_id="https://openalex.org/I1", fetch=fake_fetch,
    )

    assert resolved == []


def test_missing_orcid_on_both_candidates_never_collapses_a_genuine_tie():
    """No ORCID on either side means there's nothing safe to group on -- both
    must surface, not be silently merged."""
    def fake_fetch(url, params):
        return {
            "results": [
                {"id": "https://openalex.org/A1", "orcid": None, "display_name": "Sam Lee"},
                {"id": "https://openalex.org/A2", "orcid": None, "display_name": "Sam Lee"},
            ]
        }

    resolved = disambiguate_pi_to_openalex_author(
        entity_id="e1", pi_name="Sam Lee",
        institution_openalex_id="https://openalex.org/I1", fetch=fake_fetch,
    )

    assert len(resolved) == 2
    assert all(r.evidence["shared_orcid_with"] == [] for r in resolved)
