# Phase 5 — RPS hardening

## Context

`Claude outputs/monops-remediation-strategy-2026-09-15.md` sequences the
2026-09-15 pre-ship review into six phases. Phases 1-4 shipped (Phase 4
committed as `ebe95b5`, not yet deployed). Phase 5 is next: **S9, S10,
S11, M14, M15 (+ M16's RPS half)** — restricted-party screening (RPS,
Use Case 02) hardening. Independent of Phases 3/4's HB127 case model;
per the strategy doc's own cross-cutting rule, this phase changes **no**
HB127/demo reconciliation evidence (prove it with a diff, not by
assertion) and needs **no** `DEMO_FIXTURE_VERSION` bump.

All line numbers below were re-read from the current tree on 2026-09-17
(post Phase 4). One item from the strategy doc's Phase 5 row is already
done and dropped from scope (see below).

**M16's RPS half is already closed — drop it.** The strategy doc's own
Phase 1 plan review flagged this directly: "the plan does both here
[main.py's `depth` AND rps_routes.py's `limit`]... note in the plan doc
that Phase 5's '(+ M16 RPS half)' is already done so nobody re-plans it."
Confirmed live: `rps_routes.py:190` is
`limit: int = Query(50, ge=1, le=500)`, and
`tests/test_rps.py::test_api_list_events_limit_is_bounded` already
asserts the 500/0 boundary. Nothing to build.

---

## 1. S9 — person-name RPS screening inherits organisation-name heuristics

**Current state, confirmed live (not just cited).** `resolution/normalize.py`'s
`acronym()` (lines 63-67) builds words via `re.findall(r"[A-Za-z0-9]+", name)`
— ASCII-only. A name with any non-ASCII letter outside the Latin-1
combining range (Turkish dotless ı, Cyrillic, CJK, etc.) fragments at
that character. Reproduced directly:
```python
>>> score_pair("Ana Sa", "Akın Alptuna")
MatchCandidate(confidence=0.9, match_basis='acronym', ...)
```
`transliterate("Akın Alptuna")` leaves "ı" untouched (NFKD does not
decompose it — it's a distinct base letter, not an accented one); the
ASCII-only regex then splits "Akın" into "Ak"+"n", so `acronym()` yields
"ANA" instead of "AA". Separately, `strip_corporate_suffix` (used inside
`normalize_for_matching`, called by *every* branch of `score_pair`,
including the final fuzzy fallback — not just the acronym branch) strips
"Sa" from the person's own name "Ana Sa" as if it were "Société Anonyme"
(`CORPORATE_SUFFIXES` at `normalize.py:12-33` includes `"sa"`, `"co"`).
Both defects compound into the confirmed 0.9 false-positive match above.

`resolution/matcher.py:score_pair` (lines 13-49) has no entity-kind
parameter at all — it's the single scorer shared by 12 production call
sites across HB127 institution matching, GLEIF LEI matching, OpenAlex
author/institution resolution, Section 117, and RPS
(`screening/rps_screen.py:51`, the only person-aware caller). `screening/
rps_schema.py`'s `PartyKind.PERSON` (line 57) already exists on
`ScreeningParty.kind` but is never read by the matching path.

**Fix — two independent parts, both from the review's own fix direction.**

1. **General regex fix** (`normalize.py:65`): `[A-Za-z0-9]+` → `\w+`.
   Python's `re` module is Unicode-aware by default, so `\w+` treats
   "Akın" as one word. Verified this changes nothing for every existing
   ASCII fixture (`re.findall(r'\w+', "International Business Machines
   Corporation")` → identical 4-word split; `known_difficult_pairs.json`'s
   8 pairs are all ASCII or already transliterated to ASCII before
   `acronym()` runs). This alone drops the "Ana Sa"/"Akın Alptuna" case
   to 0.4 (fuzzy fallback, well below any threshold) — confirmed by
   direct test.

2. **Person-specific bypass, additive and opt-in.** Add
   `skip_org_heuristics: bool = False` to `score_pair` and a matching
   `strip_suffix: bool = True` parameter to `normalize_for_matching`
   (`normalize.py:70-77`) so a person-aware caller can skip
   corporate-suffix stripping on **both** the normalized-exact match and
   the fuzzy-fallback score (not just the acronym branch — suffix
   stripping is baked into `normalize_for_matching` itself, so a
   person's surname colliding with a suffix token corrupts more than
   just the acronym path today). When `skip_org_heuristics=True`,
   `score_pair` skips the acronym branch entirely (both directions) and
   passes `strip_suffix=False` into both `normalize_for_matching` calls.
   Default `False` on both new parameters — the other 11 call sites
   (institution/GLEIF/OpenAlex/Section 117 matching) are untouched, byte
   for byte.
   In `screening/rps_screen.py:screen_party` (line 51), call
   `score_pair(party.name, variant, skip_org_heuristics=party.kind is
   PartyKind.PERSON)`.

   **Scope boundary, stated explicitly rather than left implicit:** this
   bypass applies only at the scoring layer (`score_pair`), not at
   `screening/lists.py`'s blocking layer (`candidates_for`/
   `_block_index`, which still index every entry under an acronym-key
   via `_acronym_key` regardless of the querying party's kind). That's
   correct for the bug as reported — a person party can still *reach* an
   org-shaped candidate through the acronym-key block (blocking is
   explicitly non-gating, "a candidate step only" per `candidates_for`'s
   own docstring), it just no longer *scores* a false acronym match once
   it gets there. A person-kind party whose name coincidentally shares
   an acronym-block key with an unrelated entry pays a (small,
   bounded-by-`BLOCK_SIZE`) unnecessary candidate-comparison cost, never
   a false match. Not fixed here; not in scope for S9's stated defect.

**Tests** (`tests/test_normalize.py`, `tests/test_matcher.py`,
`tests/test_rps.py`):
- `acronym("Akın Alptuna") == "AA"`, not the fragmented "ANA" (fails on
  the unmodified tree first).
- Existing ASCII acronym tests (`test_acronym_skips_stopwords`, the IBM/
  BIT cases) unchanged.
- `score_pair("Ana Sa", "Akın Alptuna")` → confidence < 0.5 (was 0.9).
- `score_pair("Ana Sa", "Akın Alptuna", skip_org_heuristics=True)` also
  stays low (belt-and-suspenders — the person path must not regress
  even if the regex fix alone would have been enough for this specific
  pair).
- A person-kind party whose surname is a real corporate-suffix token —
  `score_pair("Robert Co", "Robert")` — confirmed today to return
  confidence 1.0, `match_basis="normalized_exact"` (suffix-stripping
  "Co" off the person's own surname makes "Robert Co" collapse to
  "Robert"). With `skip_org_heuristics=True`, `match_basis` must not be
  `"normalized_exact"` (suffix is no longer stripped, so the two names
  are no longer byte-identical after normalization) — proving the
  bypass is real, not a no-op — while the *unmodified, org-path*
  `score_pair` (no flag) still produces the 1.0 false exact match,
  confirming the default behavior is deliberately untouched.
- `screen_party` end-to-end: a `PartyKind.PERSON` party with a non-ASCII
  name does not falsely match an unrelated org-shaped list entry that
  the pre-fix acronym bug would have caught; a `PartyKind.ORGANIZATION`
  party's existing acronym matching (e.g. against a fixture with a real
  "ZTE Corporation"-shaped entry) is unaffected.
- Full suite run (not just these files) to confirm the regex change
  causes zero regressions anywhere else `acronym`/`score_pair` is used
  (HB127, GLEIF, OpenAlex, Section 117, DoD 1260H) — this is the item's
  own stated risk surface, checked empirically, not assumed.

---

## 2. S10 — a zero-list RPS screen is indistinguishable from a clean one

**Current state, confirmed live.** `screening/rps_service.py:screen_event`
(lines 56-96) with `opensanctions_file=None` runs with `concern_lists=[]`,
writes zero matches, and writes a `ScreeningEventManifest`
(`common/manifest.py:478-537`) with `opensanctions_snapshot_date=None` —
success, no error. `ScreeningEventManifest.write()` (line 527) persists
this to `<runs_dir>/screening-events/<event_id>/manifest.json`, but
**nothing reads it back**: `ScreeningEventManifest.load()` (line 535) is
defined and currently unreferenced anywhere in production code (confirmed
by grep). `api/rps_routes.py:_event_payload` (lines 148-176), used by
both `GET /screening-events/{id}` (line 327) and every mutating route's
response, never includes the manifest at all — only event/parties/matches.
So a caller who screens with no file, or who simply `GET`s an event that
was never screened, sees the identical shape: `matches: []`. Nothing in
the DB (`screening_events`/`screening_parties`/`screening_matches` tables,
`screening/rps_store.py`) records screening state either — the manifest
file on disk is the *only* place this fact currently lives, and it's
never read.

**Fix.**
1. `_event_payload` (and its three callers: `get_event`, `screen_event`
   route, `post_disposition` route) gains a `runs_dir` parameter and
   reads the manifest back via a small helper:
   ```python
   def _load_screening_manifest(event_id: str, runs_dir) -> ScreeningEventManifest | None:
       path = Path(runs_dir) / "screening-events" / event_id / "manifest.json"
       return ScreeningEventManifest.load(path) if path.exists() else None
   ```
   (Reading the file directly rather than `event_dir()`, which has a
   `mkdir` side effect unwanted on a plain `GET`.) Adds
   `"screening_manifest": manifest.to_dict() if manifest else None` to
   the payload. `manifest is None` now means "never screened" —
   genuinely absent, not zero-and-clean.
2. **No new manifest field needed** — the three-way distinction S10
   wants is already fully derivable from what `ScreeningEventManifest`
   already carries:
   - `screening_manifest is None` → never screened.
   - `screening_manifest.opensanctions_snapshot_date is None` → screened,
     but against zero lists (a real screen ran and consulted nothing).
   - `snapshot_date is not None and match_count == 0` → screened against
     a real list, genuinely clean.
   Only `OpenSanctionsList` is ever screened here (per
   `rps_service.py`'s own module docstring — DoD 1260H is a distinct
   list for a different purpose, never used by RPS), so
   `opensanctions_snapshot_date` alone already answers "was a real list
   consulted."
3. **Not refusing a zero-list screen** — the review's fix direction
   allows either "refuse or clearly flag." Refusing would break a
   legitimate record-now-screen-later workflow; flagging is the
   fact/judgment-consistent choice (state what happened, don't block a
   caller from recording it) and is what the manifest already
   supports once it's surfaced.
4. UI (`pages/1_Restricted_Party_Screening.py`'s event detail view,
   around line 293-332): add a screening-status line above "Matches (N)"
   using the three-way distinction above — "Not yet screened" /
   "Screened against 0 lists (no snapshot consulted)" / "Screened
   against OpenSanctions, snapshot <date> — N match(es)."

**Tests** (`tests/test_rps.py`):
- `GET /screening-events/{id}` for a never-screened event →
  `screening_manifest is None` (fails on the unmodified tree first: the
  key doesn't exist at all today).
- `screen_event` with `opensanctions_file=None` → manifest present,
  `opensanctions_snapshot_date is None`, `match_count == 0` — visibly
  different from a real clean screen.
- `screen_event` with a real file, zero matches → manifest present,
  `opensanctions_snapshot_date is not None`, `match_count == 0` — the
  genuinely-clean case, distinguishable from the above by the snapshot
  date alone.
- `GET` after `POST .../screen` returns the same manifest a later `GET`
  would (persisted, not just the transient POST response).

---

## 3. S11 — every RPS screen and every case reconcile re-ingests the whole list

**Current state, confirmed live.** `rps_service.py:screen_event` (line
81) constructs a fresh `OpenSanctionsList(list(ingester.stream_records()))`
on every call — full file read, no caching. `pipeline.py:_case_concern_lists`
(lines 797-817) does the same for both `DoD1260HList` and
`OpenSanctionsList` on every case reconcile. `screening/lists.py`'s
`_block_index` (lines 102-121) caches the two-key block index, but
**per instance** — since a new list object is built every call, the
index is rebuilt every call too. On the bundled demo fixtures (~1MB)
this is fast; on the real 434MB `targets.simple.csv` it's a full parse
plus index build per screen/reconcile, in memory, on a 2GB box — exactly
the outage risk the strategy doc's own S11 note warns against
("'load once and cache' on the real file is a memory problem, not a
speed fix... scope this to per-process caching of whatever file is
configured, with the DuckDB-indexed path written up as the follow-on and
*not* attempted here").

**Fix — per-process cache keyed on (list kind, resolved path, mtime),
nothing more.** New module-level cache in `screening/lists.py` (the
natural owner of `EntityOfConcernList`/`OpenSanctionsList`/`DoD1260HList`,
and already free of any `ingestion/`-module import — kept that way by
taking a builder callable rather than importing an ingester):
```python
_list_cache: dict[str, EntityOfConcernList] = {}

def cached_concern_list(
    path: Path | str, list_key: str, build: Callable[[], EntityOfConcernList]
) -> EntityOfConcernList:
    """Per-process cache of a concern list, keyed on its resolved snapshot
    path and mtime so a file replaced at the same path (without a process
    restart) is picked up rather than served stale. Deliberately scoped
    to per-process memory only (S11's own caution against a persistent/
    shared cache becoming a different outage on a 2GB box) -- NOT the
    DuckDB-indexed follow-on, which stays a documented future item."""
    resolved = Path(path).resolve()
    cache_key = f"{list_key}:{resolved}:{resolved.stat().st_mtime_ns}"
    cached = _list_cache.get(cache_key)
    if cached is None:
        cached = build()
        _list_cache[cache_key] = cached
    return cached
```
`rps_service.py:screen_event` and `pipeline.py:_case_concern_lists` both
call this instead of constructing directly. `screen_event` currently
reads `ingester.retrieval_date` right after construction to compute
`snapshot_date` — on a cache hit no ingester is built, so the fix stashes
`retrieval_date` as a plain attribute on the built list object (both are
plain classes, not frozen dataclasses, so this is a normal attribute
set) and reads it back from the cached object either way. This is
actually a *more* correct snapshot date than today's: today,
`retrieval_date` defaults to `date.today()` on every call regardless of
whether the file's content is stale; cached, it correctly reflects when
the data was actually read.

**Explicitly not attempted, per the strategy doc's own instruction:** no
DuckDB index, no cache eviction/LRU (realistic deployments configure at
most 1-2 distinct file paths via `MONOPS_DATA_FILE_ALLOWLIST`; unbounded
growth across many distinct paths is a theoretical, deferred concern, not
a real one at this scale), no cross-process/shared cache, no locking
around concurrent cache misses (worst case: two concurrent first calls
both build and the second write wins — a wasted build, not a correctness
bug, consistent with this codebase's already-accepted M18-class
concurrency posture).

**Tests** (`tests/test_rps.py`, a new test module or a section in
`tests/test_lists.py` if one exists — confirmed absent, so a small new
one, or added to `tests/test_rps.py`):
- Two calls to `cached_concern_list` with the same `tmp_path`-created
  file → the *same* object instance (`is`), not two equal-but-distinct
  ones (fails on the unmodified tree first, since today's call sites
  build fresh objects with no caching function to call at all).
- Modifying the file's contents (and thus its mtime) between two calls
  → a *new* object, proving the cache doesn't serve stale content.
- `screen_event` called twice against the same file →
  `opensanctions_snapshot_date` identical both times (the cached
  `retrieval_date`, not a re-computed "today" each time).
- `_case_concern_lists` called twice with the same `dod_1260h_file`/
  `opensanctions_file` → same list object instances both times.

---

## 4. M14 — `ScreeningMatch` has no `matched_field`

**Current state.** `screening/rps_schema.py:ScreeningMatch` (lines
113-128) and its allowlist entry `RPS_OBSERVATION_ALLOWED_FIELDS`
(lines 141-145) both lack `matched_field`. Epic D's acceptance criterion
(`docs/requirements.md:91`) names "matched name variant, matched field"
as required evidence on every hit; `common/schema.py`'s `ScreeningHit`
already carries it (populated with a value like
`"ownership_ultimate_parent"` — which *aspect* of the subject the
matched name represents). RPS's structural equivalent, already present
on every party and unused for this purpose, is
`ScreeningParty.role_in_event` ("subject" | "current_employer" |
"prior_affiliation" | "reference" | "counterparty") — this tells a
reviewer which real-world role produced the match without a separate
join back to the party record.

**Fix.**
1. Add `matched_field: str` to `ScreeningMatch` and to
   `RPS_OBSERVATION_ALLOWED_FIELDS["ScreeningMatch"]`.
2. `screening/rps_screen.py:screen_party` (line 57, the `ScreeningMatch(`
   constructor call) stamps `matched_field=party.role_in_event` on every
   `ScreeningMatch` it builds.
3. `rps_store.py`'s `replace_matches`/`load_matches_for_event` and
   `common/storage.py`'s `screening_matches` table DDL both need the new
   column (idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, same
   pattern Phase 4's S3 used for `concern_ties.hq_country`).
4. `api/rps_routes.py:_match_dto` (lines 124-133) and the UI's matches
   table (`pages/1_Restricted_Party_Screening.py` around line 334-347)
   both surface it.

**Tests:** a hit on a `role_in_event="prior_affiliation"` party carries
`matched_field == "prior_affiliation"` through `screen_party` → API
response → UI column, verified end to end (mirrors the existing
`test_screen_party_matches_the_real_bis_entity_list_row`-style real-data
test in `tests/test_rps.py`).

---

## 5. M15 — RPS accepts `certification_required` as a disposition

**Current state, confirmed live by direct test.**
`case/vocab.py:is_valid_rps_reason_code` (lines 183-186):
```python
def is_valid_rps_reason_code(action: str, reason_code: str) -> bool:
    if action == "dismiss":
        return reason_code in RPS_DISMISS_REASON_CODES
    return reason_code in RPS_ESCALATION_REASON_CODES
```
Only special-cases `"dismiss"`; every other `WorksheetActionKind` value —
including `"certification_required"` (a Sec. 51B.153 HB127-specific
concept, structurally meaningless for RPS) and `"request_clarification"`
— falls into the escalation-vocab check and passes if the reason code
happens to be a valid escalation code. Confirmed directly:
`is_valid_rps_reason_code("certification_required",
"needs_resec_determination")` → `True` today. Nothing else gates the
`action` value itself: `api/rps_routes.py:post_disposition` converts the
request's `action` string straight to `WorksheetActionKind(...)` with no
RPS-specific restriction, so this is reachable from the real API, not
just the function in isolation (the UI's own dropdown only offers
dismiss/escalate, so this path is unreachable through the shipped UI
today — but the API has no such restriction).

**Fix.** Make the RPS action set explicit rather than "not dismiss":
```python
def is_valid_rps_reason_code(action: str, reason_code: str) -> bool:
    if action == "dismiss":
        return reason_code in RPS_DISMISS_REASON_CODES
    if action == "escalate":
        return reason_code in RPS_ESCALATION_REASON_CODES
    return False
```
`record_disposition` (`rps_service.py:99-125`) already raises `RPSError`
→ the route already turns that into a 400 — no route-level change
needed beyond this one function.

**Tests:** `is_valid_rps_reason_code("certification_required", "needs_resec_determination")`
→ `False` (fails on the unmodified tree first — currently `True`).
Same for `"request_clarification"`. `POST .../disposition` with
`action="certification_required"` → 400, end to end.

---

## Cross-cutting

**Demo evidence diff: expected empty.** This phase touches
`resolution/normalize.py`, `resolution/matcher.py` (a new optional
kwarg, default-preserving), `screening/lists.py`, `screening/rps_*`,
`case/vocab.py`'s RPS-only dicts, `common/storage.py`/`case/vocab.py`'s
RPS tables — nothing in `reconciliation/discover.py`,
`reconciliation/reconcile.py`, or `case/demo.py`. Since `score_pair`/
`acronym` are shared by the HB127 path too, the verification step is:
re-run both demo cases (`demo`, `demo-coi`) after the change and diff
against the pre-phase snapshot (stash/capture/restore/diff, as in
Phases 1/3/4) — expected **empty**, confirmed not assumed, because this
phase's fixes are either RPS-only or additive-with-a-safe-default. No
`DEMO_FIXTURE_VERSION` bump.

**Failing test first** for every item above with a real "before" state
(all five do).

**Full suite green, `cli validate` passes** before calling this phase
done — the acronym regex change in particular touches a widely-shared
function, so this is the binding check that nothing else moved.

**Docs.** Copy this plan into
`docs/plans/2026-09-17-phase-5-rps-hardening.md` (or the actual build
date if it slips), index it in `docs/plans/README.md`, dated
implementation note appended afterward — same discipline as Phases 1-4.

**Deploy is part of the phase**, per the strategy doc's cross-cutting
rule — runbook §7, confirm both demo cases still load (unaffected,
per the empty-diff acceptance criterion above) and exercise the RPS
page's screen/disposition flow on the live site.

## Verification summary (binding acceptance criteria)

- [x] `acronym("Akın Alptuna") == "AA"`; every existing ASCII acronym
      test unchanged.
- [x] `score_pair("Ana Sa", "Akın Alptuna")` confidence < 0.5 (was 0.9);
      same with `skip_org_heuristics=True` explicitly.
- [x] The 11 non-RPS `score_pair` call sites are behaviorally unchanged
      (full suite green is the proof).
- [x] `GET /screening-events/{id}` distinguishes "never screened" /
      "screened, zero lists" / "screened, clean" — three different
      payload shapes, not one.
- [x] `cached_concern_list` returns the same object on a second call
      against an unchanged file, and a new object after the file's
      mtime changes.
- [x] `screen_event`'s `opensanctions_snapshot_date` is stable across
      repeated calls against the same file (not re-computed as "today"
      each time).
- [x] `ScreeningMatch.matched_field` populated with the matched party's
      `role_in_event`, visible through the API and UI.
- [x] `is_valid_rps_reason_code` rejects `certification_required` and
      `request_clarification`; `POST .../disposition` 400s for both.
- [x] Demo-evidence diff recorded in the implementation note: empty,
      confirmed by re-running both demo cases, not assumed.
- [x] Full suite green; `cli validate` passes.
- [ ] Deployed; both demo cases confirmed unaffected; RPS screen/
      disposition flow confirmed on the live site.

## Implementation note (2026-09-17)

Built exactly as planned; no deviations. Full suite: 432 passed, 1
skipped; `cli validate` passes.

**S9**: `acronym()`'s regex fixed (`\w+`); `score_pair`/
`normalize_for_matching` both gained an additive, default-preserving
parameter (`skip_org_heuristics`/`strip_suffix`); `screen_party` passes
`skip_org_heuristics=party.kind is PartyKind.PERSON`. All 11 non-RPS
`score_pair` call sites confirmed unaffected by the full suite run. Both
independent defects (the acronym-regex fragmentation and the
suffix-stripping-collapses-a-surname bug) verified fixed with real,
reproduced-first test cases (`"Ana Sa"`/`"Akın Alptuna"`; `"Robert
Co"`/`"Robert"`), not synthetic ones invented after the fact.

**S10**: `_event_payload` now reads `ScreeningEventManifest` back from
disk (`ScreeningEventManifest.load`, previously written but never read
anywhere in production code) and exposes it as `screening_manifest` —
`None` (never screened) / present with `opensanctions_snapshot_date is
None` (screened, zero lists) / present with a real snapshot date
(genuinely screened) are now three distinguishable payload shapes. UI
gained a screening-status line above the matches table using the same
three-way distinction.

**S11**: `screening/lists.py:cached_concern_list`, keyed on (list kind,
resolved path, mtime), used by both `rps_service.py:screen_event` and
`pipeline.py:_case_concern_lists`. `retrieval_date` is stashed as a
plain attribute on the built list object so a cache hit still reports a
real snapshot date without re-building an ingester. Verified by object
identity across repeated calls (both the low-level `cached_concern_list`
unit tests and `_case_concern_lists`' own test), and by call-counting
`OpenSanctionsTargetsIngester.stream_records` end to end through
`screen_event` (0 extra calls on a second screen against the same file).
One test-isolation issue caught and fixed during this item: the
module-level cache persists for the life of the pytest process, so a
call-counting test against the suite's shared `SAMPLE_CSL_FILE` fixture
observed a false "0 calls" (an earlier test in the same session had
already warmed that exact cache key) — fixed by using a `tmp_path`-local
copy of the fixture instead, making the test hermetic regardless of
suite ordering.

**M14**: `ScreeningMatch.matched_field` added, stamped from the matched
party's `role_in_event`; threaded through the `screening_matches` table
(idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, same pattern as
Phase 4's `concern_ties.hq_country`), `rps_store.py`, the API's
`_match_dto`, and the UI's matches table (new "role" column).

**M15**: `is_valid_rps_reason_code` now explicitly checks `dismiss`/
`escalate` and returns `False` for anything else, closing the
`certification_required`/`request_clarification` gap confirmed live
before the fix (both previously validated as if they were `escalate`).

**Demo-evidence diff**: captured the full investigative-file export for
both `demo` and `demo-coi` before (git-stashed Phase 5 changes) and
after, byte-for-byte identical except `run_id` (a fresh `uuid4` per
reconcile call, the same expected non-determinism every prior phase's
diff has carried) — confirmed empty on every finding, tie, and
recitation field, not assumed. No `DEMO_FIXTURE_VERSION` bump.

**Not done in this session**: deploy. Runbook §7 and the live-site RPS
screen/disposition-flow check are still outstanding.
