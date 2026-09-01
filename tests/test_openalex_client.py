import json
from pathlib import Path

from entity_screening.bibliometric import openalex_client

FIXTURES_DIR = Path(__file__).parent / "fixtures"
RESPONSES = json.loads((FIXTURES_DIR / "sample_openalex_responses.json").read_text(encoding="utf-8"))


def test_search_institutions_returns_real_shaped_results():
    calls = []

    def fake_fetch(url, params):
        calls.append((url, params))
        return RESPONSES["institutions_search_beijing_institute_of_technology"]

    results = openalex_client.search_institutions("Beijing Institute of Technology", fetch=fake_fetch)

    assert len(results) == 1
    assert results[0]["display_name"] == "Beijing Institute of Technology"
    assert results[0]["display_name_acronyms"] == ["BIT"]
    assert calls[0][0] == f"{openalex_client.API_BASE_URL}/institutions"
    assert calls[0][1]["search"] == "Beijing Institute of Technology"


def test_search_institutions_includes_mailto_when_contact_email_given():
    captured = {}

    def fake_fetch(url, params):
        captured.update(params)
        return {"results": []}

    openalex_client.search_institutions("X", contact_email="me@example.com", fetch=fake_fetch)

    assert captured["mailto"] == "me@example.com"


def test_search_authors_without_institution_uses_plain_search():
    captured = {}

    def fake_fetch(url, params):
        captured.update(params)
        return {"results": []}

    openalex_client.search_authors("Andrew Felton", fetch=fake_fetch)

    assert captured.get("search") == "Andrew Felton"
    assert "filter" not in captured


def test_search_authors_with_institution_filters_server_side_and_still_returns_a_real_tie():
    """Real data: even filtering server-side to authors ever affiliated with the
    exact target institution ID returns 3 candidates, not 1 -- two of which share
    an ORCID (a real, confirmed OpenAlex duplicate-author-record issue)."""
    captured = {}

    def fake_fetch(url, params):
        captured.update(params)
        return RESPONSES["authors_search_andrew_felton_montana_state"]

    results = openalex_client.search_authors(
        "Andrew Felton", institution_openalex_id="https://openalex.org/I23732399", fetch=fake_fetch
    )

    assert "I23732399" in captured["filter"]
    assert "display_name.search:Andrew Felton" in captured["filter"]
    assert len(results) == 3
    orcids = [a["orcid"] for a in results if a["orcid"]]
    assert len(orcids) == 2
    assert len(set(orcids)) == 1  # two candidates share the same real ORCID


def test_get_author_works_returns_authorships_and_paginates_until_a_short_page():
    pages = [
        {"results": [{"id": f"W{i}"} for i in range(openalex_client.WORKS_PAGE_SIZE)]},
        {"results": [{"id": "W-last"}]},
    ]
    call_count = {"n": 0}

    def fake_fetch(url, params):
        page = pages[call_count["n"]]
        call_count["n"] += 1
        return page

    works = openalex_client.get_author_works("https://openalex.org/A5067979033", fetch=fake_fetch)

    assert len(works) == openalex_client.WORKS_PAGE_SIZE + 1
    assert call_count["n"] == 2


def test_get_author_works_real_shaped_authorships():
    def fake_fetch(url, params):
        return RESPONSES["works_by_author_A5067979033_page_1"]

    works = openalex_client.get_author_works("A5067979033", fetch=fake_fetch)

    assert len(works) == 1
    authorships = works[0]["authorships"]
    assert len(authorships) == 2
    co_author = authorships[0]["author"]
    assert co_author["display_name"] == "Michael Stemkovski"
    assert authorships[0]["institutions"][0]["display_name"] == "Utah State University"
