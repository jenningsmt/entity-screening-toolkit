import uuid

from entity_screening.bibliometric.institution_match import resolve_entity_to_openalex_institution
from entity_screening.common.schema import ResolvedEntity


def _entity(name: str) -> ResolvedEntity:
    return ResolvedEntity(
        entity_id=str(uuid.uuid4()), canonical_name=name, entity_type="organization",
        source_records=(),
    )


def test_resolves_exact_name_match():
    def fake_fetch(url, params):
        return {
            "results": [
                {
                    "id": "https://openalex.org/I23732399",
                    "display_name": "Montana State University",
                    "country_code": "US",
                    "display_name_acronyms": ["MSU"],
                    "display_name_alternatives": [],
                }
            ]
        }

    match = resolve_entity_to_openalex_institution(_entity("Montana State University"), fetch=fake_fetch)

    assert match is not None
    assert match.openalex_institution_id == "https://openalex.org/I23732399"
    assert match.candidate.confidence == 1.0


def test_scores_across_acronyms_and_alternatives_and_picks_the_best():
    def fake_fetch(url, params):
        return {
            "results": [
                {
                    "id": "https://openalex.org/I125839683",
                    "display_name": "Beijing Institute of Technology",
                    "country_code": "CN",
                    "display_name_acronyms": ["BIT"],
                    "display_name_alternatives": ["北京理工大学"],
                }
            ]
        }

    match = resolve_entity_to_openalex_institution(_entity("BIT"), fetch=fake_fetch)

    assert match is not None
    assert match.candidate.confidence >= 0.80


def test_returns_none_when_nothing_clears_threshold():
    def fake_fetch(url, params):
        return {
            "results": [
                {
                    "id": "https://openalex.org/I1",
                    "display_name": "Completely Unrelated University",
                    "country_code": "US",
                }
            ]
        }

    match = resolve_entity_to_openalex_institution(_entity("Fixture State University"), fetch=fake_fetch)

    assert match is None


def test_returns_none_for_empty_results():
    def fake_fetch(url, params):
        return {"results": []}

    match = resolve_entity_to_openalex_institution(_entity("Nonexistent University"), fetch=fake_fetch)

    assert match is None


def test_picks_the_best_scoring_candidate_among_multiple_results():
    def fake_fetch(url, params):
        return {
            "results": [
                {"id": "https://openalex.org/I1", "display_name": "Fixture University System"},
                {"id": "https://openalex.org/I2", "display_name": "Fixture University"},
            ]
        }

    match = resolve_entity_to_openalex_institution(_entity("Fixture University"), fetch=fake_fetch)

    assert match is not None
    assert match.openalex_institution_id == "https://openalex.org/I2"
    assert match.candidate.confidence == 1.0
