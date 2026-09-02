import json
from pathlib import Path

import pytest
import requests

from entity_screening.bibliometric import openalex_client

FIXTURES_DIR = Path(__file__).parent / "fixtures"
RESPONSES = json.loads((FIXTURES_DIR / "sample_openalex_responses.json").read_text(encoding="utf-8"))


class _FakeResponse:
    def __init__(self, status_code, json_body=None, headers=None):
        self.status_code = status_code
        self._json_body = json_body
        self.headers = headers or {}

    def json(self):
        return self._json_body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} error")


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


def test_http_get_retries_on_429_then_succeeds(monkeypatch):
    """Real, not hypothetical: scaling the demo NSF dataset to 53 real entities
    reliably triggered OpenAlex 429s, and with no retry logic that crashed the
    whole enrichment run rather than just the one request that hit it."""
    responses = [
        _FakeResponse(429, headers={}),
        _FakeResponse(200, json_body={"results": ["ok"]}),
    ]
    calls = []
    sleeps = []

    def fake_get(url, params, timeout):
        calls.append((url, params))
        return responses[len(calls) - 1]

    monkeypatch.setattr(openalex_client.requests, "get", fake_get)
    monkeypatch.setattr(openalex_client.time, "sleep", lambda s: sleeps.append(s))

    result = openalex_client._http_get("https://api.openalex.org/institutions", {"search": "X"})

    assert result == {"results": ["ok"]}
    assert len(calls) == 2
    assert len(sleeps) == 1


def test_http_get_honors_retry_after_header(monkeypatch):
    responses = [
        _FakeResponse(429, headers={"Retry-After": "7"}),
        _FakeResponse(200, json_body={"results": []}),
    ]
    calls = []
    sleeps = []

    def fake_get(url, params, timeout):
        calls.append(1)
        return responses[len(calls) - 1]

    monkeypatch.setattr(openalex_client.requests, "get", fake_get)
    monkeypatch.setattr(openalex_client.time, "sleep", lambda s: sleeps.append(s))

    openalex_client._http_get("https://api.openalex.org/institutions", {})

    assert sleeps == [7.0]


def test_http_get_gives_up_after_max_retries_and_raises(monkeypatch):
    calls = []

    def fake_get(url, params, timeout):
        calls.append(1)
        return _FakeResponse(429, headers={})

    monkeypatch.setattr(openalex_client.requests, "get", fake_get)
    monkeypatch.setattr(openalex_client.time, "sleep", lambda s: None)

    with pytest.raises(requests.exceptions.HTTPError):
        openalex_client._http_get("https://api.openalex.org/institutions", {})

    assert len(calls) == openalex_client.MAX_RETRIES + 1


def test_http_get_retries_on_500_then_succeeds(monkeypatch):
    """Workstream 9d: widened past 429-only after measuring real call volume
    (175-297 sequential calls per enrichment run) made a transient 5xx a
    near-certainty rather than an edge case."""
    responses = [
        _FakeResponse(500, headers={}),
        _FakeResponse(200, json_body={"results": ["ok"]}),
    ]
    calls = []
    sleeps = []

    def fake_get(url, params, timeout):
        calls.append((url, params))
        return responses[len(calls) - 1]

    monkeypatch.setattr(openalex_client.requests, "get", fake_get)
    monkeypatch.setattr(openalex_client.time, "sleep", lambda s: sleeps.append(s))

    result = openalex_client._http_get("https://api.openalex.org/institutions", {"search": "X"})

    assert result == {"results": ["ok"]}
    assert len(calls) == 2
    assert len(sleeps) == 1


def test_http_get_retries_on_connection_error_then_succeeds(monkeypatch):
    calls = []
    sleeps = []

    def fake_get(url, params, timeout):
        calls.append(1)
        if len(calls) == 1:
            raise requests.exceptions.ConnectionError("connection reset")
        return _FakeResponse(200, json_body={"results": ["ok"]})

    monkeypatch.setattr(openalex_client.requests, "get", fake_get)
    monkeypatch.setattr(openalex_client.time, "sleep", lambda s: sleeps.append(s))

    result = openalex_client._http_get("https://api.openalex.org/institutions", {})

    assert result == {"results": ["ok"]}
    assert len(calls) == 2
    assert len(sleeps) == 1


def test_http_get_retries_on_timeout_then_succeeds(monkeypatch):
    calls = []

    def fake_get(url, params, timeout):
        calls.append(1)
        if len(calls) == 1:
            raise requests.exceptions.Timeout("read timed out")
        return _FakeResponse(200, json_body={"results": ["ok"]})

    monkeypatch.setattr(openalex_client.requests, "get", fake_get)
    monkeypatch.setattr(openalex_client.time, "sleep", lambda s: None)

    result = openalex_client._http_get("https://api.openalex.org/institutions", {})

    assert result == {"results": ["ok"]}
    assert len(calls) == 2


def test_http_get_gives_up_after_max_retries_on_connection_error_and_raises(monkeypatch):
    calls = []

    def fake_get(url, params, timeout):
        calls.append(1)
        raise requests.exceptions.ConnectionError("connection reset")

    monkeypatch.setattr(openalex_client.requests, "get", fake_get)
    monkeypatch.setattr(openalex_client.time, "sleep", lambda s: None)

    with pytest.raises(requests.exceptions.ConnectionError):
        openalex_client._http_get("https://api.openalex.org/institutions", {})

    assert len(calls) == openalex_client.MAX_RETRIES + 1


def test_http_get_total_retry_sleep_is_bounded(monkeypatch):
    """A throttled call can add real wall-clock time via retry sleep -- this
    is the fact Workstream 9a's timeout budgeting depends on, so pin the
    actual bound: at most MAX_RETRIES sleeps, each capped at
    MAX_RETRY_DELAY_SECONDS."""
    calls = []
    sleeps = []

    def fake_get(url, params, timeout):
        calls.append(1)
        return _FakeResponse(503, headers={})

    monkeypatch.setattr(openalex_client.requests, "get", fake_get)
    monkeypatch.setattr(openalex_client.time, "sleep", lambda s: sleeps.append(s))

    with pytest.raises(requests.exceptions.HTTPError):
        openalex_client._http_get("https://api.openalex.org/institutions", {})

    assert len(sleeps) == openalex_client.MAX_RETRIES
    assert sum(sleeps) <= openalex_client.MAX_RETRIES * openalex_client.MAX_RETRY_DELAY_SECONDS
    assert all(s <= openalex_client.MAX_RETRY_DELAY_SECONDS for s in sleeps)
