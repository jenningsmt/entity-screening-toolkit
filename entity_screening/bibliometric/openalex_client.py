"""Thin HTTP client for OpenAlex's live REST API (Epic E).

Verified live against the real API while designing this (see
docs/plans/2026-09-01-v3-openalex-bibliometric-affiliation-layer.md's Finding 2):
`api.openalex.org` needs no API key for the free tier (100,000 credits/day, 100
req/sec -- comfortably enough for this project's bounded "PIs surfaced by NSF award
data" scale, confirmed against OpenAlex's own current docs, which contradicts a
stale, incorrect forum claim that a key became mandatory in Feb 2026). A `mailto`
param is still worth sending for the "polite pool" (more consistent response times).

Every function accepts an injectable `fetch` callable (url, params) -> parsed JSON
dict, mirroring `entity_screening/ingestion/nsf.py:NSFAwardIngester`'s `fetch_page`
pattern -- tests never hit the live network.

`_http_get` retries on 429 plus 5xx plus a connection/timeout failure -- real,
not hypothetical. Scaling the demo NSF dataset from 2 entities to 53 real ones
(2026-09-02) reliably triggered OpenAlex rate limiting, and with no retry
logic a single 429 crashed the entire enrichment run (discarding every hit
already found) rather than the request that hit it -- fixed same-day with a
429-only retry. The 2026-09-02 remediation pass then measured real call
volume for the 53-entity dataset directly, with a call-counting fetch:

    53 entities resolved
                           1 candidate/PI    3 candidates/PI
      institution_search        53                53
      author_search              61                61
      works walks                61               183
      TOTAL                     175               297

(`disambiguate_pi_to_openalex_author` deliberately returns every tied
candidate rather than forcing a pick -- see
docs/plans/2026-09-01-v3-openalex-bibliometric-affiliation-layer.md's
Finding 3 -- so the works-walk multiplier is per resolved author *candidate*,
not per PI; a real PI resolving to three candidates is the recorded case,
not a hypothetical one.) At 175-297 sequential calls in one enrichment run, a
transient 500/502/503 or `requests.ConnectionError`/`Timeout` anywhere in
that sequence is a near-certainty, not an edge case -- and until this
widening, any one of them still aborted the whole run and discarded every
hit already found, exactly the failure mode the original 429-only retry was
added to prevent, just reachable via a different failure.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import requests

API_BASE_URL = "https://api.openalex.org"
DEFAULT_TIMEOUT = 30
WORKS_PAGE_SIZE = 200
MAX_RETRIES = 3
RETRY_BACKOFF_BASE_SECONDS = 1.0
MAX_RETRY_DELAY_SECONDS = 30.0
# 5xx codes worth retrying -- transient server-side failures, not 501 (Not
# Implemented), which retrying can never fix.
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

FetchFn = Callable[[str, dict[str, Any]], dict[str, Any]]


def _http_get(url: str, params: dict[str, Any]) -> dict[str, Any]:
    attempt = 0
    while True:
        try:
            response = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
        except (requests.ConnectionError, requests.Timeout):
            if attempt >= MAX_RETRIES:
                raise
            time.sleep(min(RETRY_BACKOFF_BASE_SECONDS * (2**attempt), MAX_RETRY_DELAY_SECONDS))
            attempt += 1
            continue

        if response.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
            retry_after = response.headers.get("Retry-After")
            delay = (
                float(retry_after)
                if retry_after
                else RETRY_BACKOFF_BASE_SECONDS * (2**attempt)
            )
            time.sleep(min(delay, MAX_RETRY_DELAY_SECONDS))
            attempt += 1
            continue
        response.raise_for_status()
        return response.json()


def _params(contact_email: str | None, **extra: Any) -> dict[str, Any]:
    params = {k: v for k, v in extra.items() if v is not None}
    if contact_email:
        params["mailto"] = contact_email
    return params


def search_institutions(
    query: str,
    *,
    contact_email: str | None = None,
    fetch: FetchFn | None = None,
) -> list[dict]:
    """Full-text institution search -- OpenAlex ranks server-side across its whole
    ~110K-institution corpus in one call, no bulk download or blocking needed
    (unlike GLEIF's 3.4M-row CSV)."""
    fetch = fetch or _http_get
    payload = fetch(
        f"{API_BASE_URL}/institutions", _params(contact_email, search=query, per_page=25)
    )
    return payload.get("results", [])


def search_authors(
    query: str,
    *,
    institution_openalex_id: str | None = None,
    contact_email: str | None = None,
    fetch: FetchFn | None = None,
) -> list[dict]:
    """Author search, optionally narrowed server-side to authors ever affiliated
    with a specific institution. Real data confirms this narrowing alone does not
    guarantee a single result -- see Finding 3 in the plan above."""
    fetch = fetch or _http_get
    if institution_openalex_id:
        institution_id = institution_openalex_id.rsplit("/", 1)[-1]
        filter_value = f"display_name.search:{query},affiliations.institution.id:{institution_id}"
        params = _params(contact_email, filter=filter_value)
    else:
        params = _params(contact_email, search=query, per_page=25)
    payload = fetch(f"{API_BASE_URL}/authors", params)
    return payload.get("results", [])


def get_author_works(
    author_openalex_id: str,
    *,
    contact_email: str | None = None,
    fetch: FetchFn | None = None,
    max_works: int | None = None,
) -> list[dict]:
    """All works for one author (or up to `max_works`, if given) -- each carries
    its own `authorships` array (the co-authorship graph and per-paper
    institution affiliation history in one call per page, no separate endpoint
    needed for either).

    With no cap, this pages with no limit and accumulates an author's entire
    works corpus in memory -- 456 works for Rod A. Wing (the demo dataset's
    deliberately-included prolific real PI, see docs/data_sources.md), three
    sequential round-trips. `max_works` bounds both the network cost and the
    memory footprint; a caller that sets it must record the value it used
    (e.g. `BibliometricSnapshotManifest.max_works_per_author`) since a capped
    run's coverage is a reproducibility fact, not an implementation detail --
    the same treatment `ownership/graph.py:ParentChain.truncated` already
    gives a bounded ownership walk.
    """
    fetch = fetch or _http_get
    author_id = author_openalex_id.rsplit("/", 1)[-1]
    works: list[dict] = []
    page = 1
    while True:
        payload = fetch(
            f"{API_BASE_URL}/works",
            _params(
                contact_email,
                filter=f"author.id:{author_id}",
                per_page=WORKS_PAGE_SIZE,
                page=page,
            ),
        )
        results = payload.get("results", [])
        works.extend(results)
        if max_works is not None and len(works) >= max_works:
            return works[:max_works]
        if len(results) < WORKS_PAGE_SIZE:
            return works
        page += 1
