# Streamlit UI for restricted-party screening (step 5)

*Plan as approved via Claude Code plan mode, 2026-09-14. Historical record — read
`git log` for what actually shipped.*

---

## Context

RPS (step 5) was fully built and tested but only reachable via raw API calls with
the action secret. Per instructions: a new Streamlit page under `pages/` (Streamlit's
standard multi-page auto-discovery convention, sibling to `app.py`), not an addition
to `app.py` — the same separation `rps_schema.py`'s own docstring already states for
the object graph should show up in the UI. Shared sidebar config/HTTP-helper
boilerplate factored out of `app.py` first, so a second page doesn't duplicate it.

**Two real gaps found while reading the existing code for this, not hypothetical:**

1. **No listing endpoint** — `api/rps_routes.py` only had create-by-trigger and
   `GET /{event_id}`. Addressed before the browse view was built against it.
2. **A real security gap in the endpoint the new "screen" button would call**, found
   while checking how `case_routes.py` handles caller-supplied file paths.
   `case_routes.py` never accepts a caller-supplied file path at all (`ReconcileRequest`
   has no file field; `reconcile()` always passes the server's own bundled
   demo-fixture paths). The *older* batch `/runs` endpoints in `api/main.py` do accept
   caller-supplied paths, and are protected by `_check_allowlisted`/
   `_allowed_data_files` (`MONOPS_DATA_FILE_ALLOWLIST`, set on the public deployment
   via `docker-compose.prod.yml`). **`rps_routes.py`'s `POST
   /screening-events/{id}/screen` was built in step 5 with `ScreenRequest.
   opensanctions_file: str | None` accepting any caller-supplied path, with no
   allowlist check at all** — unnoticed because nothing called it from a UI yet.
   Closed before wiring a UI that would actually invoke it.

## What was built

1. **`ui_common.py`** (new, repo root) — `render_logo()`, `SidebarConfig` (frozen
   dataclass), `render_sidebar_config()` (API base URL + `/health` gate check +
   "Analyst" + "Actions" sections), `get()`/`post()` HTTP helpers. `app.py` refactored
   to call these; its own "Case" sidebar section stays in `app.py`. Verified
   behavior-preserving by running the real HB127 worksheet end-to-end via
   `streamlit.testing.v1.AppTest` against a live `uvicorn` server (correct title, 3
   metrics rendered, no exception) both before and after the refactor.
2. **`GET /screening-events`** (new route, `api/rps_routes.py`) + `rps_store.
   list_events(conn, trigger=None, limit=50)` — reverse-chronological, optional
   trigger filter, summary fields only (`event_id`/`trigger`/`case_id`/
   `requested_by`/`requested_at`) — `GET /{event_id}` stays the detail call. Open,
   not gated, like every other read in this API.
3. **Allowlist fix** — `api/deps.py` gained `allowed_data_files()`/
   `check_allowlisted()`, identical logic to `api/main.py`'s existing
   `_allowed_data_files`/`_check_allowlisted`, duplicated per that module's own
   stated "kept in lockstep, deliberately tiny" convention (avoids a circular import
   with `main.py`). `rps_routes.py`'s `screen_event` now calls
   `check_allowlisted(request.opensanctions_file, allowed_data_files())` before the
   path reaches `rps_service.screen_event`/`OpenSanctionsTargetsIngester`. `api/main.py`'s
   own copies, and the routes that use them, are untouched.
4. **`pages/1_Restricted_Party_Screening.py`** (new) — a separate Streamlit page,
   auto-discovered by Streamlit's `pages/` convention into the sidebar switcher:
   - A visible synthetic-data warning near the top (mirrors the HB127 page's ⚠
     SYNTHETIC badge) — every created event sends `synthetic=True`; no toggle, per
     `ScreeningEvent.__post_init__`'s hard construction guard.
   - Three top-level tabs, one per trigger (Hire / Visiting scholar / Purchasing),
     matching the real API DTOs exactly. The Hire tab's optional prior-affiliations/
     references lists use small session-state-backed repeatable rows, not
     `st.data_editor` (chosen per review: fewer empty-row/type-coercion edge cases for
     a short, occasionally-empty list). The Purchasing tab has no `case_id` field at
     all — the API never accepts one for that trigger either.
   - A browse section against the new listing endpoint (optional trigger filter,
     dataframe, open-by-selection).
   - A detail view: a "Screen this event" button (always screens against the bundled
     `demo_opensanctions_targets.csv` — the same file the HB127 demo case already
     uses — rather than a free-text path field, so the UI doesn't invite the exact
     attempt the allowlist fix above exists to stop), parties/matches dataframes, an
     evidence expander mirroring the case worksheet's "Evidence (traversal path...)"
     pattern, and a per-match disposition control pulling `RPS_DISMISS_REASON_CODES`/
     `RPS_ESCALATION_REASON_CODES` from `GET /screening-events/reason-codes`, gated
     behind the same `actions_enabled` pattern as every mutating control on the HB127
     page.
5. **Tests** (`tests/test_rps.py` +5, new `tests/test_rps_ui.py` +2):
   `rps_store.list_events` ordering + trigger-filter tests, an API test for `GET
   /screening-events`, and two allowlist tests (`test_screen_endpoint_rejects_a_path_
   outside_the_allowlist` / `..._accepts_a_path_inside_the_allowlist`) mirroring
   `tests/test_api_security.py`'s existing style. `tests/test_rps_ui.py` uses
   `streamlit.testing.v1.AppTest` against a real FastAPI `TestClient` (monkeypatching
   `requests.get`/`post`, no separately-run server needed): one test that the page
   loads without exception, one that drives a full create → screen → disposition
   click-path through real Streamlit widgets and asserts a real match (a genuine
   BIS Entity List entry already confirmed present in the demo fixture) is produced
   and actioned.

## Verification

- `pytest -q` — 301 passed (294 pre-existing + 5 store/API + 2 UI smoke).
- `python -m entity_screening.cli validate` — passed.
- Manual: ran a real `uvicorn`/AppTest session against the live API — the sidebar
  page switcher shows both pages; the HB127 worksheet renders identically
  post-refactor; the RPS page's full create/browse/screen/disposition flow works
  against real demo data end to end.
- `docker` CI job's corpus-path parity assertion untouched.

## Explicit scope boundary

- No change to the HB127 worksheet's own behavior beyond the `ui_common` refactor.
- No shared worksheet combining RPS matches with HB127 findings/ties — `case_id`
  stays a plain display label.
- No pagination beyond `list_events`'s `limit` parameter.
- No event editing/deletion — matches the API, which has none.
- No loosening of `ScreeningEvent.__post_init__`'s synthetic-only guard.
