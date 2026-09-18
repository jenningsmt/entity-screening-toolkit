# Phase 6 — Ops, performance, hygiene

## Context

`Claude outputs/monops-remediation-strategy-2026-09-15.md` sequences the
2026-09-15 pre-ship review into six phases. Phases 1-5 shipped and
deployed (Phase 5, RPS hardening, deployed 2026-09-17). Phase 6 is the
last: **S6-full, M11, M12, M8, M9, M22, M23, Cosmetics, S16 (optional)**
— "lowest urgency, batch when convenient." No HB127/demo reconciliation
evidence change (proved with a diff, not assumed), no
`DEMO_FIXTURE_VERSION` bump.

All line numbers below were re-read from the current tree on 2026-09-17
(post Phase 5). Two items from the strategy doc's original list are
already resolved and dropped from scope (noted where relevant): M22's
`reopen_case` was deleted in Phase 3, and `TieKind.DECLARED_AFFILIATION_DIRECT`
was wired up by Phase 4's S2 — neither is dead code anymore.

---

## 1. S6 (full) — export retention beyond the interim count cap

**Current state.** Phase 1 shipped the interim fix:
`common/manifest.py:prune_sibling_export_dirs` (currently lines 30-45),
called from both `case/export.py:export_investigative_file` (line 255)
and `pipeline.py:export_scored_entities` (line 635), caps each export
target (case_id or run_id) at `MAX_EXPORTS_PER_TARGET = 20` sibling
directories by mtime. This bounds disk growth from *repeated* requests
against the same target, but two things are still true: (1) nothing
expires an export directory by *age* — a low-traffic, long-lived
deployment can carry stale export directories indefinitely as long as
each target stays under 20; (2) the underlying write to disk on every
plain `GET` (no action secret required) still happens at all, exactly
the "unauthenticated... writes" half of S6's original finding, only now
bounded rather than eliminated.

**Blast-radius check, done empirically before deciding scope (the
review predates the interim fix and states the risk in its original,
larger form).** Both `case_id` (for the investigative-file export) and
`run_id` (for the batch CSV/XLSX export) can only come from a prior
authenticated, action-secret-gated create: `POST /cases`
(`api/case_routes.py:361`, `Depends(require_action_secret)`) and
`POST /runs` (`api/main.py:233`, same dependency) both require the
secret. An anonymous visitor cannot mint a new case_id or run_id to
multiply targets — the only targets reachable without the secret are
`demo`/`demo-coi` and whatever an authenticated operator has already
created. So the actual unauthenticated disk-growth exposure today is
already bounded to a small, fixed set of targets × 20 directories each
— materially smaller than the original review's framing (written before
the interim cap existed).

**Decision: complete the retention story with an age-based expiry
alongside the existing count cap; do not build full in-memory
streaming.** The strategy doc's own Phase 6 line names this item
"export retention/pruning," not streaming, and given the blast-radius
finding above, a full streaming rewrite (a new `StreamingResponse`/
in-memory-buffer path for both the JSON and XLSX writers, touching
`case/export.py`, `output/export.py`, and both API routes) is more
engineering than the residual risk justifies for a phase explicitly
scoped as "lowest urgency, batch when convenient." Streaming remains a
documented option if the threat model changes (e.g. if case/run
creation is ever opened up to anonymous callers).

**Fix.** Extend `prune_sibling_export_dirs` with an age cutoff, applied
*after* the existing count-based prune, without disturbing that prune's
existing `st_mtime_ns` sort key. That key is not incidental — the
function's own comment (added in Phase 1, commit `55c7e82`) explains it
was chosen specifically because the float `st_mtime` can round two
close-together writes to the same value, making "delete the oldest"
ambiguous exactly when a burst of requests (or a pruning test) makes it
matter. The new age-based loop is a separate, one-directional cutoff
comparison (`mtime < cutoff`) with no ordering/tie-breaking at stake, so
it can safely use the plain `st_mtime` `float` — no precision concern
applies there the way it does to the sort. `time` is not currently
imported in `common/manifest.py`; add it alongside the existing
`os`/`shutil`/`subprocess` imports.
```python
import time  # new

MAX_EXPORTS_PER_TARGET = 20  # unchanged
MAX_EXPORT_AGE_DAYS = 30

def prune_sibling_export_dirs(
    export_dir: Path,
    keep: int = MAX_EXPORTS_PER_TARGET,
    max_age_days: int = MAX_EXPORT_AGE_DAYS,
) -> None:
    parent = export_dir.parent
    siblings = sorted(
        (d for d in parent.iterdir() if d.is_dir()),
        key=lambda d: d.stat().st_mtime_ns,  # unchanged -- see comment above on why
    )
    for old in siblings[: max(len(siblings) - keep, 0)]:
        if old != export_dir:
            shutil.rmtree(old, ignore_errors=True)
    cutoff = time.time() - max_age_days * 86400
    for d in parent.iterdir():
        if d != export_dir and d.is_dir() and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)
```
No call-site changes needed (both existing call sites already just call
`prune_sibling_export_dirs(export_dir)` with defaults).

**Docs.** `docs/deployment-runbook.md`'s existing note on
`prune_sibling_export_dirs` (currently ~lines 245-249) gets one added
sentence stating the age-based expiry alongside the count cap.

**Tests** (`tests/test_export_dir_pruning.py` — the dedicated file for
this helper, not `test_export.py`): extend the existing 25-exports/
confirm-≤20-survive test with a second case: create a directory,
backdate its mtime past the cutoff via `os.utime`, call
`prune_sibling_export_dirs` again, confirm it's gone even though the
target is well under the count cap (fails on the unmodified tree first
— today only the count-based prune runs). The file's two existing tests
(`test_case_export_directory_count_is_capped`,
`test_batch_export_directory_count_is_capped`) must still pass
unchanged, confirming the `st_mtime_ns` sort key survived this edit.

---

## 2. M11 — `storage.connect()` re-runs the full migration set on every request

**Current state, confirmed live.** `common/storage.py:connect()`
(currently lines 443-499) runs the full `SCHEMA_DDL`, 6 `ALTER TABLE ...
ADD COLUMN IF NOT EXISTS` statements (`screening_hits`, `cases`×2,
`concern_ties`×2, `screening_matches`), 3 `UPDATE ... WHERE x IS NULL`
statements (each a real table scan), `_migrate_drop_ownership_flags_primary_key`
(a `duckdb_constraints()` catalog query), and 3
`CREATE UNIQUE INDEX IF NOT EXISTS` statements — every time. Every API
route calls `storage.connect()` fresh via its own `_connect()` helper
(`case_routes.py`, `rps_routes.py`, `main.py` each have one), so this
full sequence runs on every single HTTP request, not once at process
start.

**Fix — module-level flag keyed on the resolved `db_path`, exactly as
the strategy doc's own fix direction states.**
```python
_migrated_paths: set[str] = set()

def connect(db_path: Path | str = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path))
    resolved = str(path.resolve())
    if resolved not in _migrated_paths:
        conn.execute(SCHEMA_DDL)
        ... (every ALTER/UPDATE/migration/index statement, unchanged) ...
        _migrated_paths.add(resolved)
    return conn
```
Schema state lives in the DB file itself, not the connection object, so
skipping a *redundant* re-run of already-idempotent DDL against an
already-migrated file is safe for the normal lifecycle (many
`storage.connect()` calls against the same path within one process,
which is the common case both in production, across requests, and in
the test suite, across calls within one test).

**Accepted limitation, stated rather than silently assumed away:** if a
caller deletes and recreates a fresh, unmigrated DB file at the exact
same path *without restarting the process*, the cache would incorrectly
skip migration for that new file. Confirmed by grep that no test does
this today. This is not something the application itself ever does
(a real deploy's DB file is durable and mutated in place, never
delete-and-recreate at the same path mid-process) — a genuine but
unrealistic edge case, the same category of accepted limitation as
Phase 5's S11 cache (which also assumes a stable file identity within a
process lifetime).

**Tests:** call `storage.connect(same_path)` twice with a spy/counter on
`conn.execute` (or more simply, monkeypatch `SCHEMA_DDL`'s execution
point) confirming the ALTER/UPDATE sequence runs exactly once across two
calls to the same path, and runs again (fresh) for a second, different
path — fails on the unmodified tree first (today it runs every time).
Full suite is the regression check that nothing depends on migrations
re-running per call.

---

## 3. M12 — `record_bulk_action` is N+1

**Current state, confirmed live.** `case/service.py:record_bulk_action`
(currently lines 178-197) calls `record_action` once per `finding_id`;
`record_action` (lines 129-175) does `store.load_case` +
`store.load_findings` (the full findings list, to build a
known-finding-id set) on *every* call, plus one `INSERT` via
`store.append_worksheet_action`. A 40-row bulk dismissal is 80+ queries
(40× load_case, 40× load_findings, 40× single-row INSERT), exactly as
the review states. `record_bulk_tie_action` (lines 239-256) has the
identical structural shape, calling `record_tie_action` in a loop — but
its own docstring already says "concern-tie rows are few; the volume
problem is on the discrepancy side," and the review's M12 citation
(`service.py:166-185`) names only `record_bulk_action`. **Left as-is,
noted but out of scope** — fixing it would be free-riding scope creep
on a low-volume path the review didn't flag; if it's ever worth doing,
it's the same mechanical change as this item, ready to apply later.

**Fix — one load, one write, matching M12's own stated fix shape.**
Extract the shared, load-independent validation into a small helper so
`record_action` (single) and `record_bulk_action` (bulk) both use it
without duplicating the case-state/vocab-validation logic:
```python
def _validate_action_for_case(case, action: WorksheetActionKind, reason_code: str) -> None:
    validate = (
        is_valid_coi_reason_code
        if case.case_kind == CaseKind.COI_ANNUAL_DISCLOSURE
        else is_valid_reason_code
    )
    if not validate(action.value, reason_code):
        raise ValueError(...)  # same message as today
```
`record_action` keeps its own load_case/load_findings/append shape
(single-row calls stay simple), now calling `_validate_action_for_case`
instead of inlining the vocab check. `record_bulk_action` is
reimplemented to load once and write once — it no longer calls
`record_action` in a loop:
```python
def record_bulk_action(conn, case_id, finding_ids, action, reason_code, reason_note, actor):
    case = store.load_case(conn, case_id)
    if case is None:
        raise ValueError(f"Unknown case_id: {case_id!r}")
    if case.state == CaseState.CLOSED:
        raise CaseStateError(...)  # same message as record_action's
    _validate_action_for_case(case, action, reason_code)
    known = {f.finding_id for f in store.load_findings(conn, case_id)}
    unknown = [fid for fid in finding_ids if fid not in known]
    if unknown:
        raise ValueError(f"finding_id(s) {unknown!r} not in case {case_id!r}")
    batch_id = str(uuid.uuid4())
    recorded_at = _now()  # one shared timestamp for the whole batch -- it is one act
    actions = [
        WorksheetAction(finding_id=fid, action=action, reason_code=reason_code,
                         reason_note=reason_note, actor=actor, recorded_at=recorded_at,
                         batch_id=batch_id)
        for fid in finding_ids
    ]
    store.append_worksheet_actions(conn, case_id, actions)  # new, batched
    return batch_id, actions
```
New `case/store.py:append_worksheet_actions(conn, case_id, actions:
list[WorksheetAction])` using `conn.executemany(...)` (the same
multi-row insert pattern `replace_ties`/`replace_matches` already use),
mirroring `append_worksheet_action`'s existing single-row SQL shape.
Net: a 40-row bulk call goes from 80+ queries to 3 (load_case,
load_findings, one `executemany`).

**Tests:** existing `tests/test_case_lifecycle.py::test_bulk_action_dispositions_a_class_with_one_reason_and_one_batch_id`
already covers correctness (same `batch_id`, all effective) — re-run
unchanged as the regression check. New test: an `unknown_finding_id`
mixed into the list raises with all unknowns named, not just the first
one hit (a real behavior change from today's per-row loop, which raises
on the first bad id and silently leaves earlier ones in the batch
already committed — the new all-or-nothing validate-first shape is
strictly safer). Query-count assertion (a query-logging fixture or a
monkeypatched `store.load_case`/`load_findings` call counter) confirming
exactly one call each across a 10-id bulk action — fails on the
unmodified tree first (today: 10 calls each).

---

## 4. M8 — `PROVENANCE_NOTICE` is demo-specific text stamped on every case's export

**Current state, confirmed live.** `case/export.py:PROVENANCE_NOTICE`
(currently lines 50-62) asserts a `SYNTH...`-prefixed LEI and cites
`tests/fixtures/demo_case/gleif.NOTICE.md` — both facts specific to the
bundled demo fixture. `build_investigative_file` (line ~117-121) stamps
this notice on *every* case's export unconditionally, including one
created via `POST /cases` with its own real or synthetic data that has
nothing to do with the demo's GLEIF fixture.

**Fix — select by case id, per the review's own stated fix direction.**
`case/export.py` gains two more notices and a small selector:
```python
DEMO_PROVENANCE_NOTICE = PROVENANCE_NOTICE  # unchanged text, renamed for clarity

GENERIC_SYNTHETIC_NOTICE = (
    "SYNTHETIC DEMONSTRATION DATA -- NOT A REAL FINDING ABOUT ANY REAL PERSON "
    "OR COMPANY. This case's subject and declaration were marked synthetic at "
    "creation (use-case-01 Section 9). Do not treat this file, in whole or in "
    "part, as a screening determination."
)
GENERIC_REAL_CASE_NOTICE = (
    "This case's subject and declaration were NOT marked synthetic at "
    "creation. This file may contain real personal and institutional data; "
    "handle per this office's data-handling policy."
)

def _provenance_notice(case_id: str, synthetic: bool) -> str:
    if case_id in (demo.DEMO_CASE_ID, demo.DEMO_COI_CASE_ID):
        return DEMO_PROVENANCE_NOTICE
    return GENERIC_SYNTHETIC_NOTICE if synthetic else GENERIC_REAL_CASE_NOTICE
```
`build_investigative_file` calls `_provenance_notice(case_id, synthetic)`
using the same `synthetic` boolean it already computes at that point.
New import: `from entity_screening.case import demo` (no cycle —
confirmed `case/demo.py` only imports `case/store.py`, not
`case/export.py`).

**Tests:** demo/demo-coi exports still carry the exact existing GLEIF-
specific text (regression, not a behavior change for the two cases that
matter operationally); a non-demo `synthetic=True` case gets the generic
synthetic notice; a non-demo `synthetic=False` case gets the generic
real-case notice — three distinct cases, not one blanket string
(fails on the unmodified tree first: today all three get the demo text).

---

## 5. M9 — "Declared affiliations" sheet has no header with zero rows

**Current state, confirmed live.** `case/export.py:_write_xlsx` (line
~312) is the one sheet writer in that function still using
`pd.DataFrame(payload["declaration"]["affiliations"]).to_excel(...)`
directly, with no `columns=` — unlike every other sheet in the same
function, which already goes through the local `sheet(writer, name,
rows, columns)` helper specifically so the header renders even with
zero rows (the concern-ties plan's own AC 9).

**Fix.** Add `_DECLARED_AFFILIATION_SHEET_COLUMNS` next to the file's
existing `_FINDING_SHEET_COLUMNS`/`_TIE_SHEET_COLUMNS`/etc. constants,
matching `payload["declaration"]["affiliations"]`'s existing dict keys
(`affiliation_id`, `source_id`, `institution_name`, `country`, `role`,
`start_date`, `end_date`, `activity_kind` — from
`build_investigative_file`'s own construction of that list). Route the
"Declared affiliations" sheet through the same `sheet()` helper instead
of the bare `pd.DataFrame(...).to_excel(...)` call.

**Tests:** export a case whose declaration has zero affiliations (or a
declaration with `affiliations=()`); open the resulting XLSX and assert
the "Declared affiliations" sheet has the header row present with the
right column names even though it has zero data rows — fails on the
unmodified tree first (today: a header-less, columnless empty sheet).

---

## 6. M22 — dead code and leftover scaffolding

**Verified against the current tree (not the 2026-09-15 review's stale
snapshot) — two of the review's original items no longer apply:**
- `ownership/flagging.py:compute_foreign_control_flag` — already deleted
  in Phase 4.
- `case/service.py:reopen_case` — already deleted in Phase 3 (S5); the
  generic `/transition` route is what the API uses. Nothing to do.
- `TieKind.DECLARED_AFFILIATION_DIRECT` + its skeleton + UI label — no
  longer dead. Wired up by Phase 4's S2: constructed in
  `reconciliation/discover.py:ties_from_declared_affiliations` (called
  from `pipeline.py:753`), with a real test
  (`tests/test_reconciliation.py`'s `test_ties_from_declared_affiliations_...`
  tests). **Remove from scope — do not delete.**

**Confirmed still dead, to delete:**
1. `common/manifest.py:AdversaryListManifest` + `.from_adversary_list`
   (currently ~lines 413-472) — constructed only in
   `tests/test_adversary_list.py::test_adversary_list_manifest_from_adversary_list`
   (line 57-63), never by any production code (export, worksheet UI, or
   `cli.py validate`, despite the class's own docstring claiming those
   consumers read from it). Delete the class and its test.
2. `explanation/store.py:load_explanations_for_case` (line ~99) —
   confirmed zero callers anywhere, production or test. Delete.
3. `common/storage.py:load_paper_embeddings` (line ~900) — zero callers.
   Delete.
4. `common/storage.py:load_topic_similarity_flags` (line ~945) — zero
   callers (`tests/test_topic_similarity.py` calls
   `compute_topic_similarity_flags`/`load_corpus` from a different
   module, never this one). Delete.
5. `common/attribution.py:registered_sources` (line ~100) — zero
   callers. Delete.
6. `screening/adversary_list.py:AdversaryCountryList.citations_for`
   (line ~59) — called only by
   `tests/test_adversary_list.py::test_load_adversary_list_loads_the_bundled_four_dni_ata_countries`
   (`assert adversary_list.citations_for(code)`). Delete the method;
   update that one test line to read `adversary_list.countries[code]`
   directly (the method was a thin wrapper: `self.countries.get(...)`)
   — same assertion, same coverage, no method needed to make it.
7. Unused test imports (confirmed exact current lines, several shifted
   from the review's stale citations):
   - `tests/test_topic_similarity.py:1-2` — `import datetime`,
     `import uuid`, neither referenced anywhere else in the file.
   - `tests/test_output_contract.py` (now line 135, not 144) —
     `from entity_screening.case import demo, export, service, store`:
     `store` is never referenced again in the file; `demo`/`export`/
     `service` are all used. Drop `store` from the import.
   - `tests/test_pii_never_in_manifests.py` — line 12
     (`from pathlib import Path`, `Path(` never used again) and line 14's
     import (same `demo, export, service, store` shape — `store` unused,
     the other three used). Drop the unused ones.

**Doc correction, not a code change:** `docs/plans/2026-09-14-foreign-adversary-list-ingester.md`'s
§3 claim that `AdversaryListManifest` is "loaded from the curated JSON's
own provenance... giving the rest of the codebase (export, worksheet UI,
docs) one typed place to read the derivation from" was never true in
production — append a dated correction note (this plan's own §7
below applies the same "append, don't rewrite" convention here).

**Tests:** full suite green after each deletion is the regression check
(no new tests needed for a deletion — the absence of a compile/import
error and unchanged pass count is the proof). `cli validate` unaffected
(none of these six are part of the observation-graph allowlist
machinery).

---

## 7. M23 — the git-dependent manifest test fails on an exported tree

**Current state, confirmed live.** `tests/test_manifest.py::test_git_commit_falls_back_to_git_rev_parse_when_env_unset`
(currently lines 73-79) asserts `_git_commit()` returns a real 40-char
hash by shelling out to `git rev-parse HEAD` — passes only inside an
actual git checkout, fails (or hangs/errors) on any exported tree with
no `.git` directory (e.g. a source tarball, a Docker build context that
excludes `.git` per `.dockerignore` — the exact scenario
`_git_commit`'s own docstring names as why `GIT_COMMIT` is baked in for
the container build in the first place).

**Fix.**
```python
_REPO_GIT_DIR = Path(__file__).resolve().parent.parent / ".git"

@pytest.mark.skipif(
    not _REPO_GIT_DIR.exists(),
    reason="requires a real git checkout (.git present) -- fails on an exported tree",
)
def test_git_commit_falls_back_to_git_rev_parse_when_env_unset(monkeypatch):
    ...  # unchanged body
```
Add `Path` (from `pathlib`) and `pytest` imports to `test_manifest.py`
if not already present.

**Tests:** none needed beyond the guard itself — this *is* the test
fix. Confirm the guard doesn't fire in this repo (it's a real checkout,
so the test still runs and passes) as the acceptance check.

---

## 8. Cosmetics

Verified each against the current tree; two of the review's seven items
turned out to already be fixed or already correct — noted, not
re-applied.

1. **Evaluative ranking language in comments, `case/export.py:172,316`.**
   Both comments justify concern-ties-before-findings ordering as "the
   higher-stakes ones" — evaluative ranking language in the one module
   whose own docstring is about redaction/provenance discipline, not
   evaluation. Reword to the statutory-distinction rationale the
   concern-ties plan actually gives: concern ties are the Sec.
   51B.151(b) *tie* test, findings are the Sec. 51B.153 *omission* test
   — ordering reflects which statutory question a reader hits first,
   not a severity judgment.
2. **String comparison instead of enum, `pipeline.py:770`.**
   `t.tie_kind.value == "own_affiliation_history"` → `t.tie_kind ==
   TieKind.OWN_AFFILIATION_HISTORY` (import already present in that
   file). No behavior change.
3. **Understated docstring, `pipeline.py:686`.** `reconcile_case`'s
   docstring says it "Advances the case from DISCOVERY to WORKSHEET";
   the code (line ~759) also advances from INTAKE and
   DECLARATION_ASSEMBLY, which `create_case`'s own flow relies on.
   Reword to name all three source states.
4. **`EXPLANATION_ALLOWED_FIELDS` naming, `explanation/schema.py:130`.**
   The review says this "lacks the leading underscore its two siblings
   have" — checked directly: only one of the two actual siblings
   (`_OBSERVATION_GRAPH_ALLOWED_FIELDS`) has the underscore;
   `RPS_OBSERVATION_ALLOWED_FIELDS` (added for RPS, predates this
   remediation series) does not either, so the review's premise is only
   half true today. Renaming `EXPLANATION_ALLOWED_FIELDS` →
   `_EXPLANATION_ALLOWED_FIELDS` for consistency with the dict checked
   by the identical `cli.py validate` mechanism is still worth doing
   (small, contained: one import + 4 references, all in `cli.py`,
   confirmed by grep); leaving `RPS_OBSERVATION_ALLOWED_FIELDS`
   unrenamed since the review never named it and touching a second,
   unrelated subsystem's naming isn't this item's scope.
5. **Positional `INSERT ... VALUES` in `case/store.py`.** `cases`,
   `findings`, and `concern_ties` already moved to named columns in
   earlier phases; `subjects` (line 71), `declarations` (line 156),
   `worksheet_actions` (line 642), `tie_actions` (line 699),
   `adjudications` (line 773), and `certifications` (line 815) still use
   bare positional `VALUES (?, ?, ...)`. Add a `_XXX_COLUMNS` constant
   for each (same pattern `_CASE_COLUMNS`/`_FINDING_COLUMNS`/`_TIE_COLUMNS`
   already establish) and switch each `INSERT` to name them explicitly —
   purely mechanical, no behavior change. `demo_meta` (line 754, a
   2-column key/value table) is left alone — positional is not a
   readability problem at 2 columns, and it's not named in the review.
6. **`infra/user_data.sh:27`'s `REPO_URL`, checked and confirmed
   already correct.** `REPO_URL="https://github.com/jenningsmt/entity-screening-toolkit.git"`
   matches the actual `git remote` this repo pushes to (confirmed
   directly from this session's own `git push` output, not assumed).
   **No change needed.**
7. **`docs/plans/README.md`'s edit-after-the-fact rule, checked and
   confirmed already correct.** The review quotes the README as saying
   "never edit a plan after the fact"; the current text (lines 13-15)
   already reads "Don't edit a plan file after the fact to match what
   shipped; if a plan meaningfully changes shape mid-build, that's
   worth its own note in the file or a follow-up plan, not a silent
   rewrite" — already the "append a dated note, don't rewrite" framing
   the review asked for (fixed sometime during Phases 1-5, evidently).
   **No change needed.**

**Tests:** none of these eight need new tests (renames, docstring/
comment wording, and mechanical column-naming with no behavior change);
full suite green is the regression check for items 2 and 5 specifically
(the only two with any code-level edit beyond comments/naming).

---

## 9. S16 — the CLI case subcommand claim (optional feature, decided: correct the docs, don't build it)

**Current state, confirmed live.** `cli.py:build_parser` (currently
lines 454-529) has exactly two subcommands, `run` and `validate` — no
`case` subcommand exists. Three real claims are still live in committed
plan docs:
- `docs/plans/2026-09-06-use-case-01-implementation.md:277` — "called by
  both the API and a new CLI subcommand."
- `docs/plans/2026-09-06-use-case-01-implementation.md:412` — "A `GET
  /cases/dismissal-basis-summary` route (+ CLI report) aggregates..."
- `docs/plans/2026-09-06-use-case-01-implementation.md:506` — "New `cli`
  case subcommand runs reconcile → worksheet → export against fixtures,
  headless."
- `docs/plans/2026-09-15-step-6-coi-annual-disclosure-reuse.md:133,141` —
  lists `cli.py` among "every existing HB-127 call site" for case
  creation and names "`cli.py`'s case-creation path," neither of which
  exists.

**Decision: correct the documents; do not build the subcommand.** Per
the strategy doc's own §9: "S16 is a feature dressed as a finding...
Build it only if the demo-scenario work needs it — and if so, plan it
as that work's dependency, not as remediation." No demo-scenario
generation work is active or planned right now, so building a new,
untested CLI surface as part of a "lowest urgency, hygiene" phase would
be exactly the scope creep the strategy doc warns against.

**Fix.** Append one dated correction note to each of the two plan
files (matching `docs/plans/README.md`'s own "append a dated note,
don't rewrite" convention, applied here to a plan doc's stale claim
rather than its shipped shape) — not a claims edit in place. Each note:
states plainly that no CLI `case` subcommand, dismissal-basis-summary
CLI report, or CLI case-creation path was ever built; cites this
Phase 6 plan and S16 as the source of the correction; and repeats the
strategy doc's own framing (build it later, as a real feature, only if
demo-scenario generation needs it).

**Tests:** none — this is a documentation-only correction.

---

## Cross-cutting

**Demo evidence diff: expected empty.** Nothing in this phase touches
`reconciliation/discover.py`, `reconciliation/reconcile.py`, or
`case/demo.py`'s reconciliation path. `case/export.py`'s M8/M9 changes
touch *export rendering*, not reconciliation output — the demo/demo-coi
provenance notice text is unchanged (M8 explicitly preserves it for
those two case ids), and the M9 sheet-header fix only changes an XLSX
sheet's header row, not JSON export content or any stored finding/tie
field. Verification: re-run both demo cases' JSON investigative-file
export before/after and diff — expected empty. No `DEMO_FIXTURE_VERSION`
bump.

**Failing test first** for every item with a real "before" state (S6,
M11, M12, M9, M23 all do; M8 has a real "before" — every case gets the
same notice — even though it's a rendering choice, not a bug in the
find-a-fact sense).

**Full suite green, `cli validate` passes** before calling this phase
done.

**Docs.** Copy this plan into
`docs/plans/2026-09-17-phase-6-ops-performance-hygiene.md`, index it in
`docs/plans/README.md`, dated implementation note appended afterward —
same discipline as Phases 1-5.

**Deploy is part of the phase**, per the strategy doc's cross-cutting
rule — runbook §7, confirm both demo cases load, confirm a fresh
investigative-file export for a non-demo test case shows the generic
(not demo-specific) provenance notice on the live site.

## Verification summary (binding acceptance criteria)

- [x] `prune_sibling_export_dirs` expires directories older than
      `MAX_EXPORT_AGE_DAYS` in addition to the existing count cap
      (fails on the unmodified tree first).
- [x] `storage.connect()` runs the full migration sequence at most once
      per resolved `db_path` per process (fails on the unmodified tree
      first).
- [x] A 10-id `record_bulk_action` call does one `load_case`, one
      `load_findings`, one batched insert — not 10 of each (fails on
      the unmodified tree first); a mixed unknown/known id list names
      every unknown id, not just the first.
- [x] Demo/demo-coi exports keep their exact existing GLEIF-specific
      provenance text; every other case gets a generic synthetic
      notice (revised from the plan's original three-way split — see
      the Implementation note's deviation record).
- [x] The "Declared affiliations" XLSX sheet renders its header row
      with zero data rows (fails on the unmodified tree first).
- [x] Six confirmed-dead functions/classes deleted (`AdversaryListManifest`,
      `load_explanations_for_case`, `load_paper_embeddings`,
      `load_topic_similarity_flags`, `registered_sources`,
      `citations_for`); `compute_foreign_control_flag`/`reopen_case`/
      `TieKind.DECLARED_AFFILIATION_DIRECT` confirmed already
      resolved and correctly left alone; unused test imports removed.
- [x] The git-dependent manifest test is `skipif`-guarded and still
      passes in this real checkout.
- [x] All eight cosmetic items resolved or confirmed already correct,
      per item 8's own accounting (2 already fixed, 6 applied).
- [x] Two plan docs carry a dated correction note striking the false
      CLI-case-subcommand claim; no subcommand built.
- [x] Demo-evidence diff recorded in the implementation note: empty,
      confirmed by re-running both demo cases, not assumed.
- [x] Full suite green; `cli validate` passes.
- [ ] Deployed; both demo cases confirmed loading; a live non-demo
      export confirmed showing the generic provenance notice.

## Implementation note (2026-09-17)

Built as planned, with one real design correction found and made during
implementation (below) and everything else landing as scoped. Full
suite: 439 passed, 1 skipped; `cli validate` passes.

**Deviation from the plan: M8's provenance notice is two-way, not
three-way.** The plan's `_provenance_notice` design branched on
`case_id` *and* `synthetic`, with a `GENERIC_REAL_CASE_NOTICE` for a
hypothetical non-synthetic case. Building it surfaced a real system
invariant the plan hadn't checked: `Subject.__post_init__` and
`Declaration.__post_init__` both raise `ValueError` if `synthetic is
not True` ("a real subject is unrepresentable, not merely
discouraged" — their own docstrings), and `POST /cases` constructs
`Subject` before `Case`, wrapped in a `try/except ValueError -> 400`.
So no case can ever exist end-to-end with non-synthetic data — the
"real case" branch was dead code by construction, the same category of
problem M22 spent this whole phase removing elsewhere. Corrected to a
two-way selector (`DEMO_PROVENANCE_NOTICE` for `demo`/`demo-coi`,
`GENERIC_PROVENANCE_NOTICE` for every other, always-synthetic, case)
before writing any test or implementation code, so nothing dead was
ever committed. `case/export.py`'s own new comment block documents this
finding at the constants' definition site, not just here.

**S6-full**: `prune_sibling_export_dirs` gained `MAX_EXPORT_AGE_DAYS`
(30), applied after the existing count-based prune, with the `st_mtime_ns`
tie-avoiding sort key on the count-based prune left untouched (this was
flagged during the plan's own review as a regression risk in an earlier
draft's code snippet — the shipped code keeps the fix).

**M11**: `storage.connect()` now gates the full DDL/ALTER/UPDATE/index
sequence on a module-level `_migrated_paths` set keyed on resolved
`db_path`, confirmed via a real `conn.execute` call-count test (14 calls
on first connect, 0 on a second connect to the same path, 14 again for
a genuinely different path).

**M12**: `record_bulk_action` reimplemented to load the case and
findings list exactly once (not once per id) and validate every id
before writing anything -- a mixed unknown/known id list now names
every unknown id and commits nothing, versus the old per-row loop's
raise-on-first-bad-id-after-partial-commit. New
`case/store.py:append_worksheet_actions` batches the insert via
`executemany`. `record_bulk_tie_action` was confirmed to have the
identical N+1 shape but left alone -- ties are low-volume by the
codebase's own docstring, and the review's M12 citation names only the
finding-side function.

**M9**: the "Declared affiliations" sheet now goes through the same
`sheet()` helper (with an explicit `columns=`) as every other sheet;
added to `test_output_contract.py`'s existing header-row-survives-zero-
rows assertion list alongside Adjudications/Certifications/Concern
ties/Tie actions.

**M22**: six confirmed-dead symbols removed (`AdversaryListManifest` +
`.from_adversary_list`, `load_explanations_for_case`,
`load_paper_embeddings`, `load_topic_similarity_flags`,
`registered_sources`, `citations_for`), each verified dead by direct
grep immediately before deletion, not from the stale review snapshot.
`compute_foreign_control_flag` (deleted in Phase 4), `reopen_case`
(deleted in Phase 3), and `TieKind.DECLARED_AFFILIATION_DIRECT` (wired
up by Phase 4's S2) were all confirmed already resolved and correctly
left untouched. Dated correction notes appended to
`docs/plans/2026-09-14-foreign-adversary-list-ingester.md` (the
`AdversaryListManifest` claim) and a cross-reference note added directly
in `common/manifest.py`'s `ScreeningEventManifest` docstring, which had
referenced the now-deleted class by name.

**M23, Cosmetics, S16**: all landed exactly as planned -- no deviations.

**Demo-evidence diff**: captured the full investigative-file export for
both `demo` and `demo-coi` before (git-stashed Phase 6 changes) and
after, byte-for-byte identical except `run_id` (the same expected
non-determinism every prior phase's diff has carried) -- confirmed
empty on every finding, tie, recitation, and provenance-notice field,
not assumed. No `DEMO_FIXTURE_VERSION` bump.

**Not done in this session**: deploy. Runbook §7 and the live-site
generic-provenance-notice check on a non-demo export are still
outstanding.
