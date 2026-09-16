# Phase 1 — Monops public-surface hotfix (rev 2, post-review)

## Context

`Claude outputs/monops-remediation-strategy-2026-09-15.md` sequences the
2026-09-15 pre-ship review
(`Claude outputs/monops-pre-ship-review-2026-09-15.md`) into six phases.
Phase 1 is the first: small, isolated fixes visible to every anonymous
visitor of the public demo, deployable in one cycle without touching
reconciliation output. It bundles two blocking UX bugs (B2, B3), one blocking
false-negative in screening coverage (B4), two live security holes (S7, S8),
a test-coverage gap that must close *before* any route change (S12), and two
small hardening items (M16, S6-interim).

This is rev 2. `Claude outputs/monops-phase-1-plan-review-2026-09-16.md`
reviewed rev 1 against the tree at `5c4afb1` and confirmed every citation
except six problems, all addressed below: a `NameError` bug in the B4
snippet (§6), an end-to-end test for B4 that the route can't actually support
(§6), an acceptance criterion (the demo-evidence diff) that was
under-specified to the point of being unpassable (§6 and cross-cutting), a
`GET`/`POST` cache-key mismatch in B2's design (§2), a scope gap in
S6-interim (only one of two export paths was capped) (§8), and four
strategy-doc obligations (§8/§9 of the strategy doc) the plan had skipped
(folded into §2, §6, and Deploy below). Everything re-verified against the
tree today; new citations noted where they differ from rev 1.

Goal (unchanged): every anonymous visitor can use what the demo page says
they can use; no visitor can make the server fetch arbitrary URLs, read
unredacted classified fields, or fill the disk; a clean subject can close;
non-demo cases get concern-list screening of their own affiliations.

**Does this phase change demo evidence?** No. Acceptance criterion (now fully
specified — see §6's "Demo-evidence diff" and the note on `discovery_sources`
ordering): reconcile both demo cases before and after every change in this
phase; the findings/ties JSON must diff empty under a stated normalization.

---

## Build order

### 1. S12 — structural gating-coverage test (build and pass *before* any route change)

**Current state.** One `app` in `entity_screening/api/main.py` mounts both
routers (`include_router` at lines 445, 452), so `TestClient(app)` sees the
full route table. Confirmed inventory: `case_routes.py` has exactly 12
`@router.post` routes (lines 331, 411, 512, 523, 534, 561, 589, 616, 644, 662,
682, 707), every one gated with `Depends(require_action_secret)`
(`api/deps.py:44-56`); `rps_routes.py` has 5 (215, 248, 280, 309, 336), all
gated; `main.py` has 4 (232, 334, 362, 385), all gated on its own
textually-separate but logic-identical `_require_action_secret`
(`main.py:154-165`, kept separate deliberately to avoid a circular import per
`deps.py`'s module docstring). **No `PUT`/`PATCH`/`DELETE` routes exist
anywhere.** Existing 403 coverage is thin: one case-route assertion
(`tests/test_api_case.py:185`), none in `tests/test_rps.py`, and
`tests/test_api_security.py` (already `from entity_screening.api.main import
app`) covers only the batch routes.

**Fix.** Extend `tests/test_api_security.py` (same file already does this
class of test for the batch routes):
- Import both gate functions: `require_action_secret` (`api/deps.py`) and
  `_require_action_secret` (`api/main.py`); `_GATE_FUNCS = {require_action_secret,
  _require_action_secret}`.
- An explicit, empty allowlist constant:
  `_UNGATED_MUTATING_ROUTES: set[tuple[str, str]] = set()`, with a comment
  that any future entry must be justified in the same commit, not inferred.
- A parametrized test walking `app.routes`: for each route whose `methods`
  includes `POST`/`PUT`/`PATCH`/`DELETE` and whose `(method, path)` is not in
  the allowlist, assert one of `_GATE_FUNCS` appears among
  `route.dependant.dependencies[*].call`, then issue a live `TestClient`
  request with `MONOPS_ACTION_SECRET` set, no header, **and an explicit empty
  JSON body (`json={}`)** — not no body at all. FastAPI validates the request
  body before resolving the route function but *after* resolving
  dependencies for most cases; sending a body-shaped payload avoids a
  malformed/missing body producing a 422 that could be mistaken for the 403
  this test wants. Assert 403.
- Run it once, unmodified, against the current tree first — must be green
  before any other Phase 1 change lands (the strategy doc's explicit
  ordering constraint, and §8's "failing test first" rule doesn't apply here
  since there's no bug yet — S12 is scaffolding for the rest, not a fix
  itself).

### 2. B2 — ungated `GET` for cached explanations (cache-key fixed per review §5)

**Current state.** `case_routes.py:512-531` — both
`POST /{case_id}/findings/{finding_id}/explanation` and
`POST /{case_id}/ties/{tie_id}/explanation` are gated, and both call the
shared `_explain()` helper (lines 470-509), which always invokes
`explanation_service.explain(...)` (line 498) — a real, possibly-costed
Claude call, correctly gated. `_render_explanation_expander` in
`pages/0_HB127_Case_Worksheet.py` (function starts at line 235) renders
`st.button("Generate explanation", ...)` at **line 246** with no `disabled=`
kwarg — the only mutating button in the file without one (eight others do:
lines 184, 338, 367, 441, 457, 482, 498, 509). So the button is always
clickable and the `POST` always 403s anonymously.

`entity_screening/explanation/service.py` — `explain()`'s cache key is
`(observation_id, evidence_hash)` (line 62:
`store.load_explanation(conn, observation_id, evidence_hash)`), and
`evidence_hash` is computed by `_evidence_hash(observation)` (lines 27-37),
which folds in `MODEL` and `PROMPT_VERSION` — not just the observation's
content. **Rev 1's plan filtered `load_explanations_for_case` by
`observation_id` alone and took the first match** — wrong whenever a
model/prompt bump leaves two rows for the same `observation_id` (the older,
now-stale one would win, and it could disagree with what `explain()` itself
would consider cached).

**Fix — reuse `_explain`'s own lookup logic instead of duplicating it.**
1. In `case_routes.py`, factor the "find the primary observation or 404"
   half of `_explain` (currently inlined at lines 478-492) into a small
   helper `_find_primary_or_404(findings, ties, observation_kind,
   observation_id, case_id) -> Finding | ConcernTie`, and have `_explain`
   call it. This is a pure refactor of existing logic — no behavior change to
   the `POST` path.
2. Promote `explanation/service.py`'s private `_evidence_hash` to a public
   `evidence_hash_for` (rename; update its one call site inside `explain()`
   at line 60). It's a pure content-hash function with no side effects —
   promoting it is the smaller change versus reaching across modules into a
   leading-underscore name, per the review's suggestion.
3. Add `from entity_screening.explanation import store as explanation_store`
   (new alias; `store` is already taken by the case store in this file).
4. New helper:
   ```python
   def _cached_explanation_or_404(
       conn, case_id: str, observation_kind: ObservationKind, observation_id: str
   ) -> dict:
       _load_case_or_404(conn, case_id)
       findings = store.load_findings(conn, case_id)
       ties = store.load_ties(conn, case_id)
       primary = _find_primary_or_404(findings, ties, observation_kind, observation_id, case_id)
       evidence_hash = explanation_service.evidence_hash_for(primary)
       cached = explanation_store.load_explanation(conn, observation_id, evidence_hash)
       if cached is None:
           raise HTTPException(
               status_code=404,
               detail=f"No cached explanation for {observation_kind.value} {observation_id!r} in case {case_id!r}",
           )
       return _explanation_dto(cached)
   ```
5. Two new ungated routes, `GET /{case_id}/findings/{finding_id}/explanation`
   and `GET /{case_id}/ties/{tie_id}/explanation`, thin wrappers around the
   helper. No `Depends` — never generates, so S12's walk correctly excludes
   them from the gated set.

This gives the `GET` and `POST` paths the *same* notion of "the cached
explanation," including the same 404-on-unknown-observation behavior, for
free — and it means a prompt/model bump (Phase 2) correctly makes the demo's
pre-generated rows a cache miss on both paths consistently, rather than the
`GET` serving a stale row the `POST` would already consider invalid.

**UI.** In `_render_explanation_expander`: on expander open, try the new
`GET` via a `_get(...)` call (mirroring the existing wrappers, lines
123-128). Catch `requests.HTTPError` and check
`exc.response.status_code == 404` specifically to mean "no cached row yet" —
any other status (5xx, etc.) must still surface as an error caption, not be
swallowed as "not cached." Render the cached explanation on a 200. Only show
the "Generate explanation" button, `disabled=not _actions_enabled` (matching
every other button), when there's no cached row. If there's no cached row
and `_actions_enabled` is `False`, show a caption instead of a dead button
(mirroring `ui_common.py:141`'s existing "⚠️ Enter the action secret..."
pattern).

**Tests.** Reconcile the demo case (pre-generates explanations via
`_ensure_demo_case_exists`); anonymous `TestClient`, secret set, no header:
`GET` a known finding's explanation → 200, cached row; `POST` the same → 403;
`GET` an unknown id → 404. Add a unit test for `evidence_hash_for` /
`_cached_explanation_or_404` proving that after a synthetic model/prompt
bump (monkeypatch `MODEL` or `PROMPT_VERSION`), the old cached row is no
longer returned by the `GET` (404, matching what `explain()` would also
treat as a miss) rather than served stale.

### 3. S8 — API base URL becomes env-only on a deployed image; belt-and-braces on `case_id`

**Current state.** `ui_common.py:119-121` always renders the API-base-URL
text input, defaulting to `os.environ.get("API_BASE_URL",
"http://localhost:8000")` — the env var is only the widget's default; the
live value is whatever the visitor types. `get()`/`post()` (lines 152-161)
build every URL by bare f-string concatenation, `f"{cfg.api_base_url}{path}"`.
No existing "local-dev-only widget" pattern anywhere in this codebase (grepped
for `DEBUG`/`LOCAL`/`dev_mode`/`ENVIRONMENT`) — generalizes from the
server-side action-secret gate that already exists. `case_id` is free text
(`pages/0_HB127_Case_Worksheet.py:120`), interpolated unvalidated into every
path built from it (worksheet, reconcile, explanation, both export routes at
523/528).

**Fix.** In `render_sidebar_config`: read `API_BASE_URL` from the
environment first; render the `st.text_input` (default
`http://localhost:8000`) only when it's unset. Deployed image sets the env
var, so no visitor ever sees or can edit the field; local dev (unset)
unchanged.

**`case_id` — confirmed safe, plus a cheap belt-and-braces fix.** Because
`api_base_url` is a fixed prefix and `case_id` is always sandwiched inside a
literal path template (`f"/cases/{case_id}/worksheet"`), no `case_id` value
can make the request resolve to a different host — there's no way for
mid-path user text to produce a scheme-relative or absolute URL. The one real
oddity: a `case_id` containing `?` or `#` could be parsed by the HTTP library
as the start of a query string or fragment, truncating the intended path (not
an SSRF escape, but worth closing since it's one line). Fix: in
`0_HB127_Case_Worksheet.py`, wrap the `case_id` read once —
`case_id = urllib.parse.quote(st.text_input("Case ID", value=DEMO_CASE_ID), safe="")`
— covering all five interpolation sites through the one variable, rather than
touching each call site.

**Tests.** New test (extend an existing UI test file if one covers
`ui_common`, else a new `tests/test_ui_common.py`) asserting, via a
monkeypatched `requests.get`/`.post`, that for a `case_id` containing
`://evil.example`, `..`, a leading `//`, or `?`, the resulting request URL
always starts with `cfg.api_base_url` and resolves to no other host; and that
the quoted `case_id` round-trips correctly for the ordinary case (no
behavior change for normal ids).

### 4. S7 — `redact=false` requires the action secret

**Current state.** `case_routes.py:725-733` — both export routes take
`redact: bool = True` as a plain, ungated query param; `_export` at 736-754.
No `Header`/`Query` import in this file yet. `require_action_secret`
(`deps.py:44-56`) is a plain function taking
`x_monops_action_secret: str | None = Header(default=None)` — callable
directly, not only via `Depends`.

**Fix.** Add `Header` to the `fastapi` import. Give both export handlers an
`x_monops_action_secret: str | None = Header(default=None)` parameter; when
`redact` is `False`, call `require_action_secret(x_monops_action_secret)`
directly before `_export` (raises 403 on missing/wrong secret). `redact=True`
(default) stays fully open. This is a conditional, parameter-dependent gate,
not a blanket route dependency, so S12's walk correctly leaves it alone (it's
a `GET`); it gets its own explicit test instead.

**Tests.** `redact=false`, no header → 403; correct header → 200 with
`classified_fields` present; `redact` omitted/`true` → unchanged, 200, open.

### 5. B3 — a clean, zero-observation case can close

**Current state.** `service.py`: `worksheet()` (94-120) computes `unactioned`
(108-110) and a local `total = len(rows) + len(tie_rows)` (111), used only
once, at line 119: `can_close=(unactioned == 0 and total > 0)`. `Case`
(`schema.py:377-387`) has no run/manifest field to key "reconciliation has
run" on instead. Verified independently: `_TRANSITIONS`
(`service.py:47-55`) only admits `WORKSHEET` from `DISCOVERY`, and the only
code that ever writes `state=CaseState.WORKSHEET` is `pipeline.py:760`,
inside `reconcile_case` itself. So a case in `WORKSHEET` has necessarily
already been reconciled — `total > 0` was never actually gating on "did
reconciliation run," it was only ever blocking the "ran, found nothing"
case, which is a normal outcome (a clean subject), not an error state.

**Fix.** Delete the now-unused `total` local; change line 119 to
`can_close=(unactioned == 0)`. Fix the `CaseStateError` message (257-262) to
be self-consistent using the existing `WorksheetView.rows`/`.tie_rows`
fields (no new field needed): report `f"Case {case_id!r} has
{view.unactioned_count} of {len(view.rows) + len(view.tie_rows)} worksheet
row(s) unactioned. ..."` — it can no longer read "has 0 unactioned... row(s)"
while still blocking, since `can_close` is now exactly `unactioned == 0`.

**Test-first.** Run the *new* test below against the unmodified tree first
to confirm it fails (raises `CaseStateError`) before making the change, per
the strategy doc's "failing test first for every B and S item" rule.

**Test.** New test in `tests/test_case_lifecycle.py` (extends the existing
`_demo_conn`-based pattern, lines 27-40/77-94, but needs a fresh, minimal
fixture — the demo fixtures always yield 2 findings + 1 tie): create a case
via `service.create_case` with a `Declaration` whose only affiliation is the
one already declared, reconcile with a `discovered` set that adds nothing
new and no GLEIF files, confirm 0 findings / 0 ties, `worksheet(...).can_close`
is `True`, and `service.transition(conn, case_id, CaseState.ADJUDICATION)`
succeeds without raising.

### 6. B4 — concern-list screening of the subject's own affiliations runs unconditionally

**Current state (re-read in full, `pipeline.py:657-775`).** Lines 716-740,
verbatim:
```python
discovery_sources = ["openalex", "foreign_adversary_countries"]      # 716

ties: list[ConcernTie] = []                                          # 718
if gleif_lei_file and gleif_relationships_file:                      # 719
    run_dir = Path(runs_dir) / "cases" / case_id                     # 720
    run_dir.mkdir(parents=True, exist_ok=True)                       # 721
    error_log = IngestionErrorLog(run_dir / "ingestion_errors.jsonl")# 722
    load_gleif_level1(conn, gleif_lei_file, date.today(), error_log) # 723
    load_gleif_level2(conn, gleif_relationships_file, date.today(), error_log)  # 724

    concern_lists = _case_concern_lists(                             # 726-728
        error_log, dod_1260h_file, opensanctions_file
    )
    error_log.close()                                                # 729

    ties += tie_from_ownership(                                      # 731-734
        case_id, run_id, list(declaration.affiliations), conn, concern_lists,
        adversary_list,
    )
    ties += ties_from_own_affiliations(                              # 735-737
        case_id, run_id, discovered, concern_lists
    )
    discovery_sources += ["gleif_ownership", "dod_section_1260h"]    # 738
    if opensanctions_file:                                           # 739
        discovery_sources.append("opensanctions")                     # 740
```
**Rev 1's "fix" snippet dropped line 720 (`run_dir = Path(runs_dir) /
"cases" / case_id`)** while moving the `mkdir`/`IngestionErrorLog` calls
above the `if` — every reconcile (demo and non-demo alike) would `NameError`
on the first line. Fixed below by moving the assignment too.

`_case_concern_lists` (778-798) needs only `error_log`, `dod_1260h_file`
(bundled by default), `opensanctions_file` — no GLEIF dependency.
`ties_from_own_affiliations` (`reconciliation/discover.py:348`,
signature `(case_id, run_id, discovered_affiliations, concern_lists, *,
concern_threshold)`) — no `conn`, no GLEIF. Only `tie_from_ownership`
(`discover.py:241`, signature `(case_id, run_id, declared_affiliations, conn,
concern_lists, adversary_list, *, lei_threshold)`) genuinely needs GLEIF
(queries GLEIF tables via `conn`). The `reconcile` route
(`case_routes.py:422-430`) passes GLEIF only for `demo`/`demo-coi`, and never
passes `opensanctions_file` for any case.

**Fix — restructure so concern-list screening always runs, and preserve
`discovery_sources`'s exact existing order (both demo cases carry GLEIF, so
this keeps their manifest field byte-identical, which the demo-evidence-diff
acceptance criterion below depends on):**
```python
discovery_sources = ["openalex", "foreign_adversary_countries"]
ties: list[ConcernTie] = []

run_dir = Path(runs_dir) / "cases" / case_id
run_dir.mkdir(parents=True, exist_ok=True)
error_log = IngestionErrorLog(run_dir / "ingestion_errors.jsonl")

gleif_ready = bool(gleif_lei_file and gleif_relationships_file)
if gleif_ready:
    load_gleif_level1(conn, gleif_lei_file, date.today(), error_log)
    load_gleif_level2(conn, gleif_relationships_file, date.today(), error_log)

concern_lists = _case_concern_lists(error_log, dod_1260h_file, opensanctions_file)
error_log.close()

if gleif_ready:
    ties += tie_from_ownership(
        case_id, run_id, list(declaration.affiliations), conn, concern_lists, adversary_list,
    )
    discovery_sources.append("gleif_ownership")

ties += ties_from_own_affiliations(case_id, run_id, discovered, concern_lists)
discovery_sources.append("dod_section_1260h")

if opensanctions_file:
    discovery_sources.append("opensanctions")
```
For a GLEIF-supplied case (both demo cases today), the final
`discovery_sources` is `["openalex", "foreign_adversary_countries",
"gleif_ownership", "dod_section_1260h"]` — **identical order to today**.
For a non-demo case with no GLEIF: `["openalex", "foreign_adversary_countries",
"dod_section_1260h"]` — correctly omits `gleif_ownership`. Side effect worth
noting: `run_dir`/`error_log` are now created for every reconcile, not just
GLEIF-backed ones — intended, since DoD-1260H/OpenSanctions ingestion can
also log errors and previously had nowhere to put them when GLEIF was absent.

**Non-demo ownership-path limitation — document, don't solve.** Add a
"Known limitations" heading to `docs/architecture.md` (none exists today —
grepped) stating: *"Ownership-parent screening (`tie_from_ownership`)
requires a GLEIF Level 1/2 snapshot; only the demo's 2-row fixture is bundled
today, so non-demo cases created via `POST /cases` do not get ownership-tie
screening. 1260H/OpenSanctions screening of the subject's own
declared/discovered affiliations (`ties_from_own_affiliations`) has no such
dependency and always runs."*

**Tests.**
1. Unit test on `ties_from_own_affiliations` directly (none exists today —
   grepped) with a `discovered` affiliation matching a `dod_1260h.json`
   entry, confirming a `ConcernTie` with
   `tie_kind == TieKind.OWN_AFFILIATION_HISTORY` (`schema.py:485`).
2. **End-to-end, at the `pipeline.reconcile_case` layer, not through the API
   route** (rev 1 proposed going through `POST /cases` + `POST
   .../reconcile`, but `case_routes.py:427` passes
   `works_fixture=demo.load_demo_works_fixture() if is_demo else None` — a
   non-demo case always gets `works_fixture=None`, so the route has no way to
   hand it a fixture without hitting the live OpenAlex network; `tests/
   test_pipeline*.py` already tests at the `reconcile_case` layer directly,
   which is exactly the function this fix changes). Call
   `pipeline.reconcile_case(case_id, ..., works_fixture=<fixture with a
   discovered affiliation named "NIO, Inc.">, gleif_lei_file=None,
   gleif_relationships_file=None)` — reusing the real bundled
   `dod_1260h.json` entry "NIO, Inc." (`entity_screening/screening/data/
   dod_1260h.json:1638-1644`, id `1260h-0204`) needs no new list file.
   Assert 1 finding / 1 own-affiliation-history tie, and that
   `manifest.discovery_sources` includes `"dod_section_1260h"` but not
   `"gleif_ownership"`.
3. Run tests 1-2 against the unmodified tree first to confirm they fail
   (test 2 currently: 0 ties, no `dod_section_1260h`), per the "failing test
   first" rule.

**Demo-evidence diff — fully specified (this was the acceptance criterion
rev 1 left unpassable as written).** `reconcile_case` regenerates `run_id`
(`pipeline.py:688`, fresh `uuid4` every call) and `finding_id`/`tie_id` (also
per-run `uuid4`s — confirmed via `service.py`'s own docstring on
`_evidence_hash`/`evidence_hash_for`); `ConcernTie` also carries `run_id` and
`related_finding_id`. A byte-for-byte diff of two reconciles is *never*
empty even on a no-op change. Procedure: reconcile both demo cases before
and after this change; for each finding/tie row, strip `run_id`,
`finding_id`, `tie_id`, `related_finding_id`, `anchor_affiliation_id` (confirm
at build time whether it's per-run — treat it as such if so), and any
`generated_at`/`*_at` timestamp; sort rows by `(source, institution_name)`
for findings and `(tie_kind, concern_entity_name)` for ties (order is
otherwise random per M10, unrelated to this phase, and not itself part of
the diff); then compare the remaining fields. `discovery_sources` order is
preserved exactly by the restructure above, so it does not need to be
excluded from the comparison — include it. Expect zero differences.

### 7. M16 — ceilings on `limit` and `depth`

**Current state.** `rps_routes.py:190` —
`list_events(trigger: str | None = None, limit: int = 50)`, no ceiling.
`main.py:413-418` — `get_ownership_chain(run_id, entity_id, direction: str =
"up", depth: int = 10)`, no ceiling on the recursive CTE. No existing
`fastapi.Query(...)` usage anywhere under `entity_screening/` — new pattern.

**Fix.** Import `Query` from `fastapi` in both files.
`limit: int = Query(50, ge=1, le=500)` in `rps_routes.py`;
`depth: int = Query(10, ge=1, le=25)` in `main.py`. 500 is generously above
any real screening-event volume for this deployment; 25 is well above any
real ownership chain depth GLEIF data produces (1-3 hops observed in the
remediation-pass verification work) while still bounding the CTE's worst
case.

**Note for the phase table.** The strategy doc's Phase 5 line lists "(+ M16
RPS half)" as if the RPS half of M16 ships separately in Phase 5; this plan
does both halves now, in Phase 1, per the strategy doc's own §2 item 7
("ceilings on `limit` and `depth`," unsplit). Recording this here so Phase 5
planning doesn't re-plan already-shipped work.

**Tests.** `GET /screening-events?limit=5000` → 422 (FastAPI's own
validation error). `GET /runs/{id}/ownership/{entity}?depth=1000` → 422.
Existing default-value tests unchanged.

### 8. S6 (interim) — cap export-directory growth on *both* export paths

**Current state.** Two independent, structurally identical export paths both
write a fresh, never-pruned directory per ungated `GET`:
- `case/export.py:225-258` (`export_investigative_file`) →
  `InvestigativeFileManifest.export_dir` (`common/manifest.py:548-551`):
  `{runs_dir}/cases/{case_id}/investigative_file/{export_id}/`. Routes:
  `case_routes.py:725-733`.
- `pipeline.py:612-640` (`export_scored_entities`) →
  `ExportManifest.export_dir` (`common/manifest.py:151-154`):
  `{runs_dir}/{source_run_id}/exports/{export_id}/`. Routes:
  `main.py:320-331` (`/runs/{run_id}/export.csv|xlsx`, via `main.py:295-317`'s
  `_export`). **Rev 1 only capped the first path** — the pre-ship review
  named both (S6 cites both route families explicitly).

No `StreamingResponse` anywhere in this codebase and no existing
pruning/cleanup helper — full in-memory streaming (S6-full) would be new
code and is out of scope for this hotfix, matching the strategy doc's own
"if full streaming is more than a day" fallback to a directory-count cap.

**Fix — one shared helper, since both paths are structurally identical.**
Add to `entity_screening/common/manifest.py` (natural home: both manifest
classes already live here, and both call sites already import from here):
```python
MAX_EXPORTS_PER_TARGET = 20

def prune_sibling_export_dirs(export_dir: Path, keep: int = MAX_EXPORTS_PER_TARGET) -> None:
    """Caps disk growth from repeated, ungated exports: after a fresh
    export_dir is created, deletes the oldest sibling directories (by mtime)
    until at most `keep` remain, the new one included."""
    parent = export_dir.parent
    siblings = sorted(
        (d for d in parent.iterdir() if d.is_dir()),
        key=lambda d: d.stat().st_mtime,
    )
    for old in siblings[: max(len(siblings) - keep, 0)]:
        if old != export_dir:
            shutil.rmtree(old, ignore_errors=True)
```
Call `prune_sibling_export_dirs(export_dir)` right after `export_dir =
export_manifest.export_dir(runs_dir)` in both `export_investigative_file`
(`case/export.py`, after line 248) and `export_scored_entities`
(`pipeline.py`, after line 632). Both files already import from
`common.manifest`; add `prune_sibling_export_dirs` to each import list plus
`shutil` if not already imported.

**Tests.** For each of the two export functions: call it (or hit the `GET`
route) 25 times for one target id; confirm at most `MAX_EXPORTS_PER_TARGET`
sibling directories remain and that the survivors are the newest by mtime
(check by mtime/export_id, not by assuming iteration order). Home: whichever
file currently covers export (`tests/test_export.py` for the case path;
confirm the equivalent for the batch path at build time).

---

## Cross-cutting

**S12's test is written and green first**, before steps 2-8 touch a route.
Re-run it after steps 2 and 4 (the only steps that add/modify routes) to
confirm the new/changed routes are categorized correctly.

**Failing test first for every B/S item** (§8 of the strategy doc, made
explicit per item above): B3, B4's two new tests, S7, and S8's URL test are
all to be run red against the unmodified tree before the corresponding fix
lands, not just written alongside it. (S12 has no "before" state to fail
against — it's scaffolding, already noted above. B2's tests are naturally
red-then-green since the routes don't exist yet.)

**Full suite green, `cli validate` passes** — same bar as every prior phase.

**Deploy is part of the phase.** Per `docs/deployment-runbook.md` §7,
including these Phase-1-specific additions:
- **Correct the nginx rate-limit claim** (strategy doc §9, previously
  missing from this plan): `infra/nginx/monops.conf`'s comment at line 63
  ("the rate limit above is the actual defence against volume") and
  `docs/deployment-runbook.md:214-217`'s equivalent claim both need
  correcting to reflect that the websocket-exempt rate limit does not cover
  UI-driven API calls (S6's finding) — do this as a doc-only edit in the same
  deploy, not deferred to Phase 6.
- **§7b's warm-up already exercises both demo cases** (`_ensure_demo_case_exists`
  builds/reconciles `demo` and `demo-coi` together on first access) but the
  runbook's current single `curl .../cases/demo/worksheet` doesn't say so —
  add a second `curl .../cases/demo-coi/worksheet` to §7b so the runbook
  proves both load rather than relying on the reader knowing the side
  effect.
- **The fresh-Lightsail-rebuild question**
  (`docs/2026-09-09-repository-archaeology-report.md:278`, `:358`, and the
  open question at `:551`) stays explicitly deferred, not closed, in this
  phase — Phase 1's deploy is a `git pull` + `systemctl restart` against the
  existing instance (per the runbook's established procedure), not a rebuild
  from scratch; closing that question is its own, larger exercise (spin up a
  second Lightsail instance from Terraform and diff it against the live one)
  that doesn't belong inside a hotfix deploy. State this explicitly in the
  deploy step rather than silently skip it.
- Confirm live on `https://mikejennings.dev/monops` that "Explain this
  match" returns the cached explanation for an anonymous visitor (the
  concrete B2 check the strategy doc names).

**The pre-generated-explanation mechanism (strategy doc §9, "an unknown ...
resolve during Phase 1") — answered, not unknown.**
`case_routes.py:143-157`'s `_demo_no_synthesis_call` is the fixture callable
`_ensure_demo_case_exists` (160-215) passes to `explanation_service.explain`
for every demo finding/tie: it always returns an ungrounded, no-citation
response deterministically, so every demo explanation ships recitation-only
by construction and needs no `ANTHROPIC_API_KEY` — recitation-only is a
complete, valid explanation per `explanation/schema.py`, not a stand-in for
one. This changes Phase 4's stated assumption that "regeneration needs a
live `ANTHROPIC_API_KEY`" — for the *demo* it does not, unless a future
phase deliberately decides to ship real syntheses for the demo cases.
Caveat worth carrying into Phase 2/4 planning: since `evidence_hash_for`
(renamed in this phase, §2) folds in `MODEL`/`PROMPT_VERSION`, a prompt bump
makes every pre-generated demo row a cache *miss* even though
`DEMO_FIXTURE_VERSION` hasn't moved — this phase's B2 `GET` design (§2)
already handles that correctly (404s rather than serving stale), which is
part of why the cache-key fix in §2 matters beyond just B2 itself.

**Docs.** Per this project's standing practice
([[feedback_commit_plans_to_repo]]), copy this plan verbatim into
`docs/plans/2026-09-16-phase-1-public-surface-hotfix.md` and add it to
`docs/plans/README.md`'s index as part of implementing it.

## Verification summary (binding acceptance criteria)

- [ ] S12 route-walk test passes before any other change, and again after.
- [ ] Anonymous `TestClient`: `GET` a demo explanation → 200 cached row;
      `POST` the same → 403; `GET` an uncached id → 404; a model/prompt-bump
      cache-key change makes the `GET` 404 rather than serve a stale row.
- [ ] `ui_common` URL test: malicious `case_id` values never escape
      `cfg.api_base_url`'s host; quoting doesn't change behavior for normal
      ids.
- [ ] `redact=false` → 403 with no header, 200 with the correct one;
      `redact` omitted/`true` → unchanged.
- [ ] New test: a subject with zero findings/zero ties reconciles cleanly and
      `transition(..., ADJUDICATION)` succeeds (fails on the unmodified tree
      first).
- [ ] New tests: `ties_from_own_affiliations` unit test, plus a
      `pipeline.reconcile_case`-layer end-to-end test proving a non-demo,
      no-GLEIF case screens a discovered affiliation against 1260H (both fail
      on the unmodified tree first).
- [ ] `run_dir` is assigned before use in the restructured `reconcile_case`
      (the rev-1 `NameError` is gone) — confirmed by every reconcile test
      passing, demo and non-demo alike.
- [ ] Demo-evidence diff (both demo cases, before/after B4), under the
      stated id/timestamp normalization and row sort, including
      `discovery_sources`: empty.
- [ ] `limit`/`depth` over their ceilings → 422.
- [ ] Export-directory count never exceeds `MAX_EXPORTS_PER_TARGET` on
      *both* the case-export and the batch-export path.
- [ ] Full suite green; `cli validate` passes.
- [ ] Deployed and confirmed live; nginx/runbook rate-limit claim corrected;
      §7b checks both demo cases; Lightsail-rebuild question explicitly
      recorded as deferred (not silently skipped).

---

## Implementation note (2026-09-16)

All eight build-order items landed, in the order above, each with its test
written and run against the unmodified tree first where the plan called for
it (§1 confirmed green pre-existing; §5, §6 tests confirmed red before the
fix). Full suite: 368 passed, 1 skipped (the pre-existing environment-
dependent git test), `cli validate` passes. Two things worth recording
because they weren't fully anticipated in the plan text:

- **S12's implementation deviated from the plan's described mechanism.**
  The plan said to walk `app.routes` and inspect
  `route.dependant.dependencies[*].call`. On the FastAPI version actually
  installed (0.141.1), `include_router()` is lazy: `app.routes` holds an
  internal `_IncludedRouter` wrapper for each mounted router, not flat
  `APIRoute` objects, so that inspection path doesn't work without reaching
  into private (`_`-prefixed) FastAPI internals. The test instead walks
  `TestClient(app).get("/openapi.json").json()["paths"]` — FastAPI's own
  public, already-flattened route listing — and asserts a live 403 for every
  mutating (method, path) pair not in the (empty) allowlist. This is
  actually more black-box than the planned approach (behavioral proof
  instead of dependency-graph introspection) and needed no change to the
  binding acceptance criterion. See `tests/test_api_security.py`.
- **The export-dir pruning test exposed a filesystem timestamp-granularity
  issue, not a logic bug.** `prune_sibling_export_dirs` sorts siblings by
  mtime; a tight test loop creating 25 directories back-to-back hit ties
  at this filesystem's actual mtime update granularity (~15ms bursts,
  confirmed by instrumentation), making "the survivors are the N most
  recent" flaky *in the test* even though the count cap itself (≤ 20) held
  on every run. Switched the sort key to `st_mtime_ns` (doesn't fully fix
  it alone) and added a 20ms sleep between calls in the two new pruning
  tests (`tests/test_export_dir_pruning.py`) to match the spacing a real
  HTTP round-trip would have — not a production code concern, since real
  anonymous requests are never this tightly packed.

Not done as part of this phase, by design: the actual deploy (runbook §7,
including the §7b/nginx/rate-limit doc edits already made) and the
Lightsail-rebuild question remain for whoever runs the deploy step, since
this session has no access to the live instance's SSH credentials. The
`docs/how-this-was-built.md` file shows as modified in `git status` but was
not touched by this work — that's a separate, pre-existing uncommitted
change from another session, left alone.
