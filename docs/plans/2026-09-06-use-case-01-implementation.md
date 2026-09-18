# Use Case 01 — HB 127 Researcher Screening: Implementation Plan

**Status:** Plan, not yet built. Approved 2026-09-06 (with five conditions folded in — see
the pushback section and binding acceptance criteria).
**Scope:** the vertical slice from `docs/use-case-01-hb127-researcher-screening.md` §12 —
one subject, one declaration, a worked reconciliation worksheet, an exportable investigative
file — plus the minimum around it to demo a real finding.

This is a historical record of the plan as approved, per `docs/plans/README.md`. Read
`git log` / `docs/architecture.md` for what was actually built.

---

## 1. Context

`docs/use-case-01-hb127-researcher-screening.md` (approved in principle, no code started)
defines the first fully-specified user for this project: a research security analyst at a
Texas A&M System institution operating Texas HB 127 screening. `docs/requirements.md` §9c
records why the project's shape moved — a corpus-in/ranked-list-out screening tool was built,
verified and deployed against a question no analyst asks; the statutory test is a **failure
to disclose**, which makes this a *declaration-versus-record reconciliation* problem, not a
screening-and-scoring one.

The engine built for V1–V3 transfers almost intact — `pipeline.py` as shared orchestration,
a real API boundary, a thin Streamlit HTTP client. What is genuinely new is a **case model**
(subject, declaration, worksheet, adjudication, investigative file) and a **reconciliation
engine** that diffs a declared affiliation set against what public records show. This plan
covers the vertical slice §12 identifies: *one subject, one declaration, a worked
reconciliation worksheet, an exportable investigative file* — plus the minimum around it to
demo a real finding.

Two planning-phase decisions were folded back into the spec by the user and **must be
committed and pushed before implementation starts** (they are already edited on disk):

- `docs/use-case-01…md` §5 — a new *"Detection is not manual"* requirement (periodic
  re-screening of the closed-case population) and §12 — step 4 split, two discovery paths in
  step 2, coverage recorded at intake not inferred.
- `docs/requirements.md` §9c — the batch orchestration survives *repositioned* as population
  re-screening (not legacy); the corpus UI does not survive; resolution trigger stated.

---

## 2. Pushback — where the spec needs qualifying

The use-case document was written without reference to the code. Most of it holds. Eight
places where it is optimistic, underspecified, or wrong about the current codebase:

**A. "Epics C and D already built — this is wiring, not new matching logic" (§12 step 2) is
mostly right, with one real seam.** Nothing today feeds an ownership-chain parent name into
the concern-list screener. `pipeline.enrich_ownership` computes *only* the cross-jurisdiction
`ForeignControlFlag`; it never screens a parent's `legal_name` against
`screening/lists.py`. The §10 marquee finding ("declared employer's ultimate parent is on the
DoD 1260H list") needs a new compose function (`resolve_entity_to_lei` → `parent_chain` →
screen each resolved parent). It reuses built matchers, but it is a new function and a new
`Finding` producer — treated as its own commit (C3), not "Epic C unchanged."

**B. The case/worksheet/adjudication layer is new *in kind*, not just in LOC.** Every
persistence pattern in the repo today is write-once or delete-and-replace, driven by the
pipeline. A human-driven, **append-only adjudication log** with per-actor attribution and
re-openable cases is a posture nothing here has. It also introduces an **"actor" concept the
system has never had**, with no auth layer behind it. For synthetic-data portfolio scope a
plain `actor` string is fine — but it is a real decision, and the plan names it rather than
letting "thin case model" (Phase 5) hide it.

**C. "The declared set is a merge of scoped sources" (§6) needs a scope model richer than a
date window.** "Highest education only" and "professional/social/charitable org memberships"
are not temporal windows. Each declaration source needs a per-category scope *kind*
(`temporal_window` / `highest_only` / `type_enumeration` / `full_history`) plus a descriptor.
This is load-bearing: it is the grouping key for §8 bulk action ("dismiss everything outside
the DS-160 five-year window in one action"), not display text. Modeled as structured data in
C1.

**D. §7's "NSF… repurposed from input corpus to discovery source — Built, needs repointing"
undersells it.** `NSFAwardIngester` is a corpus ingester (date range / local file). Querying
it by PI name needs a new request mode (`pdPIName`), and its value is narrow — U.S. awards
only, no foreign-affiliation data. It is a new adapter, **deferred out of the slice**; the
slice's two discovery paths are publications and ownership, per the edited §12.

**E. §10 + a synthetic subject means the bibliometric layer — "the core" per §9c — is
exercised in the demo by a labeled fixture only.** Attaching a real author's publication
record to a fictional name is ruled out (§10), correctly. Worth stating plainly: the
strongest *real-data* demo is the ownership finding; the bibliometric core runs on fixtures
until a fully-synthetic-but-realistic works corpus, or a consenting real subject, exists.

**F. The `cli validate` check on `Finding` is a lint, not the `MatchStatus` guarantee.**
`MatchStatus` is airtight — the enum has one member, so "confirmed" is unrepresentable in
code. A field check on `Finding` is a test-enforced convention. The plan strengthens it to
**allowlist equality** (any new field fails CI until the allowlist constant is deliberately
edited in the same commit), which is as close as the language allows — but it is not
identical, and the plan says so.

**G. §4.1's "at no extra cost" is optimistic.** The accumulated-case-law by-product ("how
does your institution define substantial?") is free *only if* dismissal reasons are
structured from commit one. Retrofitting aggregation onto free text is the expensive path, so
`WorksheetAction.reason_code` is a controlled vocabulary in C4.

**H. House real-data-first discipline is not yet satisfied for this plan** — it is written
from spec + code only. Three real-data checks are **binding before the relevant commits
merge**: (1) a real GLEIF Level 2 subsidiary→ultimate-parent chain terminating at a real
1260H entity; (2) ≥6 real declared-vs-discovered institution-name pairs to calibrate the
reconciliation threshold; (3) *(deferred to step 4)* the DNI Annual Threat Assessment
adversary-country derivation. OpenAlex rate-limiting does **not** block the slice — the demo
path is fixture-driven by design, same posture as the existing screening-only demo run.

---

## 3. Binding constraints (restated — design is held to these)

From the task and use-case §4:

1. **Fact/judgment boundary.** The system states observable facts about a discrepancy and
   never evaluates them. `Finding` carries **no** `severity`, `risk`, `priority`, `score`,
   `materiality`, `tier`, `weight`, or `disposition` field. Enforced structurally — a
   `cli.py validate` check fails CI if the field set changes (see §5.1).
2. **`MatchStatus` stays single-member.** A new `Adjudication` records the *human's*
   decision, attributed and timestamped; the tool still asserts none.
3. **No real PII, ever, in this build.** Synthetic subjects only. No personal data in
   manifests or logs (they record dataset provenance only — must stay that way). Field-level
   sensitivity classification on the declaration model; redaction by default in exports.
4. **The declaration model is complete and functional with no DS-160 present.**
   §51B.151(a)(2) covers U.S. citizens, who have no visa application. Not a DS-160-first
   model.
5. **The declared set is a merge of scoped sources.** Every `Finding` states which
   declaration sources were searched and the stated scope of each. The DS-160 five-year
   employment window is the specific trap — a naive diff flags every older affiliation.
6. **Worksheet closure rule.** A case cannot leave `worksheet` state while any finding is
   unactioned. Bulk action (one reason across a selected class) is a requirement.
7. **The foreign-adversary list is versioned and moves** (rolling three-ATA window). Every
   country determination cites the list version that produced it — the
   `GleifSnapshotManifest` pattern.

Plus, from the edited spec: **coverage under §51B.151 is recorded at intake by whoever opens
the case, never inferred by the system** (a legal determination, not an observable fact).

---

## 4. Architecture

### 4.1 New package: `entity_screening/case/`

Case model + lifecycle + services. Kept separate from the batch path so the two evolve
independently.

### 4.2 Schema (`common/schema.py`, all frozen dataclasses)

`Subject` and `Declaration` reject `synthetic=False` in `__post_init__` — "no real PII by
construction", not by policy (see AC 3). `cli validate` asserts the guard fires.

```
Subject(subject_id, display_name, coverage_basis,        # "151a1" | "151a2"
        classified_fields: dict, synthetic: bool)         # __post_init__: synthetic must be True

DeclarationSource(source_id, kind,                        # "ds160"|"passport"|"cv"|"institutional_supplemental"
        present: bool, scope_kind,                        # "temporal_window"|"highest_only"|"type_enumeration"|"full_history"
        scope_descriptor: dict)                           # e.g. {"window_years":5,"anchor":"<submission date>"}

DeclaredAffiliation(affiliation_id, source_id, institution_name,
        country, role, start_date, end_date, activity_kind)

Declaration(declaration_id, subject_id, synthetic: bool,   # __post_init__: synthetic must be True
        sources: tuple[DeclarationSource,...],
        affiliations: tuple[DeclaredAffiliation,...])

Case(case_id, subject_id, office_id="default", trigger, access_scope,
        coverage_basis, statutory_deadline: date|None, state, synthetic: bool)

DiscoveredAffiliation(source,                             # "openalex"|"gleif_ownership"|"nsf_award"
        institution_name, country,
        country_on_adversary_list: bool|None,             # None until step 4
        adversary_list_version: str|None,
        first_observed, last_observed, record_count, role,
        source_refs: tuple[str,...])

DeclarationSearch(source_kind, present: bool, scope_kind,
        scope_descriptor: dict, covers_this_item: bool)

NearestDeclared(declared_affiliation_id, institution_name, best_confidence,
        match_basis, cleared_name: bool, scope_compatible: bool)   # why it didn't clear

Finding(finding_id, case_id, run_id,
        discovered: DiscoveredAffiliation,
        declaration_search: tuple[DeclarationSearch,...],
        factual_basis,                                    # "absent_from_in_scope_source"
                                                          # "absent_only_outside_scope_windows"
                                                          # "partial_match_below_threshold"
        nearest_declared: tuple[NearestDeclared,...],
        concern_list_evidence: tuple[ScreeningHit,...]=(),
        ownership_evidence: tuple[ForeignControlFlag,...]=())
        # NO severity/risk/priority/score/materiality/tier/weight/disposition — on Finding
        #   OR on any type in its graph (DiscoveredAffiliation, DeclarationSearch,
        #   NearestDeclared). The allowlist check (AC 1) covers all of them.

WorksheetAction(finding_id, action,                       # "dismiss"|"request_clarification"|"escalate"|"certification_required"
        reason_code, reason_note, actor, recorded_at, batch_id: str|None)

Adjudication(case_id, seq, assessment, recommendation, actor, recorded_at)   # append-only; re-open => seq+1

Certification(case_id, finding_id, substance_of_failure, reasons_for_disregarding,
        department_head, recorded_at)                     # §51B.153
```

`Finding` reuses the existing `ScreeningHit` and `ForeignControlFlag` types verbatim as
evidence payloads, **stored inline inside the `findings` row (serialized JSON), not written
to `screening_hits` / `ownership_flags`**. Same "inline the matched entry, no further join"
discipline as `screen.py` / `cross_check.py`. One consequence to fix in C3:
`ForeignControlFlag.evidence` does **not** currently carry `source_attribution` (it has
`lei_match_basis` / `relationship_path` / `truncated` only), so the ownership compose must add
GLEIF's and the matched concern list's attribution to the evidence dict — otherwise the new
primary output drops the §10 licence NFR that `ScreeningHit` evidence already satisfies.

### 4.3 Storage (`common/storage.py`) — migration strategy

**All new tables, purely additive.** `SCHEMA_DDL` gains `CREATE TABLE IF NOT EXISTS` for
`subjects`, `declarations`, `declared_affiliations`, `declaration_sources`, `cases`,
`findings`, `worksheet_actions`, `adjudications`, `certifications`. **No `ALTER TABLE` on any
existing table.**

**`reconcile_case` does not write to `screening_hits` / `ownership_flags` / `lei_matches`.**
Concern-list and ownership matching are *called* (the matchers and `parent_chain` run), but
their results are persisted only inside `findings` rows as inline evidence. This sidesteps
`insert_screening_hits`'s delete-by-producer semantics entirely — no fourth `producer` value,
no interaction with a co-existing batch run's rows. The ownership path *does* still load GLEIF
into the shared disposable `gleif_lei` / `gleif_relationships` working tables (via the
existing `load_gleif_level1/2`), exactly as `enrich_ownership` does. `findings` is scoped
`(case_id, run_id)` where `run_id` is minted per reconciliation execution.

The remediation-pass trap (a `CREATE TABLE IF NOT EXISTS` not adding a column to an existing
DuckDB file) **does not apply** here because nothing existing changes shape. On the deployed
instance, a fresh `connect()` against `./data/processed/entity_screening.duckdb` creates the
new tables on first access — existing corpus runs and the `run_id="demo"` run are untouched
and still readable.

Per-table lifecycle (stated explicitly, per house practice):

| Table | Model | On re-run |
|---|---|---|
| `subjects`, `declarations`, `declaration_sources`, `declared_affiliations` | current-state | replace on re-intake |
| `findings` | current-state, scoped | delete-and-replace `WHERE case_id=? AND run_id=?` (mirrors `insert_screening_hits`) |
| `worksheet_actions` | append-only history; latest per `finding_id` is effective | append |
| `adjudications` | **append-only**, `PRIMARY KEY (case_id, seq)` | append seq+1 |
| `certifications` | append-only | append |

### 4.4 Reconciliation engine: `entity_screening/reconciliation/`

- **`discover.py`** — adapters producing `DiscoveredAffiliation`:
  - `discover_from_publications(subject_name, hiring_institution_name, works_by_author, *, fetch=None, works_fixture=None)` —
    reuses `disambiguate_pi_to_openalex_author` + `get_author_works`; aggregates each work's
    `authorships` into `(institution_name, country, year_first, year_last, count, role)`
    tuples. Fixture-driven for the demo (`works_fixture`), live OpenAlex optional.
  - `discover_from_ownership(declared_employer_names, conn, concern_lists, *, threshold, max_depth)` —
    reuses `resolve_entity_to_lei` + `parent_chain`; **new compose (C3):** screens each
    resolved parent `legal_name` via `screening/lists.py`; the existing cross-jurisdiction
    `ForeignControlFlag` rides along as `ownership_evidence`.
- **`reconcile.py`** — `reconcile(declaration, discovered) -> list[Finding]`:
  - No blocking (both sets are tens of rows). For each `DiscoveredAffiliation`, `score_pair`
    against every `DeclaredAffiliation.institution_name` (reusing `resolution/matcher.py` +
    `normalize.py` — acronym/suffix handling already there is useful for institutions).
  - "Declared" = best name match ≥ `RECONCILIATION_THRESHOLD` **and** the declared entry's
    scope admits the discovered fact's date range. Otherwise → `Finding`.
  - `factual_basis` = `absent_from_in_scope_source` if a *present, in-scope* source would
    have captured it; `absent_only_outside_scope_windows` if every source that could carry it
    is out of scope (the mid-career-affiliation case); `partial_match_below_threshold` if a
    near-match exists. `nearest_declared` retains the sub-threshold candidates and why they
    didn't clear — same discipline as `author_resolve` keeping tied candidates.
  - `RECONCILIATION_THRESHOLD` gets its own constant + rationale (like
    `DEFAULT_CONCERN_THRESHOLD = 0.90` did), **calibrated against ≥6 real institution-name
    pairs before merge**, recorded in `docs/data_sources.md`.

### 4.5 `pipeline.py` — new entry points, existing ones repositioned

- **`reconcile_case(case_id, *, db_path, runs_dir, fetch=None, works_fixture=None) ->
  (ReconciliationManifest, list[Finding])`** — mints a `run_id`, runs both discovery paths,
  reconciles, persists findings (delete-and-replace per `run_id`), writes the manifest.
  **Never touches `scored_entities`.** Same "separate explicit step" posture as
  `enrich_ownership` / `enrich_bibliometric`.
- Case services (worksheet actions, adjudication, certification, export) live in
  `case/service.py`, called by both the API and a new CLI subcommand.
- **`run_screening` repositioned, not retired.** Docstring + `docs/architecture.md` +
  `docs/methodology.md` updated in the slice to describe it as *population re-screening
  against updated reference data* (the edited §5 requirement). The identifier/CLI-subcommand
  rename and the retirement of `resolve_entities_from_nsf` (used only by `run_screening`,
  groups awards into org entities — no role in the case model) are **deferred to the trigger
  commit**: *resolved when the case path can produce a closed, exported investigative file.*
  Deferring the mechanical rename keeps the slice diffs legible.

### 4.6 Manifests (`common/manifest.py`)

- **`ReconciliationManifest`** (per reconcile run) — `case_id` (opaque), `run_id`,
  `reconciled_at`, discovery-source provenance (OpenAlex `queried_at`, GLEIF snapshot ref,
  concern-list versions, `adversary_list_version` once it exists), `reconciliation_threshold`,
  finding counts. **Contains no subject name / DOB / passport** — `case_id` is the only join
  key. Mirrors `BibliometricSnapshotManifest` + `GleifSnapshotManifest`.
- **`InvestigativeFileManifest`** (per export) — `case_id`, `exported_at`, `redaction_profile`,
  adjudication `seq` exported, format. Mirrors `ExportManifest`'s per-call immutability.
- **`AdversaryListManifest`** *(step 4, not the slice)* — list version, ATA-year derivation,
  gubernatorial designations, source URLs.

### 4.7 API (`api/main.py` + `api/dto.py`)

New routes, mirroring the `enrich_*` posture; mutations gated by the existing
`_require_action_secret` dependency; the existing `MONOPS_DATA_FILE_ALLOWLIST` still applies
to any file path:

```
POST /cases                               create from synthetic subject+declaration+coverage (gated)
POST /cases/{id}/declaration              attach/replace declaration sources (gated)
POST /cases/{id}/reconcile                run discovery + reconciliation (gated)
GET  /cases/{id}/worksheet                findings + effective actions + case state
POST /cases/{id}/findings/{fid}/action    single analyst action + reason (gated)
POST /cases/{id}/worksheet/actions        bulk action over a finding-id set + one reason (gated)
POST /cases/{id}/adjudication             record assessment + recommendation (gated)
POST /cases/{id}/certifications           §51B.153 department-head certification (gated)
GET  /cases/{id}/investigative-file.json  export (redaction-by-default)
GET  /cases/{id}/investigative-file.xlsx  export
```

Self-healing demo case (`case_id="demo"`) via `_ensure_demo_case_exists`, a mirror of
`_ensure_demo_run_exists` — built lazily from bundled fixtures, **zero live network calls**.

The corpus routes (`POST /runs`, `/runs/{id}/scores`, exports, the three `enrich_*`) **stay**,
dropped from the FastAPI `description`/tags so they are unadvertised but still callable and
CI-covered.

### 4.8 Streamlit (`app.py`)

The case worksheet becomes the **only visitor-facing view**. Sections: demo case loads on
landing (self-heal) → synthetic-data banner → intake form (subject, coverage basis, deadline)
→ structured declaration entry (rows tagged source + scope) → "Run reconciliation" (gated) →
**worksheet table, one row per finding** (discovered fact / declaration-search trail /
factual basis / measurable attributes / evidence / action / reason / actor) with multi-select
+ bulk action → closure-rule indicator → adjudication panel → "Export investigative file".

Removed from the visitor view: the scored/filterable entity table, rubric sliders, the
topic-similarity section. `scoring/` stays in the repo serving the (hidden) batch path only.

### 4.9 Demo fixtures

- Synthetic `Subject` + `Declaration`: declared employer = a synthetic Chinese subsidiary;
  DS-160 present (5-yr window) + CV present (full history) + passport.
- Real bundled GLEIF Level 1/2 sample + real DoD 1260H snapshot.
- **Binding real-data check (H):** confirm a real GLEIF L2 subsidiary→ultimate-parent chain
  terminating at a real 1260H-listed entity. If it exists → use the real subsidiary name. If
  not → a **clearly-labeled synthetic GLEIF fixture row for the subsidiary only**, whose
  `IS_DIRECTLY_CONSOLIDATED_BY` edge points at a real parent LEI genuinely on 1260H. Either
  way the parent evidence is real.
- Second finding: a **clearly-labeled bibliometric fixture** (`works_fixture`) — a fabricated
  works list for the synthetic subject showing an affiliation absent from the declaration. No
  real person's works.
- No adversary-list finding in the slice demo (step 4).

---

## 5. Binding acceptance criteria

1. **The whole `Finding` graph has a frozen field set.** A `_FINDING_GRAPH_ALLOWED_FIELDS`
   dict in `schema.py` maps each type in the graph — `Finding`, `DiscoveredAffiliation`,
   `DeclarationSearch`, `NearestDeclared` — to its allowed field names; `cli.py validate`
   asserts every one matches. Guarding only `Finding`'s outer shell would let `risk_tier` be
   added to `DiscoveredAffiliation` and still reach the export — the exact "guarantee lost at
   a boundary" pattern the 2026-09-02 evaluation found four times. Any added field on any of
   these types → CI red until the dict is edited in the same commit. `Finding` has no
   `disposition` — the human action is a separate `WorksheetAction` record.
2. **`MatchStatus` stays single-member** (`test_cli_validate` already covers this). The human
   decision lives only on `Adjudication` / `WorksheetAction` / `Certification`, each
   attributed + timestamped.
3. **No real PII by construction.** `Subject.__post_init__` and `Declaration.__post_init__`
   raise on `synthetic is not True`; `cli validate` asserts the guard fires; the constraint is
   documented on both types. This is the difference between "no real PII by policy" and "by
   construction", consistent with how the rest of the design makes bad states
   unrepresentable. `ReconciliationManifest`, `InvestigativeFileManifest`, and
   `ingestion_errors.jsonl` contain `case_id` only. A test reconciles + exports the demo case,
   then greps every written manifest + log + run-dir file for the synthetic subject's surname
   and asserts absence. Exports redact classified fields by default (`redaction_profile` on
   the manifest); a test asserts a raw export never contains a classified field value.
4. **Complete with no DS-160.** A test runs full reconciliation on a subject whose only
   sources are CV + passport (coverage basis `151a2`, a U.S. citizen); no `DeclarationSearch`
   references a DS-160 window; findings still produced and adjudicable.
5. **Scoped-source trail on every finding.** Each `Finding` carries `declaration_search`
   listing every source searched, its `scope_kind` + descriptor, and `covers_this_item`. A
   test with a 15-year career and a 5-year DS-160 asserts the older affiliations land as
   `absent_only_outside_scope_windows` (not `absent_from_in_scope_source`) and are selectable
   as one class for bulk dismissal.
6. **Closure rule + bulk action.** `Case` cannot transition out of `worksheet` while any
   finding lacks an effective `WorksheetAction`; enforced in the transition function and
   asserted. Bulk action writes one `WorksheetAction` per finding sharing a `batch_id`.
7. **Adversary list versioned + cited** *(step 4)*. Until built, `country_on_adversary_list`
   is `None` and the worksheet shows "adversary-list check not yet run" — never implies
   "clear". When built, every determination carries `adversary_list_version` + `basis`;
   `AdversaryListManifest` records the ATA derivation.
8. **Two discovery paths through one `Finding`.** Slice tests exercise both
   `discover_from_publications` (fixture) and `discover_from_ownership` (real GLEIF + 1260H)
   producing `Finding`s that flow through the *same* worksheet / adjudication / export code —
   the architectural test the edited §12 calls for.
9. **Ownership-parent-vs-concern compose is documented as new wiring** (C3), reusing
   `resolve_entity_to_lei` + `parent_chain` + the concern-list matchers, with the
   jurisdiction-mismatch flag carried as `ownership_evidence` — not described as "Epic C
   unchanged".
10. **`RECONCILIATION_THRESHOLD`** has its own constant + rationale, calibrated against ≥6
    real declared-vs-discovered institution-name pairs before the C2 merge, recorded in
    `docs/data_sources.md`.
11. **Batch path repositioning.** `run_screening` docstring + `architecture.md` +
    `methodology.md` describe it as population re-screening in the slice; the identifier/CLI
    rename + `resolve_entities_from_nsf` retirement are deferred to the trigger commit; the
    corpus Streamlit view is removed; the corpus API/CLI stay CI-covered — the `docker` job's
    `entities_count==2 and hits_count==1` assertion **stays green at every commit boundary**.
12. **`reconcile_case` writes zero rows to `scored_entities`.** Findings delete-and-replace
    per `run_id`; `adjudications`/`certifications`/`worksheet_actions` append-only; re-opening
    a closed case appends `Adjudication.seq+1` and a fresh reconciliation `run_id`, leaving
    prior findings + adjudication readable. Idempotency test, extending
    `test_idempotency.py`'s shape.
13. **§4.1 case-law by-product.** `WorksheetAction.reason_code` is a controlled vocabulary
    from C4. A `GET /cases/dismissal-basis-summary` route (+ CLI report) aggregates
    dismissals by `reason_code` across closed cases.
14. **The investigative file carries source attribution + licence** (§10 NFR — "surfaced in
    output, not just a README"). Every `concern_list_evidence` / `ownership_evidence` payload
    in the export carries `source_attribution` with `attribution` and `license` populated
    (GLEIF's for the ownership path — added to `ForeignControlFlag.evidence` in C3 since it is
    absent there today). The extended `test_output_contract.py` asserts this on the parsed
    export, mirroring the assertion it already makes for the corpus CSV. The new primary
    output must not silently drop a requirement the old one satisfied.

---

## 6. Tests

- **Extend `tests/test_output_contract.py`** — investigative-file export boundary: parse the
  exported file and the `/worksheet` JSON; assert every finding row carries the
  discovered-fact + `declaration_search` trail + `factual_basis` + evidence; assert every
  evidence payload carries `source_attribution` with `attribution` + `license` populated
  (AC 14); assert **no** `severity`/`risk`/`priority`/`score`/`materiality` key anywhere in
  the export or `/worksheet` JSON (walk the whole `Finding` graph, not just the top level —
  AC 1); language discipline — no "confirmed", no "substantial", no "risk score", no
  recommended-disposition string in any system-generated field (human `reason_note` exempt,
  and flagged as human text).
- **Extend `tests/test_idempotency.py`** — `reconcile_case` twice → identical findings,
  `worksheet_actions`/`adjudications` untouched; re-open → new `seq`, prior intact; a
  co-existing batch run's `screening_hits` survive untouched.
- **`tests/test_case_lifecycle.py`** — state machine, closure rule, bulk action, no-DS-160
  path, 15-year-career scope classification.
- **`tests/test_reconciliation.py`** — `score_pair`-based matching, scope compatibility,
  `nearest_declared` retention, both discovery adapters against fixtures.
- **`tests/test_finding_contract.py`** (or fold into `test_cli_validate.py`) — the
  allowlist-equality assertion.
- **`tests/test_pii_never_in_manifests.py`** — reconcile + export the demo case; grep every
  written manifest + log for the synthetic surname → absent; raw export has no classified
  field value.
- **`tests/test_demo_case.py`** — self-heal on first `/cases/demo/worksheet`; idempotent;
  produces the real ownership finding + the fixture bibliometric finding; no field ever reads
  "confirmed".
- **CI** — new tests run in the existing `test` job (no new deps; OpenAlex is fixture-driven
  in tests). `pytest -q` and `python -m entity_screening.cli validate` green **at every
  commit boundary**. The `docker` job's corpus assertion is a parity guard and must stay
  green.

---

## 7. Out of scope for this slice

- **Foreign-adversary-country list** acquisition + verification against the three most recent
  DNI Annual Threat Assessments — engine hook + `None` state only; the list, its manifest,
  and its verification are step 4, their own commit after the spine.
- **NSF-by-PI-name discovery adapter**, `resolve_entities_from_nsf` retirement, and the
  `run_screening` identifier rename — deferred to step-2 breadth / the repositioning trigger.
- **CV / document parsing** — declaration intake is structured data entry; the CV is a source
  tag on manually-entered rows, never a parsed file (consistent with §9).
- Export-control / restricted-party bundling (§12 step 5); COI / NSPM-33 reuse (step 6).
- **Multi-tenant** (19 A&M offices) — `Case.office_id` present and defaulted; no tenant
  isolation or filtering.
- Epic J LLM explanations.
- Real subject data of any kind; live OpenAlex on the demo's critical path.
- **Rubric / scoring in the case view** — `scoring/` stays serving the hidden batch path
  only; `Finding` carries no score; queue-ordering (one case in the slice) is meaningless
  here and is not ported.
- SLA / deadline-countdown logic — `statutory_deadline` stored, not enforced.
- Authn / login — `actor` is a plain string.

---

## 8. Blocking vs. deferred open questions (use-case §11)

**Blocks the demo (not the engine):**
- The adversary-country list must be derived + verified against the three most recent DNI
  ATAs before any adversary determination ships. The slice builds the engine hook with a
  `None` state; the demo presents no adversary determination.
- The real GLEIF→1260H chain check (§4.9) before the demo's headline finding is committed.

**Does not block — stated assumptions:**
- §51B.152(2) council-determined supplemental content → modeled as an open
  `institutional_supplemental` `DeclarationSource` kind with an extensible field set.
- Single- vs multi-tenant → single-tenant; `office_id` stub for a later filter, not a
  migration.
- Turnaround expectations → `statutory_deadline` stored as a first-class field, no SLA logic.
- "How 'substantial' settles" → deliberately unresolved; captured via `reason_code`
  aggregation (§4.1).

---

## 9. Verification

- `pytest -q` + `python -m entity_screening.cli validate` green.
- `uvicorn entity_screening.api.main:app --reload` + `streamlit run app.py` → landing shows
  the demo case worksheet with ≥2 findings (one real ownership, one fixture bibliometric);
  walk one finding through dismiss-with-reason, one through certification-required; record an
  adjudication; export the investigative file; confirm the exported file carries the
  `declaration_search` trail and no evaluative field.
- New `cli` case subcommand runs reconcile → worksheet → export against fixtures, headless.
- **Corpus parity:** `POST /runs` with the existing fixtures still returns
  `entities_count==2, hits_count==1`; the `docker` CI job still passes.
- **Real-data checks (binding, before the relevant commit merges):**
  1. A real GLEIF L2 subsidiary→ultimate-parent chain terminating at a real 1260H entity.
  2. ≥6 real institution-name pairs to calibrate `RECONCILIATION_THRESHOLD` — obtainable
     without any real subject: OpenAlex `display_name` vs its own `display_name_alternatives`
     / `display_name_acronyms`, and GLEIF `legal_name` vs the institution's common name.
     Recorded in `docs/data_sources.md`.
  3. *(step 4, deferred)* DNI ATA adversary-country derivation.
- Grep the deployed-shape run dir + all manifests for the synthetic subject name → absent.

---

## 10. Commit sequence

**Pre-implementation (do first, push before any code):**
- **P1** — this plan → `docs/plans/2026-09-06-use-case-01-implementation.md` +
  `docs/plans/README.md` index row ("Plan, not yet built").
- **P2** — the already-edited `docs/use-case-01…md` §5/§12 + `docs/requirements.md` §9c,
  committed as "fold planning-phase scope decisions into the spec".

**Slice:** fixtures are created in the commit that first needs them (tests need them anyway),
so the self-healing demo case in C6 has everything to build from — C6 does not depend on a
later commit.

- **C1** — schema + storage: all new dataclasses (incl. `__post_init__` synthetic guards);
  new DuckDB tables in `SCHEMA_DDL` (no `ALTER`); `cli validate` graph-allowlist + synthetic-
  guard assertions. No behavior.
- **C2** — `reconciliation/` (`discover.py` publications path, `reconcile.py`),
  `RECONCILIATION_THRESHOLD` (+ real-pair calibration in `docs/data_sources.md`); name-string
  core extracted from `institution_match`; `pipeline.reconcile_case`; `ReconciliationManifest`.
  **Ships** the synthetic `Subject` + `Declaration` fixture and the labeled bibliometric
  `works_fixture`.
- **C3** — ownership discovery path: the parent-vs-concern-list compose + `source_attribution`
  added to `ForeignControlFlag.evidence` + jurisdiction flag as `ownership_evidence`.
  **Ships** the demo GLEIF/1260H fixture rows (+ a `.NOTICE.md` provenance file for any
  synthetic GLEIF row, mirroring `demo_opensanctions_targets.NOTICE.md`) after the real-data
  chain check.
- **C4** — worksheet + analyst actions + bulk action + closure rule; `Adjudication`
  append-only + re-open; `reason_code` vocabulary.
- **C5** — §51B.153 `Certification` + investigative-file export + `InvestigativeFileManifest`
  + redaction-by-default + the extended `test_output_contract.py` (AC 1, 14).
- **C6** — API routes + DTOs + action-secret gating + `_ensure_demo_case_exists` (builds from
  the C2/C3 fixtures, no live calls).
- **C7** — Streamlit: case worksheet becomes the only visitor view; corpus view removed;
  corpus routes/CLI retained + unadvertised. **Deploy the remediation pass first (see §11).**
- **C8** — `test_demo_case.py` + docs sweep (`architecture.md`, `methodology.md`,
  `data_sources.md` for the new fixtures, `use-case-01` status header, `requirements.md` §9c
  forward-pointer, `plans/README.md` → "Built").

**Later (the repositioning trigger — case path produces a closed, exported investigative
file):** adversary-list ingester + `AdversaryListManifest` + verification; `run_screening` →
population-rescreen rename + CLI subcommand rename; `resolve_entities_from_nsf` retirement;
NSF-by-PI-name discovery adapter.

Every commit: `pytest -q` + `cli validate` green; the corpus `docker` CI assertion green; the
`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` trailer.

---

## 11. Deployment sequencing

`origin/master` is current, but the Lightsail instance has not been confirmed redeployed
since the remediation pass — if that is still true, the live site runs **pre-remediation
code**, and without intervention the security lockdown (Workstream 2: action gate, file
allowlist, rate limiting, noindex), the case worksheet, and the removal of the corpus view
would all land in one deploy — a large change to verify against a live box, and a security
exposure left standing in the meantime.

**Deploy the remediation pass on its own, and confirm it, before C7 lands.** The refactor
then deploys against a known-good, locked-down baseline instead of compounding three
independent changes into one verification. This also means the `_ensure_demo_case_exists`
self-heal, the action-gate wiring on the new `/cases/*` mutation routes, and the
`MONOPS_DATA_FILE_ALLOWLIST` behaviour are all being added *on top of* code already proven in
production, not alongside it.

Update `memory/project_monops_deployment_status.md` once the remediation-pass deploy is
confirmed.

## Correction (2026-09-17, Phase 6 remediation, S16)

Three claims in this plan were never built and are not planned as
remediation:

- §4.5 ("called by both the API and a new CLI subcommand")
- §9 ("New `cli` case subcommand runs reconcile → worksheet → export
  against fixtures, headless")
- AC 13 ("A `GET /cases/dismissal-basis-summary` route (+ CLI report)
  aggregates...")

`entity_screening/cli.py` has exactly two subcommands, `run` and
`validate` — no `case` subcommand, and no CLI dismissal-basis-summary
report, exist anywhere in this codebase. Per the 2026-09-15 pre-ship
review's S16 and the remediation strategy's own framing: this is a
feature dressed as a finding, not a regression to fix. It will be built
later, as a real feature with its own review, only if headless
demo-scenario generation actually needs it — not smuggled in under
hygiene remediation. See
`docs/plans/2026-09-17-phase-6-ops-performance-hygiene.md`'s S16
section for the full decision record.
