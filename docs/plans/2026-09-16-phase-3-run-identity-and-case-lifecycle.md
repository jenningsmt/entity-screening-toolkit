# Phase 3 — Run identity and case lifecycle

## Context

`Claude outputs/monops-remediation-strategy-2026-09-15.md` sequences the
2026-09-15 pre-ship review into six phases. Phases 1 (public-surface
hotfix) and 2 (Epic J grounding gate) shipped and deployed. Phase 3 is
next: **the highest-risk phase in the sequence**, per the strategy doc's
own framing — it changes how findings and ties are identified, which
touches the store, the action tables, the explanation cache, and exports.
It's deliberately placed before Phase 4 so Phase 4's re-reconciliation and
fixture bump exercise the new, safe path rather than the old destructive
one.

**The problem.** `finding_id`/`tie_id` are `uuid4()`, regenerated on every
reconciliation run. Re-running reconciliation on a case — which nothing
today prevents, even mid-worksheet — orphans every prior analyst action
(the action tables reference an id that no longer exists) and permanently
breaks the explanation cache for that case, with no state guard stopping
an analyst from doing this to their own in-progress work with one click.
Separately, the state machine lets a case reach CLOSED with no recorded
outcome, and reach OUTCOME with no recorded adjudication — two
independent gates that don't check each other.

**S5's design fork, settled against real data (not assumed).** The
strategy doc names two options and says the natural key "must be
enumerated and proven unique before locked." Researched directly against
this repo's real demo fixtures and its own tests (see §1 below): I'm
going with **deterministic ids (`uuid5`)**, per the strategy doc's own
lean, and the natural key is now enumerated and checked against a real
collision case that exists in this codebase's own test suite today, not
a hypothetical.

All line numbers below were re-read from the current tree on 2026-09-16
(post Phase 1/2).

**Does this phase change demo evidence?** The findings/ties *content* is
unchanged, but their *ids* change shape (uuid4 → uuid5) — this requires
another `DEMO_FIXTURE_VERSION` bump (Phase 2 already did 5→6 for the same
class of reason; this phase does 6→7) so the self-heal rebuilds under the
new id scheme rather than silently orphaning the demo's own pre-generated
explanations. The demo-evidence diff (content, not ids) stays empty.

---

## 1. S5 (core) — deterministic ids, natural key enumerated and proven unique

**Current state.** `entity_screening/reconciliation/reconcile.py:153`
(`build_finding`) and `entity_screening/reconciliation/discover.py:328`,
`:383` (`tie_from_ownership`, `ties_from_own_affiliations`) each call
`str(uuid.uuid4())`. `entity_screening/case/store.py`'s `replace_findings`/
`replace_ties` are pure `DELETE FROM ... WHERE case_id = ?` then
`executemany` INSERT — current-state-per-case, no continuity logic at
all. Neither `findings` nor `concern_ties` has a primary key or unique
index (`entity_screening/common/storage.py:256-297`). `discovered`/
`declaration_search`/`nearest_declared`/`concern_list_evidence`/
`ownership_evidence` are stored as `JSON` columns, not flattened — so a
SQL-level `UNIQUE` constraint has to be on the *id* (once the id itself is
a deterministic fingerprint of the natural key), not on JSON sub-fields.

**The natural key, enumerated from the actual construction sites:**
- **Finding:** `(case_id, discovered.source, discovered.institution_name)`.
  `discovered_finding_map`'s own docstring (`reconcile.py:185-192`) already
  asserts this pair is unique per run — one `DiscoveredAffiliation` per
  `(source, institution_name)` per run, hence at most one `Finding` per
  key per run. `factual_basis` doesn't need to be in the key: it's
  *computed from* the discovered item, not an independent axis a second
  Finding could vary on for the same institution in the same run.
- **ConcernTie:** `(case_id, tie_kind, anchor_affiliation_id,
  concern_entity_name)`. **Proven necessary with a real collision, not a
  hypothetical:** `tests/test_reconciliation.py:289-338`
  (`test_both_at_once_produces_one_finding_and_one_tie_joined_by_id`) feeds
  a work whose institution is literally `"NIO INC."`, and because
  `reconcile_case` always runs both `tie_from_ownership` (declared-employer
  path) and `ties_from_own_affiliations` (own-affiliation path) whenever
  GLEIF files are supplied, the result is **two ties with the identical
  `concern_entity_name` ("NIO INC.") in the same case/run**: one
  `declared_employer_ultimate_parent` (anchor=`demo-aff-subsidiary`) and
  one `own_affiliation_history` (anchor=`None`, by construction —
  `discover.py:387`). `concern_entity_name` alone collides here;
  `anchor_affiliation_id` alone doesn't disambiguate `own_affiliation_history`
  ties from each other (always `None`) or from a hypothetical second
  `declared_employer_ultimate_parent` tie with a *different* anchor but
  the same parent. All four components are load-bearing:
  `tie_kind` separates the two real ties above; `anchor_affiliation_id`
  separates two `declared_employer_ultimate_parent` ties on different
  declared affiliations that happen to share an ultimate parent (two
  employers owned by the same conglomerate); `concern_entity_name`
  separates two `own_affiliation_history` ties (always `anchor=None`) on
  different institutions. No existing test or fixture shows a second
  `own_affiliation_history` tie on the *same* institution in one run — and
  `_aggregate_own_affiliations`'s one-per-`(source, institution_name)`
  guarantee is exactly why there can't be one.

**Fix.** Reuse this codebase's own existing deterministic-id pattern
(`pipeline.py:124`, `resolve_entities_from_nsf`:
`uuid.uuid5(uuid.NAMESPACE_DNS, key)`) rather than inventing a new one:
```python
# reconcile.py:build_finding
finding_id = str(uuid.uuid5(
    uuid.NAMESPACE_DNS, f"finding|{case_id}|{item.source}|{item.institution_name}"
))
```
```python
# discover.py: both tie-construction sites
tie_id = str(uuid.uuid5(
    uuid.NAMESPACE_DNS,
    f"tie|{case_id}|{tie_kind.value}|{anchor_affiliation_id}|{concern_entity_name}",
))
```
A literal `"finding|"`/`"tie|"` type prefix rules out any cross-type
collision between the two id spaces sharing one namespace UUID.

**Uniqueness enforcement — `CREATE UNIQUE INDEX`, not a table constraint
on JSON fields.** Verified directly against the installed DuckDB (1.5.5):
`ALTER TABLE ... ADD CONSTRAINT ... UNIQUE` is **not supported**
(`Not implemented Error`), but `CREATE UNIQUE INDEX IF NOT EXISTS ...`
is, is idempotent to re-run, and correctly rejects a duplicate with a
`ConstraintException`. Since the id *is* now the natural key's
fingerprint, a unique index on the id column alone gives M18 for free —
no need to index into the JSON columns at all:
```sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_findings_finding_id ON findings(finding_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_concern_ties_tie_id ON concern_ties(tie_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_explanations_obs_hash ON explanations(observation_id, evidence_hash);
```
Add these to `entity_screening/common/storage.py`'s existing migration
block (the same place M11's three `ALTER`s and three `UPDATE`s already run on
every `connect()`) — verified this exact statement shape and multi-column
form both work and are idempotent via a direct DuckDB test in this
session. **Deploy-time check, can't be verified from here:** confirm the
live persistent volume has no accidental duplicate rows before this
migration runs (astronomically unlikely under the old random-uuid4
scheme, but the index creation will fail loudly rather than silently if
there is one — that's the correct failure mode, not a problem to design
around).

**Explanation-cache orphan cleanup.** `replace_findings`/`replace_ties`
must delete `explanations` rows for ids they *remove* (present in the old
set, absent from the new one) — not every stale-hash row for a *kept* id,
which `evidence_hash_for`'s own `(observation_id, evidence_hash)` lookup
already handles correctly (a kept id with changed content just misses on
hash and regenerates; no accumulation problem at this project's scale).
Implementation: load the old id set before deleting, diff against the
new set, `DELETE FROM explanations WHERE observation_id IN (removed_ids)`
in the same call.

**`_DEMO_CASE_TABLES` must include `explanations`.**
`entity_screening/case/demo.py:129-137` currently omits it — confirmed by
direct read. Add it so a demo rebuild also wipes stale explanation rows
for the case, not just findings/ties/actions.

**Correct the "ids don't persist across runs" docstrings — this
reasoning becomes false, and the actual safety property moves to a
different mechanism, not away.** Three places assert the old invariant
as the reason staleness can't happen:
`entity_screening/common/storage.py:364-368` (the `explanations` table's
own DDL comment), `entity_screening/explanation/service.py`'s
`evidence_hash_for` docstring (~lines 43-48), and
`entity_screening/explanation/schema.py`'s `MatchExplanation` docstring
(~lines 64-73). After this fix, ids *do* persist across runs — but
`evidence_hash_for` already folds in the observation's full recitation
(every field value) plus `case_context` (Phase 2) plus
`MODEL`/`PROMPT_VERSION`, so a genuine content change under a now-stable
id still produces a different hash and correctly misses the cache. Rewrite
all three comments to state that the safety property is carried entirely
by `evidence_hash_for`'s content hash now, not by id churn — id stability
is what makes the cache *more* useful (a no-op reconcile correctly reuses
a cached explanation instead of always regenerating), not what makes it
unsafe.

**`DEMO_FIXTURE_VERSION` bump, 6→7 (Phase 2 did 5→6 for the same class of
reason).** The demo's finding/tie ids change value (not just staying
stable — they change *shape*, uuid4 → uuid5) the first time this code
reconciles the demo case. Bump `DEMO_FIXTURE_VERSION` in
`entity_screening/case/demo.py` (6 → 7) so `_ensure_demo_case_exists`
rebuilds and regenerates the demo's pre-generated explanations under the
new ids on next deploy — same no-live-key mechanism as every prior bump
(`_demo_no_synthesis_call`).

**Tests.**
1. Unit test: reconciling the same case fixture twice produces the
   *identical* `finding_id`/`tie_id` set both times (not just the same
   count, which `test_reconciliation.py:341-360`
   `test_reconcile_case_is_current_state_not_append` already checks
   without checking id equality — extend it or add a sibling test that
   does).
2. Unit test reproducing the real collision above directly against
   `build_finding`/`tie_from_ownership`/`ties_from_own_affiliations`:
   confirm the two "NIO INC." ties from
   `test_both_at_once_produces_one_finding_and_one_tie_joined_by_id`'s
   fixture get *different* `tie_id`s (proving the 4-component key, not
   just documenting it).
3. **The money test** (this phase's actual exit criterion): reconcile the
   demo case, record a `WorksheetAction` on one finding, reconcile the
   demo case *again* (same fixtures, nothing changed) — the action is
   still attached (`effective_actions` still shows it against the same
   id), no orphan `explanations` rows exist for ids no longer present,
   and a `GET .../explanation` for that finding still serves the cached
   row (proves the explanation cache reuse is real, not just
   theoretically possible).
4. `CREATE UNIQUE INDEX` migration test: run it twice (idempotent), and
   confirm inserting a genuine duplicate id raises (a narrow, direct
   DuckDB-level test, not through the full pipeline).

---

## 2. S5 (state guard) — reconcile refused outside INTAKE/DECLARATION_ASSEMBLY/DISCOVERY

**Current state.** `entity_screening/api/case_routes.py`'s `reconcile`
route (lines 412-439) only 404s on an unknown case — no state check at
all. `pages/0_HB127_Case_Worksheet.py`'s "Re-run reconciliation" button
(lines 191-202) is gated only on `_actions_enabled` (the action-secret
gate), rendered unconditionally regardless of `worksheet["state"]`. An
analyst mid-worksheet can click it and wipe their own progress today —
confirmed directly, not inferred.

**Re-open mechanism — one path, not two.** `service.reopen_case`
(`case/service.py:362-366`) is a two-line wrapper —
`return transition(conn, case_id, CaseState.DISCOVERY)` — confirmed
**unreachable from any HTTP route or the UI** (grepped `entity_screening/api/`
and `pages/`: zero hits outside its own definition). It's called only
directly, at the service layer, by two unit tests
(`tests/test_case_lifecycle.py:277`, `tests/test_idempotency.py:251`).
The generic `POST /cases/{id}/transition {"target_state": "discovery"}`
route already reaches the exact same `transition()` call with the exact
same effect, since `CLOSED: {CaseState.DISCOVERY}` is already in
`_TRANSITIONS`. Per M22's own recommendation: **delete `reopen_case`**,
update the two tests to call `service.transition(conn, case_id,
CaseState.DISCOVERY)` directly instead, and the UI's re-open control
(M6, below) uses the generic transition route.

**A structural note on what this guard implies for a WORKSHEET-state
case wanting fresh data.** `_TRANSITIONS` has no edge from WORKSHEET or
OUTCOME back to DISCOVERY except through the full
`CLOSED → DISCOVERY` re-open. So once a case reaches WORKSHEET, the
*only* way to get fresh reconciliation is to complete the lifecycle to
CLOSED (which, after M5 below, requires a recorded outcome, which
requires a recorded adjudication) and then re-open. This is a real
operational consequence of doing exactly what the strategy doc asks —
not something to silently smooth over by inventing a new backward edge
(that would be a second, unreviewed design fork on top of this phase's
already-substantial one). Flagging it here as a deliberate scope
boundary, not a gap: the strategy doc's own framing ("refused... unless
re-opened") already accepts this shape.

**Fix.** In the `reconcile` route, after `_load_case_or_404`, reject with
409 if `case.state not in
{CaseState.INTAKE, CaseState.DECLARATION_ASSEMBLY, CaseState.DISCOVERY}`.
In the worksheet page, hide (not just disable) the "Re-run reconciliation"
button once `worksheet["state"]` is no longer `"discovery"`-reachable —
concretely, only render it when `worksheet["state"] in
{"intake", "declaration_assembly", "discovery"}` (check the worksheet
payload actually exposes a state this early — if a case is fetched via
`GET /worksheet` before it's ever reached WORKSHEET, confirm what
`get_worksheet` returns for a pre-DISCOVERY case; if the route only
works post-WORKSHEET today, the button's visibility condition simplifies
to "never show it once the case worksheet exists," which is very likely
the real intended behavior anyway, since the worksheet page is only
navigated to for a case already past intake).

**Tests.** `POST /cases/demo/reconcile` a second time while state is
WORKSHEET → 409 (fails on the unmodified tree first — today it succeeds
and wipes the worksheet). Re-open (`transition` to DISCOVERY), reconcile
again → succeeds.

---

## 3. M10 — deterministic row order

**Current state.** `entity_screening/case/store.py:450` (`load_findings`)
and `:527` (`load_ties`) both `ORDER BY finding_id`/`ORDER BY tie_id` —
today that's ordering by a fresh random uuid4, so row order is
unreproducible across reconciles (confirmed, line numbers unchanged from
the review).

**Fix.** Order by the natural key's own components instead — reproducible
*and*, once S5 lands, stable across runs for the same content:
```sql
-- findings
ORDER BY discovered->>'source', discovered->>'institution_name'
-- concern_ties
ORDER BY tie_kind, concern_entity_name
```
DuckDB's `->>` JSON-text-extraction operator on the `discovered` JSON
column — **verified directly against the installed DuckDB (1.5.5) in
this session**: `ORDER BY discovered->>'source', discovered->>'institution_name'`
against a real two-row JSON table returns the correct alphabetical order.
This is also what makes Phase 4's before/after evidence diffs meaningful
(the strategy doc's own stated reason for placing M10 here rather than
standalone).

**Tests.** Reconcile the demo case twice; assert `load_findings`/
`load_ties` return the same row order both times (this test is currently
impossible to write meaningfully — row order is random today — so it's
new coverage, not a rewrite).

---

## 4. M19 — `POST /cases` case_id collision is 409, not silent overwrite

**Current state.** `entity_screening/api/case_routes.py`'s `create_case`
(lines 332-409) has no existence check; `store.save_subject`/
`save_declaration`/`save_case` are each `DELETE ... WHERE id = ?` then
`INSERT` — confirmed, a `POST /cases` with an existing `case_id` silently
deletes and replaces the `Case`/`Subject`/`Declaration` rows, leaving
`findings`/`worksheet_actions`/etc. orphaned against the now-replaced
case (a second-order effect on top of the primary bug).

**Fix.** In `create_case`, before saving: if `request.case_id` is
`demo.DEMO_CASE_ID`/`demo.DEMO_COI_CASE_ID` (reserved — reuse the existing
constants `case_routes.py` already imports and checks against elsewhere,
not new string literals) or `store.load_case(conn, request.case_id)`
returns non-`None`, raise `HTTPException(409, ...)`.

**Tests.** `POST /cases` with `case_id="demo"` → 409. `POST /cases` twice
with the same fresh `case_id` → second call 409, first case's data
unchanged.

---

## 5. M5 — couple state transitions to the records they imply

**Current state.** `case/service.py`'s `transition()` (lines 245-271)
only extra-checks the WORKSHEET→ADJUDICATION edge (`can_close`).
`OUTCOME → CLOSED` and `ADJUDICATION → OUTCOME` have no coupling to
`record_outcome`/`record_adjudication` having ever been called —
confirmed directly. `record_action`/`record_tie_action` (lines 126-166,
191-221) have **no state check at all** — they accept an action in any
state, including CLOSED, confirmed directly (only the reason-code vocab
and finding/tie-belongs-to-case are checked).

**Fix.**
1. `transition()`: when `target is CaseState.OUTCOME` (from ADJUDICATION),
   require at least one `Adjudication` row exists for the case —
   `store.next_adjudication_seq(conn, case_id) > 0` (it's a next-seq
   counter, not a count: it returns `0` when none exist, not `1`, so `> 0`
   is the correct check — not `> 1`). When `target is CaseState.CLOSED`
   (from OUTCOME), require a recorded outcome — reuse
   `service.latest_outcome(conn, case_id)`, which already exists and
   already returns `None` when nothing's recorded, rather than writing a
   new store-layer check. Both raise `CaseStateError` → 409, same pattern
   as the existing `can_close` check.
2. `record_action`/`record_tie_action`: reject (raise `CaseStateError`)
   when `case.state == CaseState.CLOSED`. Every other state stays
   allowed — an action recorded mid-ADJUDICATION or mid-OUTCOME is a
   legitimate correction, only a closed case's record should be
   immutable going forward (append-only history stays append-only, but
   nothing new appends once closed).

**Tests.** `transition` ADJUDICATION→OUTCOME with zero adjudications
recorded → 409 (fails on the unmodified tree first). Same for
OUTCOME→CLOSED with no outcome recorded. `record_action` on a CLOSED
case → 409 (fails first).

---

## 6. M6 — UI controls for the full lifecycle

**Current state.** `pages/0_HB127_Case_Worksheet.py` has controls only
for WORKSHEET→ADJUDICATION (lines 525-534) and recording an adjudication
(lines 536-547) — confirmed, no `→ OUTCOME`, `record_outcome`,
`→ CLOSED`, or re-open control anywhere in the file. Every existing
mutating button follows `disabled=not _actions_enabled` (optionally
ANDed with a domain predicate) — the convention any new control must
match.

`_VALID_OUTCOMES` (`service.py:57-62`) is private and not exposed via any
route today; the UI needs it for a dropdown.

**Fix.**
1. Promote `_VALID_OUTCOMES` → `VALID_OUTCOMES` (public), same "a second
   layer needs it" rationale Phase 2 used for `evidence_hash_for`. Add it
   to the existing `GET /cases/reason-codes` response
   (`case_routes.py:288-298`) as `"outcomes": service.VALID_OUTCOMES` —
   reuses the existing small-vocab GET route rather than adding a new
   endpoint.
2. In the worksheet page, when `worksheet["state"] == "adjudication"`
   (same block as the existing adjudication form): after the "Record
   adjudication" button, add a `"→ Outcome"` button,
   `disabled=not _actions_enabled`, posting
   `{"target_state": "outcome"}` to the transition route — let the API's
   409 (from M5's new coupling) surface via the existing
   `except requests.RequestException` pattern if no adjudication is
   recorded yet, same as every other button here.
3. When `worksheet["state"] == "outcome"`: a form — `st.selectbox`
   over the fetched `outcomes` vocab, a note `st.text_area`, "Record
   outcome" button (`disabled=not _actions_enabled`) posting to
   `/cases/{case_id}/outcome`; then a `"→ Closed"` button posting
   `{"target_state": "closed"}`.
4. When `worksheet["state"] == "closed"`: a `"Re-open case"` button
   posting `{"target_state": "discovery"}` to the transition route (the
   one surviving re-open mechanism, per §2 above).

**Tests.** UI smoke test (same `AppTest` + `TestClient` pattern as
Phase 1's `tests/test_case_worksheet_ui.py`) driving a case through
WORKSHEET → ADJUDICATION → record adjudication → OUTCOME → record
outcome → CLOSED → re-open, entirely through rendered widgets, asserting
no exception at each step — this is the exit criterion the strategy doc
names explicitly ("full lifecycle INTAKE → CLOSED drivable from the UI
with the secret").

---

## 7. M7 — `dismissal-basis-summary` scoped and dangling-id-safe

**Current state.** `case_routes.py:301-329`. No `case_id` filter (a
global aggregate across every case, open or closed, demo or not), no
join back to `findings`/`concern_ties` (an action whose id no longer
resolves is still counted) — both confirmed directly against the live
SQL.

**Fix.** Join against `findings`/`concern_ties` (proves the id still
resolves) and against `cases` (scope to `state = 'closed'`, exclude the
demo cases via a parameterized `NOT IN (?, ?)` bound to
`demo.DEMO_CASE_ID`/`demo.DEMO_COI_CASE_ID` — not hardcoded string
literals, consistent with M19 above):
```sql
SELECT wa.reason_code, count(*)
FROM worksheet_actions wa
JOIN findings f ON f.finding_id = wa.finding_id AND f.case_id = wa.case_id
JOIN cases c ON c.case_id = wa.case_id
WHERE wa.action = 'dismiss' AND c.state = 'closed' AND c.case_id NOT IN (?, ?)
GROUP BY wa.reason_code ORDER BY count(*) DESC
```
(mirrored for `tie_actions`/`concern_ties`). This also means, post-S5,
the join is never spuriously empty for a still-open case's dismissals —
they're correctly excluded on purpose (this is "the office's accumulated
case law," not a live scratch pad), and a genuinely dangling id (an old
action against a since-removed finding) is correctly excluded too, not
just tolerated.

**Tests.** Dismiss a finding in an open (non-closed) case → doesn't
appear in the summary. Close that case → now appears. A demo-case
dismissal → never appears regardless of state.

---

## Cross-cutting

**Failing test first for every item**, same discipline as Phases 1-2:
S5's money test, the state-guard 409 tests, M5's coupling tests, and
M7's scoping tests all run red against the unmodified tree first.

**Contract test — no dangling ids in export.** Extend
`tests/test_output_contract.py`'s existing contract test
(`test_investigative_file_export_contract`, lines 137-275) — which
today only reconciles once, so it can't currently exercise a dangling-id
scenario — with a second reconcile after recording an action, then
assert every `worksheet.action_history`/`tie_actions.action_history`
entry's `finding_id`/`tie_id` appears in `payload["findings"]`/
`payload["concern_ties"]`. This is the "no dangling ids" exit criterion
the strategy doc names explicitly.

**Full suite green, `cli validate` passes.**

**Deploy is part of the phase.** Runbook §7, then confirm both demo
cases still load — this deploy's `DEMO_FIXTURE_VERSION` bump means the
self-heal does real work (a full rebuild + explanation regeneration)
rather than a no-op, so the post-restart check matters more than usual
here; watch for the rebuild actually completing rather than timing out.

**Docs.** Copy this plan into
`docs/plans/2026-09-16-phase-3-run-identity-and-case-lifecycle.md`, index
it in `docs/plans/README.md`, dated implementation note appended
afterward — same pattern as Phases 1-2.

## Verification summary (binding acceptance criteria)

- [ ] Reconciling the same case twice produces identical finding/tie id
      sets (new coverage — impossible to assert meaningfully today).
- [ ] The real "two ties, same concern_entity_name, different tie_kind"
      collision case gets two distinct tie ids.
- [ ] **Money test:** reconcile → record an action → reconcile again →
      action still attached, no orphan `explanations` rows, `GET
      .../explanation` still serves the cached row.
- [ ] `CREATE UNIQUE INDEX` rejects a genuine duplicate id; migration is
      idempotent to re-run.
- [ ] `POST .../reconcile` in WORKSHEET/ADJUDICATION/OUTCOME/CLOSED → 409
      (fails on the unmodified tree first); succeeds again after
      re-open.
- [ ] `load_findings`/`load_ties` return the same row order across two
      reconciles of the same case.
- [ ] `POST /cases` with `case_id="demo"` or any existing id → 409.
- [ ] `transition` to OUTCOME with no adjudication recorded → 409;
      to CLOSED with no outcome recorded → 409 (both fail on the
      unmodified tree first).
- [ ] `record_action`/`record_tie_action` on a CLOSED case → 409 (fails
      first).
- [ ] Full lifecycle INTAKE → CLOSED → re-opened, drivable from the UI
      with the secret, no exception at any step.
- [ ] `dismissal-basis-summary` excludes open cases, demo cases, and any
      dangling-id action.
- [ ] Export contract test proves no dangling id in `action_history`/
      `effective_actions` after a second reconcile.
- [ ] `reopen_case` deleted; its two direct test callers updated to call
      `service.transition(..., CaseState.DISCOVERY)`.
- [ ] `DEMO_FIXTURE_VERSION` bumped; the three "ids don't persist across
      runs" docstrings corrected to state the real, current safety
      mechanism (`evidence_hash_for`'s content hash).
- [ ] Full suite green; `cli validate` passes.
- [ ] Deployed; both demo cases confirmed loading post-rebuild.

---

## Implementation note (2026-09-16)

All seven sections landed, in plan order, full suite 396 passed / 1 skipped
(the pre-existing environment-dependent git test), `cli validate` passes.
Test-first discipline followed for every item with a "before" state to
fail against: S5's state guard, M19, M5's three coupling tests, and M7's
two scoping tests were all run red against the unmodified tree first,
confirmed to fail for the stated reason, then fixed. (S5 core's own new
tests were written alongside the fix rather than strictly before it, since
the change itself — uuid4 → uuid5 — has no ambiguity a red run would
clarify; M10 similarly, since "make row order deterministic" has no
meaningful red state beyond "test can't be written at all," noted in the
test's own docstring instead.)

**Demo-evidence diff, done empirically, not asserted.** Captured findings/
ties for both demo cases against the tree at `76e9ebc` (pre-Phase-3, via
`git stash`) and again post-Phase-3, normalized by stripping `run_id`/
`finding_id`/`tie_id`/`related_finding_id`/timestamps and sorting rows.
Content is byte-identical for both demo cases. Also independently
re-verified with `anchor_affiliation_id` *not* stripped (it's a
fixture-defined declared-affiliation id, not derived by S5's uuid5 change,
so it should never have moved) — still identical, confirming the
normalization wasn't masking anything.

**One real bug the new `CREATE UNIQUE INDEX` caught immediately, not
anticipated in the plan.** `tests/test_case_store.py::
test_findings_are_current_state_per_case` called
`replace_findings(conn, "case-1", [_finding(), _finding()])` — the same
fixture object twice, both carrying the literal hardcoded `finding_id=
"find-1"`. Before this phase, the `findings` table had no uniqueness
constraint at all, so two rows sharing an id silently coexisted; the new
unique index correctly rejected it. This was a real, if narrow,
pre-existing gap the test had been relying on rather than testing — fixed
by giving the test two genuinely distinct findings (different
`finding_id`, different institution) instead of the same one twice, which
is also the only shape a real reconcile could ever produce (`discovered_
finding_map`'s own one-per-institution guarantee).

**Two additional stale-docstring corrections beyond the plan's named
three.** `entity_screening/explanation/service.py`'s `evidence_hash_for`
docstring also referenced M10's "row order isn't guaranteed stable" as a
reason for sorting `case_context` before hashing; since M10 now makes
that order deterministic too, the docstring was updated to say the sort
is kept as a cheap, harmless safety net rather than a load-bearing fix for
an active bug. `entity_screening/explanation/schema.py`'s
`MatchExplanation` docstring rewrite briefly duplicated its own trailing
paragraph on the first pass (caught and fixed before running tests).

Not done as part of this phase, by design: the actual deploy. This
phase's `DEMO_FIXTURE_VERSION` bump (6→7) means the next deploy's
self-heal does real work — a full rebuild of both demo cases and their
pre-generated explanations under the new deterministic ids — so the
post-restart check (confirm both demo cases still load) matters more than
in a typical deploy.
