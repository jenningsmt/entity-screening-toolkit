# Step 6 — COI / NSPM-33 annual disclosure reuse

*Plan as approved via Claude Code plan mode, 2026-09-15. Historical record — read
`git log` for what actually shipped.*

---

## Context

`docs/use-case-01-hb127-researcher-screening.md` §12 names step 6 ("COI and NSPM-33
disclosure reuse") as the next item in the build sequence, and asserts it is "nearly
free": an annual conflict-of-interest disclosure is structurally identical to a
§51B.152 declaration — a self-reported affiliation set reconciled against the record —
so the same reconciliation engine should serve it with no new matching logic. Steps
1–5 are built and the tree is clean; this plan is the implementation-planning pass for
step 6, following this project's established practice (steps 4 and 5 each did a
real-data verification pass before design — the foreign-adversary-list ingester
against the DNI ATAs, RPS against the real `us_trade_csl` file and the TAMU manual).
That same discipline applies here: before touching `Declaration`, verify what NSPM-33
disclosure content and a real annual COI disclosure actually require, rather than
treating "nearly free" as a settled premise.

## Real-data research done before designing this

**"COI and NSPM-33" is two different problems wearing one name — the same shape of
finding use-case-02 §0 made once already for "export control".** Confirmed by reading
OSTP's NSPM-33 guidance and several real institutional policies directly, not assumed:

1. **NSPM-33's own federal disclosure forms** (Biographical Sketch + Current & Pending
   (Other) Support) are submitted **at proposal time** and updated on **event
   triggers** — a new proposal, a post-award "reportable change," a 30-day window
   after an undisclosed-support discovery, and (per NSF's Research.gov process live
   since May 2024/Oct 2025) an **annual PI/co-PI certification** of foreign-talent-
   program non-participation. Their content is per-project, not per-affiliation:
   funding source, dollar amount, person-months, dates, and an explicit
   overlap-with-pending-proposals check. None of that maps onto `DeclaredAffiliation`
   (institution + role + dates + activity kind) without inventing a new,
   differently-shaped type — this is real new modeling, not reuse.
2. **A real annual institutional COI disclosure** is a different, and
   differently-triggered, artifact: submitted at hire and **annually thereafter**,
   updated within a fixed window ("at least annually and within thirty (30) days of a
   change" — confirmed by fetching **Texas A&M System Regulation 15.01.03, Financial
   Conflicts of Interest in Sponsored Research**, directly; the language is in the
   Regulation itself, not in Rule 15.01.03.M1, which implements it but doesn't repeat
   the cadence) via a **Disclosure Profile** (TAMU uses the Huron Research Suite for
   this). **Note this is specifically TAMU's financial-conflicts-of-interest regime,
   not its separate Conflict-of-Commitment rule (15.99.99.M0.02)**, which governs
   outside-time-commitment limits rather than financial/affiliation disclosure and is
   not modeled here — the same care use-case-02 §6 took to keep "three different lists
   of countries" from being blurred into one. This plan models the financial-COI
   disclosure pattern specifically, because it's the one with confirmed real
   field-shape and cadence grounding. Its content — confirmed convergent across TAMU,
   Rice University Policy 218, Ohio State's outside-activities policy, and three other
   public institutional policies — is exactly affiliation-shaped: outside employment,
   board memberships, consulting, foreign government/institutional affiliations, each
   with an organization name, a role, and dates. **This is the artifact step 6's
   "nearly free" claim is actually about.**

**Consequence for scope:** step 6 targets the annual institutional COI/Outside-Interest
disclosure only. NSPM-33's federal per-proposal Biographical Sketch / Current & Pending
Support forms are explicitly out of scope for this reuse — a distinct, event-triggered,
differently-shaped compliance artifact that would need its own type if ever built,
exactly the caution use-case-02 §0/§6 already established once for conflating two
regimes under one colloquial name. `docs/use-case-01-hb127-researcher-screening.md`'s
step 6 description will be corrected to say "annual COI/Outside-Interest disclosure
reuse," not "COI and NSPM-33 disclosure reuse," with this finding recorded.

## What's already reusable vs. genuinely new

Verified directly against the code (not assumed from the doc):

**Reusable unmodified:**
- `Declaration` / `DeclaredAffiliation` / `DeclarationSource` / `ScopeKind`
  (`entity_screening/common/schema.py:277-335`) — no field names a document type, a
  statute, or "hiring"; `DeclarationSource.kind` is already a free string and
  `activity_kind` already anticipates non-employment kinds. An Outside-Interest
  disclosure fits with a new `kind`/`activity_kind` string value, no schema change.
- `reconciliation/reconcile.py` and `reconciliation/match.py` — consume only
  `declaration.affiliations`/`declaration.sources`; nothing HB-127-specific.
- `Finding`, `ConcernTie`, the worksheet/adjudication/export pipeline
  (`case/service.py`, `case/export.py`), and the fact/judgment-boundary field
  allowlist (`_OBSERVATION_GRAPH_ALLOWED_FIELDS`) — no changes needed.
- `DISMISS_REASON_CODES` and `TIE_DISMISS_REASON_CODES`/`TIE_ESCALATION_REASON_CODES`
  (`case/vocab.py`) — already statute-agnostic factual bases (variant name, record
  error, clarified by subject, previously reviewed — `known_and_previously_reviewed`
  already says "prior case **or disclosure cycle**", `vocab.py:33-36`, anticipating
  exactly this). Reused as-is. (One tie-dismiss code,
  `immaterial_to_requested_access_scope`, is phrased around a hiring access decision a
  COI case doesn't have; documented as a known imprecision — `other` + note covers it
  — not worth a new vocabulary for one code.)

**Genuinely new — small, real, not "free," but not new matching logic either:**
1. **Recurrence gap in persistence.** `pipeline.reconcile_case`
   (`entity_screening/pipeline.py:695`) and `case/export.py:100` load "the"
   declaration for a case via `case_store.load_declaration_for_subject(conn,
   case.subject_id)` — a `.fetchone()` with no ordering and no cycle/period
   discriminator. Nothing stops two `Declaration` rows existing for one `subject_id`
   (an annual disclosure implies exactly that, cycle after cycle), but this lookup
   would silently pick an arbitrary one. Confirmed no test exercises two declarations
   for one subject (`tests/test_case_store.py:186-209` round-trips exactly one).
2. **`Case.coverage_basis` (and `Subject.coverage_basis`) is HB-127-specific by
   definition**, not generic metadata: `CoverageBasis`'s docstring is "which limb of
   HB 127 Sec. 51B.151(a) brings a subject under screening"
   (`common/schema.py:224-234`), with exactly two members, both statute citations. A
   COI case has no §51B.151(a) limb at all. Confirmed (via grep across
   `entity_screening/`) that `coverage_basis`/`access_scope` are never branched on by
   any matching/reconciliation logic — purely descriptive, stored and displayed
   (`case/export.py:119-130`, `api/case_routes.py:198`, one Streamlit metric at
   `pages/0_HB127_Case_Worksheet.py:156`) — so this is safe to generalize without
   behavioral risk, but it is a real, deliberate type change, not a no-op.
3. **Escalation vocabulary.** `ESCALATION_REASON_CODES`'s
   `possible_nondisclosure_for_certification` (`case/vocab.py:50-53`) routes to a
   §51B.153 department-head certification — a mechanism that does not exist for a COI
   case. Reusing it unmodified would offer analysts a dead-end code, exactly the kind
   of wrong-shape reuse this project's own retrospective already flagged once
   (`docs/plans/2026-09-06-concern-ties-as-a-distinct-observation.md`). Needs its own
   small vocabulary, mirroring how RPS got `RPS_ESCALATION_REASON_CODES` instead of
   reusing `ESCALATION_REASON_CODES` unmodified (`case/vocab.py:137-149`).
4. **`record_action` doesn't currently load the `Case` at all** — it validates against
   a hardcoded vocabulary (`case/service.py:118-146`). Selecting the right escalation
   vocabulary per case needs a `Case`-kind discriminator and one extra `load_case`
   call.

## Design

**1. `CaseKind` discriminator** (`common/schema.py`, new enum):
```python
class CaseKind(Enum):
    HB127_RESEARCHER_SCREENING = "hb127_researcher_screening"
    COI_ANNUAL_DISCLOSURE = "coi_annual_disclosure"
```
Add `Case.case_kind: CaseKind = CaseKind.HB127_RESEARCHER_SCREENING` — defaulted, so
every existing HB-127 call site (`cli.py`, `case/demo.py`, `api/case_routes.py`)
needs no change. This is the field the rest of the design keys off, rather than
inferring "COI-ness" from `coverage_basis` being absent.

**2. Fix the recurrence gap.** Add `Case.declaration_id: str` (no default — every
creation site sets it explicitly). `api/case_routes.py:create_case` already computes
`f"{request.case_id}-declaration"` for the `Declaration` object itself
(`case_routes.py:283`); add the same value to `Case(...)`. Same one-line addition in
`case/demo.py` and `cli.py`'s case-creation path. Then change the two read sites:
- `pipeline.py:695`: `case_store.load_declaration(conn, case.declaration_id)` instead
  of `load_declaration_for_subject(conn, case.subject_id)` (`load_declaration` already
  exists, `case/store.py:177-185` — this is a call-site swap, not a new function).
- `case/export.py:100`: same swap.
`load_declaration_for_subject` stays (still useful for "what's this subject's current
declaration" lookups outside a case context) but reconciliation/export no longer
depend on it being unambiguous.

**3. Generalize `coverage_basis`.** `Subject.coverage_basis: CoverageBasis | None`
and `Case.coverage_basis: CoverageBasis | None`, default `None`. Update the four
`.value` read sites to guard `None` (`case/export.py:119-130`, `api/case_routes.py:198`,
`case/store.py` insert/select already handles `NULL` via the existing `VARCHAR`
column — no DDL change needed since DuckDB `VARCHAR` already accepts `NULL`). Update
the one Streamlit display (`pages/0_HB127_Case_Worksheet.py:156`) to show
`"N/A — annual disclosure, not an HB-127 case"` when `None`.

**4. New COI escalation vocabulary** (`case/vocab.py`):
```python
COI_ESCALATION_REASON_CODES: dict[str, str] = {
    "needs_supervisor_review": "Beyond the analyst's authority to dispose of alone.",
    "needs_subject_clarification": "Cannot be dispositioned without input from the subject.",
    "needs_coi_committee_referral": (
        "Appears to meet the institution's conflict-of-interest/commitment "
        "threshold; routed to the COI committee for a management-plan decision."
    ),
    "other": "See the note.",
}
```
plus `is_valid_coi_reason_code`, mirroring `is_valid_rps_reason_code`
(`case/vocab.py:164-167`). `DISMISS_REASON_CODES` stays shared (§ above).

**5. Schema/DDL.** `common/storage.py`'s `cases` table DDL declares exactly the 9
columns `Case` has today, as `CREATE TABLE IF NOT EXISTS` — which will **not**
backfill `case_kind`/`declaration_id` onto an already-existing local database (the
committed dev-only `data/processed/entity_screening.duckdb`, and anyone's local
checkout that's already run the demo). Add both columns to the DDL, update
`case/store.py:save_case`/`load_case`'s positional `INSERT`/`SELECT` column lists in
lockstep (both are hand-written positional tuples today, `store.py:204-255`), and
regenerate the demo database as part of this change (it's dev-only, reproducible
data — the practical fix, not a migration script).

**6. Wire the discriminator into validation.** `case/service.py:record_action`
currently doesn't load the `Case`. Add `case = store.load_case(conn, case_id)` (raise
if `None`, matching `worksheet()`'s existing pattern) and select
`is_valid_coi_reason_code` vs. `is_valid_reason_code` by `case.case_kind` for
escalation actions only (dismiss vocab is shared, per above). `record_tie_action`
stays as-is — ties keep the shared `TIE_*` vocab regardless of case kind (documented
known imprecision, § above).

**7. API surface.** `api/case_routes.py`'s `CreateCaseRequest`: add optional
`case_kind: str = "hb127_researcher_screening"`, mapped to `CaseKind(...)`.
`declaration_id` is **not** a new request field — per step 2, it stays
server-computed as `f"{request.case_id}-declaration"` at all three creation sites,
the same value already used for the `Declaration` object itself. Accepting it from
the caller would reopen exactly the ambiguity this plan exists to close (a caller
could point a case at an unrelated subject's declaration); the fix is that the value
is never chosen by anything other than the case-creation code path, deterministically,
same as today. No new route — this is the same endpoint HB-127 cases already use,
consistent with "reuse the engine, don't fork a new service module" (the opposite
choice from step 5's RPS, which deliberately did fork because the fit was genuinely
wrong there — use-case-02 §4).

**8. Doc updates.**
- New `docs/use-case-03-coi-annual-disclosure-reuse.md`, structured like
  use-case-02: the two-regimes-one-name finding (§ above), the real TAMU/Rice/OSU
  grounding, the fact/judgment boundary restated (a COI *finding* is never itself
  "a conflict" — that's the COI committee's call, exactly the same discipline as
  `ConcernTie` never asserting a tie "would prevent" access).
- `docs/use-case-01-hb127-researcher-screening.md` §12: correct step 6's one-line
  description to "annual COI/Outside-Interest disclosure reuse," record that NSPM-33's
  federal disclosure forms are a separate, out-of-scope artifact, and note the two
  small generalizations actually required (recurrence, `coverage_basis`) rather than
  leaving "nearly free" unqualified.
- `docs/plans/README.md`: add this plan's row once implemented.
- Plan file itself gets copied to `docs/plans/2026-09-15-step-6-coi-annual-disclosure-
  reuse.md` as part of implementation, per this project's standing practice.

## Demo data (synthetic subject, real reference data — same discipline as §10)

Reuse the **existing** HB-127 demo subject rather than inventing a new one: add a
second `Declaration` + `Case` (`case_kind=COI_ANNUAL_DISCLOSURE`, `coverage_basis=None`,
`trigger="Annual Outside-Interest disclosure, TAMU System Regulation 15.01.03,
FY2027"`) for the *same* `subject_id`, with a declared-affiliation set that
deliberately omits one item the bundled OpenAlex/GLEIF fixtures would still surface —
producing a genuine new `Finding` under the second cycle. This is the direct
end-to-end proof that the recurrence fix (`declaration_id` on `Case`) actually
disambiguates two cycles for one subject, not just a theoretical claim. No new
fixture files needed — same bundled OpenAlex/GLEIF/DoD-1260H/OpenSanctions data,
a different declared set.

## Tests

- `tests/test_case_store.py`: two `Declaration`s + two `Case`s for one `subject_id`;
  assert `load_declaration(conn, case1.declaration_id) != load_declaration(conn,
  case2.declaration_id)` — the regression test for the exact gap found above.
- `tests/test_pipeline.py`: reconcile both cases for the same subject; assert findings
  are correctly scoped per `case_id` and don't collide.
- `tests/test_case_lifecycle.py`: `record_action` on a `COI_ANNUAL_DISCLOSURE` case
  rejects `possible_nondisclosure_for_certification` and accepts
  `needs_coi_committee_referral`; the reverse for an HB-127 case.
- `tests/test_demo_case.py`: extend for the second demo cycle, end-to-end
  (intake → worksheet → export), asserting the export's `coverage_basis` renders
  `None` cleanly.
- `cli.py validate` / the `_OBSERVATION_GRAPH_ALLOWED_FIELDS` guard: no change
  expected (Finding/ConcernTie shapes are untouched) — run as a non-regression check.

## Verification

1. `pytest` (full suite) — confirms the new tests pass and nothing existing regresses
   (in particular the HB-127 demo case and its existing tests, since `CaseKind`
   defaults preserve prior behavior).
2. Run the demo end-to-end via the CLI/API for both cases on the same subject; inspect
   the exported investigative files for both `case_id`s and confirm each carries its
   own declaration/findings, not a merged or duplicated set.
3. Load both cases in the Streamlit worksheet (`pages/0_HB127_Case_Worksheet.py`) and
   confirm the COI case's "Coverage basis" metric shows the `None`-safe label rather
   than erroring.
