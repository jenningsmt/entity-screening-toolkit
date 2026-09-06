# Concern ties as a distinct observation, not a Finding

**Status:** Plan, not yet built. Approved 2026-09-06 (with the pairing change folded in —
§4.1's `related_finding_id` join replaces a presentation-layer name match; see §4.1, §4.11,
AC 5).
**Prompted by:** the first real export from the deployed HB 127 slice, where the
ownership observation (declared employer's ultimate parent on the DoD 1260H list) was
classified as a bulk-dismissable declaration-scope gap and dismissed. Root cause: the two
discovery paths answer different statutory questions and were forced through one type.

This is a historical record of the plan as approved, per `docs/plans/README.md`. Read
`git log` / `docs/architecture.md` for what was actually built.

*Named `ConcernTie`, not `AdversaryTie`: §51B.001's "foreign adversary" is a country
determination that is not built; 1260H and OpenSanctions are entity lists. The
adversary-country status is one nullable attribute on the type, not its name.*

---

## 1. Context

The first real export from the deployed HB 127 slice
(`docs/plans/2026-09-06-use-case-01-implementation.md`) showed the ownership finding — a
declared employer whose ultimate parent is on the DoD Section 1260H list — classified
`factual_basis: absent_outside_all_source_scopes`, `in_scope_of: (none)`. That bucket was
built to hold affiliations older than the DS-160's five-year window: the class an analyst
**bulk-dismisses**. In the walk-through it *was* dismissed, reason code
`outside_declaration_scope`.

The classification is literally accurate and materially misleading. The subject **did**
declare the employer. The observation is that the declared employer is controlled by a
concern-listed entity — which is not a non-disclosure at all.

**Root cause: the two discovery paths answer different statutory questions.** §51B.153's
employment bar is about *failure to disclose*. §51B.151(b)'s background check is about
*ties to a foreign adversary "that would prevent the person from being able to maintain
the security or integrity"* of the institution's research (operative text to be verified —
see pushback A). The reconciliation engine implements the first. The ownership path belongs
to the second, and forcing it through a declaration-diff frame mislabels it.

**This is the experiment working.** §12 of the use-case doc took "two structurally
different discovery paths flowing through one `Finding`" as a deliberate decision, with the
stated rationale that a `Finding` designed against one kind of evidence would need
reshaping when the second arrived, and that finding out early — inside the slice, while
reshaping is cheap — was worth doing. It did need reshaping. The plan folded that risk in
knowingly; the first real export surfaced it exactly where and when it was supposed to.

**Decision, made by the user as the analyst, not up for re-litigation:** an undisclosed
affiliation and a concern-linked employer become **two distinct kinds of thing, not one
type with a discriminator** — two worklists, triaged differently, with different dismissal
reasoning.

---

## 2. Pushback — where the task is optimistic, expensive, or wrong about the code

**A. §51B.151(b) is not in the spec, and the task paraphrases it.** The use-case doc's
method note: *"Every requirement traceable to statute quotes the operative text rather than
paraphrasing it."* §1 currently says *"Three provisions do the work"* and quotes only
§51B.151(a), §51B.152, §51B.153. The task supplies `"ties to a foreign adversary that
would prevent the person from being able to maintain the security or integrity"` — which
reads like a real fragment. **Resolved on review:** the user confirmed the operative text
and that P2 may proceed quoting it. §1 gains §51B.151(b) as a fourth quoted provision
(*"Three provisions"* → *"Four"*), and P2 is no longer blocked. The two-types *decision*
stood regardless of the precise (b) wording — it rests on the §51B.153-vs-background-check
distinction, which §1.1 consequence 1 already draws ("not on nationality, not on
affiliation, not on a concern-list hit"). Kept in the pushback list because the general
lesson holds: had the user not been the domain authority here, this would be a blocking
web-verification step, not an assumption.

**B. "Concern list" is not "foreign adversary" — the name matters.** §51B.001 defines a
foreign adversary as a *country* (the rolling three-ATA DNI list). The DoD 1260H list and
OpenSanctions are *entity* lists. A tie to a 1260H company is evidence relevant to a
research-security background check, but a type called `AdversaryTie` overclaims — it
implies the §51B.001 country determination, which is a **separate, still-unbuilt
attribute** (step 4). Recommend **`ConcernTie`**, carrying the adversary-country status as
one nullable attribute (`country_on_adversary_list`, cited to the list version per §4's
existing rule). The task's title says "adversary ties"; the plan proposes the more precise
name and says why. If the user wants "adversary" in the name, that is a one-pass rename —
flag before the spec edits, not after.

**C. The both-at-once case is currently hypothetical in the case path, and making it real
adds scope.** `discover_from_publications` today aggregates the subject's *own* OpenAlex
affiliations and **never screens them against concern lists**. The Seven Sons universities
(Beijing Institute of Technology among them) are in **OpenSanctions, not the DoD 1260H
list** -- verified: BIT's best match in the bundled 1260H file is 0.73, well under the 0.90
concern threshold, and none of the demo's own affiliations match it. So a concern-screen of
the subject's own affiliations against the bundled list is inert on the demo; the
both-at-once case needs OpenSanctions in the case path (a ~450 MB file the demo omits) or a
purpose-built fixture. Recommendation: **this pass builds the `ConcernTie` type, the
ownership->tie path, and `ties_from_own_affiliations` screening against the bundled 1260H
list** (real machinery, inert on the demo); the both-at-once *demonstration* is a **test
fixture**, and OpenSanctions in the case path plus the co-author-institution tie
(`cross_check_bibliometric`'s shape) are follow-ons.

**D. Removing `Finding.concern_list_evidence` / `Finding.ownership_evidence` touches ~11
sites plus the `findings` table shape.** Both fields are populated *only* by
`reconcile_ownership` today (the publication path never sets either). Once the ownership
path emits a `ConcernTie` instead, both become dead. Removing them is the right call — it
returns `Finding` to a pure declaration-vs-record discrepancy, matching `reconcile.py`'s
own docstring. But it is a wide edit (§4 architecture lists every site) and the risk is a
stale reference to a removed field surviving somewhere — the "guarantee lost at a
boundary" pattern in reverse.

**E. The deployed demo case is the real migration problem, not the column.** `findings` is
current-state-per-case and delete-and-replace; the two dropped JSON columns can be handled
with an explicit-column `INSERT`/`SELECT` (extra columns on a pre-existing DB are simply
ignored — no `ALTER` needed; DuckDB `DROP COLUMN` support is verified at implementation
time only as optional cleanup). But `_ensure_demo_case_exists` returns early when the case
row exists, so after a deploy the **stale ownership `Finding` persists in `findings` and no
`concern_ties` rows exist** until someone manually hits `/cases/demo/reconcile`. Fix: a
`demo_meta(key, value)` one-row table storing a `fixture_version`;
`_ensure_demo_case_exists` rebuilds the demo case's rows across all case tables and
re-reconciles when the stored version differs from the code constant. Cheap, and
future-proofs every later demo-fixture change.

**F. `ScreeningHit.entity_id` is already misused on the ownership path** (the "also fix"
item): `discover.py:_screen_name_against_concern_lists` sets
`entity_id=ownership_context["declared_employer_name"]` — a name in a field that is a UUID
everywhere else. The `ConcernTie` rework is the natural place to fix it: the inlined
`ScreeningHit.entity_id` becomes the declared `affiliation_id` (the subject-side anchor),
with the name carried in evidence as it already is.

**G. Closure-rule volume is asymmetric between the two worklists.** A mid-career
researcher's `Finding` list can be dozens of rows (the §6 trap) — bulk action is
load-bearing there. A `ConcernTie` list should be *short* — a tie to a concern-listed
entity is rare. Per-tie disposition is the norm; tie bulk action is a cheap consistency
nicety, not a requirement. The plan includes it but notes the asymmetry.

**H. `discover_from_ownership` currently skips a parent that is itself declared** (`if
best.cleared: continue`). Under the reframe that skip is wrong: a subject who works for a
company controlled by a 1260H entity has a §51B.151(b) tie **whether or not** the parent
was disclosed — disclosure is the §51B.153 question, irrelevant here. The `ConcernTie`
path emits the tie regardless. Behavior change (improvement) the reframe enables.

**I. `reconcile._source_covers`'s `_OWNERSHIP_SOURCES` special-case becomes dead** once
`gleif_ownership` items never reach `reconcile` / `build_finding`. Remove it.

---

## 3. Binding constraints (restated — design is held to these)

1. **Fact/judgment boundary.** `ConcernTie` and every type in its graph carry **no**
   `severity`, `risk`, `priority`, `score`, `materiality`, `tier`, `weight`, `disposition`
   or `rank` field — **and specifically no field asserting the "would prevent … security
   or integrity" conclusion** (no `impairs_*`, `would_prevent`, `disqualifying`, etc.).
   `ConcernTie` is added to `cli.py validate`'s Finding-graph allowlist guard
   (`_FINDING_GRAPH_ALLOWED_FIELDS`, renamed `_OBSERVATION_GRAPH_ALLOWED_FIELDS`); a
   `_FORBIDDEN_FINDING_FIELD_TOKENS` addition covers the (b)-conclusion words.
2. **`MatchStatus` stays single-member.** The tie's evidence (`ScreeningHit`,
   `ForeignControlFlag`) keeps `CANDIDATE_MATCH`. The human's decision lives on a
   `TieAction` / `Adjudication` record, attributed and timestamped.
3. **No real PII.** Synthetic subjects only; the `Subject`/`Declaration` `__post_init__`
   guards stay; `cli.py validate` still asserts them.
4. **Provenance on every observation.** Each `ConcernTie` states how the tie was
   established (traversal path in its evidence) and carries `source_attribution`
   (the concern list's and, for an ownership tie, GLEIF's) through to the export, exactly
   as `Finding` does today.
5. **Export provenance block + redaction-by-default apply to the new section.** The
   existing `PROVENANCE_NOTICE` already covers fabricated ownership chains; no change
   needed there beyond adding the `concern_ties` payload it implicitly describes.

---

## 4. Architecture

### 4.1 New type: `ConcernTie` (`common/schema.py`)

```
class TieKind(Enum):                       # a factual descriptor of the connection, never evaluative
    DECLARED_EMPLOYER_ULTIMATE_PARENT = "declared_employer_ultimate_parent"
    DECLARED_AFFILIATION_DIRECT       = "declared_affiliation_direct"        # a declared institution is itself listed
    OWN_AFFILIATION_HISTORY           = "own_affiliation_history"            # subject's own OpenAlex affiliation matches
    # CO_AUTHOR_INSTITUTION -- follow-on, not this pass

@dataclass(frozen=True)
class ConcernTie:
    tie_id: str
    case_id: str
    run_id: str
    tie_kind: TieKind
    anchor_affiliation_id: str | None      # the DECLARED affiliation this tie runs from
                                           #   (kinds 1 & 2); None for OWN_AFFILIATION_HISTORY
    related_finding_id: str | None         # set when the SAME discovered affiliation also
                                           #   produced a Finding (the both-at-once case) --
                                           #   a join key, not a name match; always None for
                                           #   an ownership tie (it has no corresponding finding)
    concern_entity_name: str               # the concern-listed entity as the list names it
    country: str | None
    country_on_adversary_list: bool | None  # None = not yet checked (step 4); never "clear"
    adversary_list_version: str | None
    first_observed: str | None             # for a publication-derived tie
    last_observed: str | None
    record_count: int
    concern_list_evidence: tuple[ScreeningHit, ...]        # the concern-list match(es), inlined
    ownership_evidence: tuple[ForeignControlFlag, ...] = ()  # cross-jurisdiction flag, when applicable
```

`anchor_affiliation_id` replaces a loosely-typed `subject_anchor: str` that would have held
"an id or a phrase" — the same smell as last pass's `nearest_declared: tuple[dict, ...]`.
`tie_kind` already says what kind of connection this is; the anchor is now always either a
real declared `affiliation_id` or `None`, and the measurable-attribute fields describe an
`OWN_AFFILIATION_HISTORY` tie.

`related_finding_id` is how a `ConcernTie` and a `Finding` for the *same* discovered
affiliation are paired (pushback: do not name-match in the UI). In the both-at-once case
the tie is derived from the very `DiscoveredAffiliation` that produced the finding, so the
relationship is known at creation — `reconcile_case` stamps it (§4.3). The grouping is then
a join, not an inference.

The traversal path and its truncation status live **inside** the evidence payloads
(`ScreeningHit.evidence["ownership_path"]`, `ForeignControlFlag.relationship_path` /
`.evidence["truncated"]`) — where they already are — not duplicated on `ConcernTie`.

`Finding` **loses** `concern_list_evidence` and `ownership_evidence` (pushback D). Every
site: `schema.Finding`, `_OBSERVATION_GRAPH_ALLOWED_FIELDS["Finding"]`,
`case/store.py` (`replace_findings` INSERT column list, `load_findings` SELECT,
`_finding`-related helpers), `case/export.py:_finding_to_dict` + `_write_xlsx` Findings
sheet, `api/case_routes.py:_worksheet_payload`, `reconcile.build_finding` (drop the two
kwargs), `reconcile.reconcile_ownership` (deleted). `_OBSERVATION_GRAPH_ALLOWED_FIELDS`
gains `"ConcernTie"` and any nested type; `cli.py validate`'s loop iterates it.

### 4.2 Reason-code vocabulary for ties (`case/vocab.py`)

`outside_declaration_scope` is meaningless for a tie. New controlled sets:

```
TIE_DISMISS_REASON_CODES = {
  "historical_or_divested_relationship":
      "The tie is to a relationship that has ended -- the ownership link or the "
      "subject's involvement is no longer current.",
  "designation_postdates_the_relationship":
      "The concern-list designation took effect after the subject's involvement "
      "ended (cite both dates in the note).",
  "immaterial_to_requested_access_scope":
      "The tie does not touch the research data or systems this access request "
      "concerns. The access scope and the reasoning are in the note.",
  "misidentified_entity":
      "The name match is to a different entity than the concern-listed one "
      "(the 'Chinese Academy of Sciences' / 'Ordnance Science' shape).",
  "known_and_previously_reviewed":
      "Reviewed in a prior case or disclosure cycle; disposition on record.",
  "analyst_judgment_tie_does_not_impair":
      "In the analyst's judgment the tie would not prevent this person, in this "
      "role, from maintaining the security or integrity of the research. The "
      "reasoning is in the note -- this code records only that the basis was the "
      "analyst's own Sec. 51B.151(b) judgment.",
  "other": "A basis not covered above; see the note.",
}

TIE_ESCALATION_REASON_CODES = {
  "needs_supervisor_review":        "Beyond the analyst's authority to dispose of alone.",
  "needs_export_control_review":    "Implicates export-control / restricted-party questions.",
  "needs_counterintelligence_referral":
      "Meets the office's threshold for referral to the institution's research "
      "security / counterintelligence point of contact.",
  "needs_subject_clarification":    "Cannot be dispositioned without input from the subject.",
  "recommend_access_scope_limitation":
      "Route to the department with a recommendation to limit what the person can "
      "access, rather than to block employment.",
  "other": "See the note.",
}
```

`is_valid_reason_code` gains an observation-kind parameter (or a sibling
`is_valid_tie_reason_code`). Both dismiss vocabularies feed §4.1's
`/cases/dismissal-basis-summary`, split by observation kind.

**On `analyst_judgment_tie_does_not_impair`:** this reason code *does* record the
§51B.151(b) "would prevent … security or integrity" conclusion — correctly, because it is
the **human's** conclusion, recorded on a `TieAction`, which is the right side of the
fact/judgment line (same shape as the existing `analyst_judgment_not_material`). The
forbidden-token guard (§3.1) applies to **field names on the observation types**, not to
reason-code *values*, so there is no conflict. It looks like a violation at a glance;
stated here so a future reviewer does not have to re-derive why it is not.

### 4.3 Discovery (`reconciliation/discover.py`)

- `discover_from_ownership` → **`tie_from_ownership`**, returns `list[ConcernTie]` directly
  (no `OwnershipDiscovery` intermediate; the type only ever fed `reconcile_ownership`).
  Drops the "skip if the parent is itself declared" branch (pushback H). Fixes
  `ScreeningHit.entity_id` to the `affiliation_id` (pushback F).
- **New: `ties_from_own_affiliations(discovered_affiliations, concern_lists, ...)`** —
  screens each `DiscoveredAffiliation` the publication path already produced against the
  registered concern lists; emits a `ConcernTie(tie_kind=OWN_AFFILIATION_HISTORY)` per
  match. Runs **regardless of whether that affiliation is also an undisclosed `Finding`**
  — that is the both-at-once case, and it is deliberately two artifacts. Returns the tie
  keyed to its source `DiscoveredAffiliation` so `reconcile_case` can set
  `related_finding_id` (below).
- `reconcile.py`: `reconcile` (the `Finding` path) is refactored so the mapping from each
  `DiscoveredAffiliation` to the `finding_id` it produced (if any) is available to the
  caller — a `{(source, institution_name): finding_id}` dict is sufficient, since
  `_aggregate_own_affiliations` yields one `DiscoveredAffiliation` per institution within a
  run. `reconcile_ownership` deleted; `build_finding`'s
  `concern_list_evidence` / `ownership_evidence` kwargs deleted; `_OWNERSHIP_SOURCES` and
  the `gleif_ownership` branch in `_source_covers` deleted (pushback I).

### 4.4 `pipeline.reconcile_case`

Returns `tuple[ReconciliationManifest, list[Finding], list[ConcernTie]]` (was a 2-tuple).
Orchestration: run `reconcile` (findings + the `DiscoveredAffiliation→finding_id` map),
run `tie_from_ownership` and `ties_from_own_affiliations`, then stamp each
`OWN_AFFILIATION_HISTORY` tie's `related_finding_id` from that map (ownership ties get
`None`). Persists ties via a new `case_store.replace_ties(conn, case_id, ties)`
(current-state per case, same as `replace_findings`; findings and ties are written in one
connection scope so their `related_finding_id` links are always consistent).
`ReconciliationManifest` gains `tie_count`. The `demo` path passes the bundled DoD 1260H
file so `ties_from_own_affiliations` has a list to screen against (it already loads it for
the ownership path).

### 4.5 Storage (`common/storage.py`, `case/store.py`)

- New tables, additive (`CREATE TABLE IF NOT EXISTS`):
  - `concern_ties` — `tie_id, case_id, run_id, tie_kind, anchor_affiliation_id,
    related_finding_id, concern_entity_name, country, country_on_adversary_list,
    adversary_list_version, first_observed, last_observed, record_count,
    concern_list_evidence JSON, ownership_evidence JSON`. Current-state per case:
    `replace_ties` deletes `WHERE case_id = ?` then inserts.
  - `tie_actions` — mirrors `worksheet_actions` (`tie_id, case_id, action, reason_code,
    reason_note, actor, recorded_at, batch_id`). Append-only; latest per `tie_id` is
    effective.
  - `demo_meta` — `key VARCHAR, value VARCHAR` (one row: `fixture_version`).
- `findings` loses two columns: handled by explicit-column `INSERT (col, …) VALUES` and a
  narrowed `SELECT` in `load_findings` — no `ALTER` needed; the two legacy columns on a
  pre-existing DB sit unused (only the deployed demo). Optional `ALTER TABLE findings DROP
  COLUMN IF EXISTS …` in `connect()` **iff** the installed DuckDB supports that exact
  syntax (verify at implementation time — same discipline as `graph.py`'s CTE note).
- `case/store.py` gains `_tie_to_dict`/`_tie_from_dict`, `replace_ties`, `load_ties`,
  `append_tie_action`, `load_tie_actions`, `effective_tie_actions`.

### 4.6 Migration — the deployed demo case (pushback E)

`entity_screening/case/demo.py` gains `DEMO_FIXTURE_VERSION = 2`.
`_ensure_demo_case_exists` (in `api/case_routes.py`):

```
stored = store.demo_meta_get(conn, "fixture_version")
if demo.demo_case_exists(conn) and stored == str(demo.DEMO_FIXTURE_VERSION):
    return
# else: wipe the demo case's rows from every case table, rebuild, re-reconcile,
#       and store.demo_meta_set(conn, "fixture_version", DEMO_FIXTURE_VERSION)
```

So the first request after this deploys rebuilds the demo case cleanly: the stale ownership
`Finding` is gone, two `Finding`s (undisclosed BIT, Zhejiang) and **exactly one**
`ConcernTie` (`DECLARED_EMPLOYER_ULTIMATE_PARENT`, AVIC) are written. Verified against the
bundled DoD 1260H list: none of the demo's own declared/discovered affiliations (BIT,
Zhejiang University, Nanjing University, UT Austin) match it at the 0.90 concern threshold
(best is BIT vs "Beijing Meiya Hongshu Technology" at 0.73), so `ties_from_own_affiliations`
adds nothing to the demo — a clean one-tie demonstration. No manual step.

### 4.7 Closure rule (`case/service.py`)

`WorksheetView` gains `tie_rows: tuple[TieRow, ...]`; `unactioned_count` and `can_close`
account for **both** finding rows and tie rows. `service.transition()` — the existing
enforcement point for WORKSHEET→ADJUDICATION (`service.py:163`) — is unchanged in
structure; it already calls `worksheet()` and checks `can_close`. New
`record_tie_action` / `record_bulk_tie_action` mirror the finding versions, validating
`tie_id` against `load_ties`.

### 4.8 API (`api/case_routes.py`)

- `GET /cases/{id}/worksheet` payload gains `tie_rows` alongside `rows`, and
  `unactioned_count` / `can_close` cover both.
- `POST /cases/{id}/ties/{tie_id}/action` and `POST /cases/{id}/ties/actions` (bulk),
  gated, mirroring the finding action routes.
- `GET /cases/reason-codes` gains `tie_dismiss` / `tie_escalation`.
- `GET /cases/dismissal-basis-summary` splits its aggregation by observation kind
  (`finding` vs `tie`), both from their own vocabularies.
- `reconcile` route response gains `tie_count`.

### 4.9 UI (`app.py`)

Two stacked sections under one closure indicator:

- **"Discrepancies — undisclosed items"**: the existing `Finding` table (minus the concern
  columns), its single + bulk disposition tabs, its dismiss/escalation vocabularies.
- **"Concern ties"**: a `ConcernTie` table — anchor (the declared affiliation it runs
  from, or "—"), tie kind, concern entity, list + confidence, a one-line traversal
  summary, country / adversary-list status ("not yet checked" when null) — with its own
  single + bulk disposition and the *tie* vocabularies.
- A combined closure indicator: "*N of M discrepancy rows and P of Q concern-tie rows have
  an analyst action. The case can close when all do.*"
- **Grouping is a join on `related_finding_id`**, not a name match: a `ConcernTie` whose
  `related_finding_id` is set renders a "same affiliation also flagged as an omission —
  row <id>" note (and the paired `Finding` row gets the reciprocal), so the analyst sees
  that dismissing the omission does not dispose of the tie. Nothing in the presentation
  layer compares institution names.

### 4.10 Export (`case/export.py`)

- JSON payload gains top-level `"concern_ties": [...]` and `"tie_actions"` (effective +
  history). (JSON object key order is not semantically meaningful to consumers — no
  ordering guarantee is made or needed there.)
- XLSX: a **"Concern ties"** sheet immediately after "Case" and **before** "Findings",
  plus a "Tie actions" sheet. Every sheet — including the existing Adjudications /
  Certifications — is built with an explicit `columns=` list so headers render even with
  zero rows (the second "also fix" item): a reader can tell "none recorded" from "not
  implemented".
- The `PROVENANCE_NOTICE` already describes fabricated ownership chains; it now literally
  applies to the `concern_ties` section. No text change required, but the notice is
  re-read to confirm it reads correctly for a tie that is *not* ownership-derived.

### 4.11 The both-at-once case — argued

**Two artifacts.** A discovered affiliation that is both undisclosed *and* matches a concern
list (exercised by a test fixture -- see pushback C for why not the live demo) produces a
`Finding` (`ABSENT_FROM_IN_SCOPE_SOURCE` or `ABSENT_OUTSIDE_ALL_SOURCE_SCOPES`) **and** a
`ConcernTie` (`OWN_AFFILIATION_HISTORY`). Reasons:

- **Different statutory questions.** The `Finding` feeds the §51B.153 omission bar; the
  `ConcernTie` feeds the §51B.151(b) background check. Collapsing them forces one
  disposition to stand for two decisions.
- **Different triage.** An analyst may reasonably dismiss the omission
  (`analyst_judgment_not_material` — a 2013 postdoc is not a substantial omission) while
  escalating the tie (`needs_counterintelligence_referral` — a tie to a Seven Sons
  university touching the requested access scope is serious regardless of disclosure).
- **The closure rule then requires both to be actioned** — correct: dismissing the
  omission does not dispose of the tie.
- **The analyst still sees the connection** via `ConcernTie.related_finding_id` — a join
  key set at creation because the tie is derived from the same `DiscoveredAffiliation`
  that produced the finding (§4.1). "Two artifacts" does not mean "two disconnected rows",
  and the pairing is a fact, not a presentation-layer name match.

---

## 5. Binding acceptance criteria

1. `ConcernTie` and every type in its graph match a frozen per-type allowlist
   (`_OBSERVATION_GRAPH_ALLOWED_FIELDS`); `cli.py validate` fails CI on any field not on
   it, and on any field name containing a forbidden token — the set now also rejects the
   §51B.151(b) conclusion words. `ConcernTie` has **no** `disposition` field; the human
   action is a `TieAction`.
2. `MatchStatus` stays single-member (`test_cli_validate` unchanged). Tie evidence keeps
   `CANDIDATE_MATCH`.
3. `Finding` no longer carries `concern_list_evidence` / `ownership_evidence`; the removal
   is a deliberate edit to `_OBSERVATION_GRAPH_ALLOWED_FIELDS["Finding"]` in the same
   commit, and no code path references either field afterward (grep-clean).
4. The ownership-parent-on-a-concern-list observation is a `ConcernTie`
   (`tie_kind=DECLARED_EMPLOYER_ULTIMATE_PARENT`), never a `Finding`. It is emitted
   whether or not the parent is itself declared.
5. A subject's own discovered affiliation that matches a concern list produces a
   `ConcernTie` (`OWN_AFFILIATION_HISTORY`) **in addition to** any `Finding` for the same
   affiliation — the both-at-once case, two artifacts (§4.11). The tie's
   `related_finding_id` is set to that `Finding`'s id (a join key stamped at creation);
   an ownership tie's `related_finding_id` is `None`. No code path pairs a tie and a
   finding by comparing institution names.
6. `ConcernTie` reason codes are their own controlled vocabulary; `outside_declaration_scope`
   is not among them; `record_tie_action` rejects an off-vocabulary code.
7. Closure rule: a case cannot leave `WORKSHEET` while **any `Finding` or any `ConcernTie`**
   lacks an effective action. Enforced in `service.transition()`; `WorksheetView.can_close`
   / `unactioned_count` account for both.
8. Every `ConcernTie`'s `concern_list_evidence` (and `ownership_evidence` where present)
   carries `source_attribution` with `attribution` + `license` populated, through to the
   investigative-file export — the AC-14 guarantee, extended to the new section.
9. The exported investigative file carries the synthetic `provenance` block (unchanged)
   and a `concern_ties` section; the XLSX "Concern ties" sheet is ordered before
   "Findings", and every XLSX sheet renders its header row even with zero data.
10. `ScreeningHit.entity_id` on a `ConcernTie`'s inlined evidence is the subject-side
    `affiliation_id` (a stable id), not an entity name.
11. The deployed demo case self-heals across this schema change via `DEMO_FIXTURE_VERSION`
    — the first request after deploy rebuilds it; no manual reconcile step.
12. Corpus parity: `POST /runs` still returns `entities_count==2, hits_count==1` (the
    `docker` CI job's assertion). `pytest -q` + `cli validate` green at every commit
    boundary.

---

## 6. Tests

- **`tests/test_finding_contract.py`** — extend the parametrized allowlist / forbidden-token
  checks to cover `ConcernTie` and its graph; add a case asserting a `would_prevent`-style
  field would fail.
- **`tests/test_reconciliation.py`** —
  - `tie_from_ownership` produces a `ConcernTie`, not a `Finding`, for the demo GLEIF chain;
    `tie_kind`, `concern_entity_name`, evidence + attribution asserted.
  - it emits the tie even when the parent is also a declared affiliation.
  - `ties_from_own_affiliations` produces a `ConcernTie` for a fixture affiliation matching
    the bundled 1260H list.
  - both-at-once: one fixture affiliation, undisclosed *and* 1260H-listed → exactly one
    `Finding` and exactly one `ConcernTie`, with `tie.related_finding_id == finding.finding_id`
    (a join, asserted directly — no name comparison anywhere in the test either).
  - an ownership tie's `related_finding_id` is `None`.
  - `reconcile` (the `Finding` path) never sets concern/ownership evidence and never sees a
    `gleif_ownership` item.
- **`tests/test_case_lifecycle.py`** — closure rule blocks WORKSHEET→ADJUDICATION while a
  `ConcernTie` is unactioned even if every `Finding` is actioned; bulk tie action with one
  `batch_id`; `record_tie_action` off-vocabulary rejection.
- **`tests/test_case_store.py`** — `concern_ties` / `tie_actions` round-trip;
  `replace_ties` is current-state; `load_findings` reads a `findings` row that still has
  the two legacy columns (simulate a pre-migration DB) without error.
- **`tests/test_output_contract.py`** — the investigative-file test asserts the
  `concern_ties` section is present, every tie evidence payload carries attribution +
  licence, no evaluative key anywhere in the `ConcernTie` graph as serialized, the XLSX
  "Concern ties" sheet sits before "Findings", and the Adjudications / Certifications /
  Concern-ties XLSX sheets have header rows with zero data.
- **`tests/test_demo_case.py`** — the demo worksheet now shows N finding rows + ≥1 tie row;
  the AVIC observation is a tie, not a finding; `can_close` is false until both lists are
  actioned; a `DEMO_FIXTURE_VERSION` bump forces a rebuild (simulate a stale v1 demo case,
  assert it is replaced).
- **`tests/test_api_case.py`** — `GET /worksheet` returns `tie_rows`; the tie action routes
  gate and record; `/cases/reason-codes` returns the tie vocabularies;
  `/cases/dismissal-basis-summary` splits by observation kind.
- **Migration test** — build a case with the *old* `Finding` shape persisted (2 legacy
  columns populated), run the new `load_findings`, assert it returns clean `Finding`
  objects and a subsequent `reconcile_case` writes the new shape.

---

## 7. Out of scope for this pass

- **The `CO_AUTHOR_INSTITUTION` tie kind** (`cross_check_bibliometric`'s shape) — a
  co-author's institution matching a concern list. Follow-on; the `TieKind` enum leaves
  room.
- **OpenSanctions in the case discovery path** — stays optional / omitted for the demo
  (the ~450 MB file). `ties_from_own_affiliations` screens against the bundled DoD 1260H
  list only for now.
- **The foreign-adversary-country list** (§12 step 4) — `country_on_adversary_list` stays
  `None`; the tie UI shows "adversary-list check not yet run", never "clear".
- **`Adjudication` / outcome changes** — an adjudication already spans the whole case;
  nothing about ties changes its shape.
- **Queue-ordering / materiality configuration** — still not built; `ConcernTie` carries
  no ordering field.

---

## 8. Spec changes — land before code, in their own commit

Pushback A's verification (pull and quote §51B.151(b) from the enrolled text) is a
prerequisite for the §1 and §7 edits. If a web-enabled step confirms the text, this commit
proceeds; if it materially differs, the §7 mapping and the type's framing are revised
first.

- **§1** — add §51B.151(b) as a fourth quoted provision; *"Three provisions"* → *"Four"*.
- **§1.1** — a fifth consequence: §51B.151(b) is a *separate* test from the §51B.153
  omission bar; the two produce two artifacts.
- **§4** — the "ownership relationship" and "name match against a concern list" bullets no
  longer say "(existing Epic C/D machinery, unchanged)"; they feed a **concern-tie
  observation**, a distinct artifact. Add to "may not assert, ever": *that a tie would or
  would not prevent the person from maintaining the security or integrity of the research*
  (§51B.151(b)'s "would prevent" clause is the analyst's).
- **§5** — Discovery leaves when reconciliation has produced *findings and concern ties*;
  the closure rule covers *every finding and every tie*.
- **§7** — a column or note mapping each discovery source to the statutory limb it serves:
  OpenAlex → §51B.153 (omission) and, on a concern match, §51B.151(b) (tie); GLEIF
  ownership → §51B.151(b) only (never an omission); concern lists → §51B.151(b).
- **§8** — "one row per finding" → "one row per finding *or concern tie*"; two worksheet
  sections, two vocabularies, one closure rule over both; bulk action load-bearing for
  findings, a convenience for ties.
- **§10** — the demo narrative: the AVIC observation is a **concern tie**, not a finding;
  the demo produces 2 findings (undisclosed BIT, Zhejiang) + exactly 1 concern tie (AVIC
  ultimate parent). The both-at-once case (an affiliation both undisclosed and
  concern-listed) is noted as covered by a test fixture, not the live demo, because the
  Seven Sons universities are in OpenSanctions (omitted from the demo), not the bundled
  1260H list.
- **`requirements.md` §9c** — the "ownership graph finally earns its place" bullet: it
  produces "the *concern-tie* shape this use case most needs", not "the finding shape".
  Small edit.

---

## 9. Verification

- `pytest -q` + `python -m entity_screening.cli validate` green.
- `uvicorn … & streamlit run app.py` → demo case worksheet shows two sections; the AVIC
  observation is under "Concern ties"; close is blocked until both lists are actioned;
  dismiss a tie with a tie-vocabulary reason; export the investigative file and confirm the
  XLSX "Concern ties" sheet sits before "Findings".
- `GET /cases/dismissal-basis-summary` after dismissing one finding and one tie → two
  aggregations, each from its own vocabulary.
- Corpus parity: `POST /runs` with the committed fixtures still returns
  `entities_count==2, hits_count==1`; the `docker` CI job passes.
- Simulate the deployed instance: build a v1-shape demo case (ownership row in `findings`,
  `demo_meta` absent), bump `DEMO_FIXTURE_VERSION`, hit `/cases/demo/worksheet`, assert
  the ownership row is gone from `findings` and present as a `ConcernTie`.
- Grep: no remaining reference to `Finding.concern_list_evidence` /
  `Finding.ownership_evidence` / `reconcile_ownership` / `OwnershipDiscovery`.

---

## 10. Commit sequence

**Pre — spec + plan (pushed before any implementation):**
- **P1** — this plan → `docs/plans/2026-09-06-concern-ties-as-a-distinct-observation.md`
  + `docs/plans/README.md` index row ("Plan, not yet built").
- **P2** — §8's spec edits, quoting §51B.151(b) per the operative text the user confirmed
  on review (pushback A — no longer blocking).

**Implementation:**
- **C1** — `ConcernTie` + `TieKind` in `schema.py`; `_OBSERVATION_GRAPH_ALLOWED_FIELDS`
  (renamed) covering it; `cli.py validate` extended; forbidden-token additions. `Finding`
  loses the two evidence fields (deliberate allowlist edit). New `concern_ties` /
  `tie_actions` / `demo_meta` tables. `case/store.py` marshalling. No behavior yet;
  `load_findings` narrowed + explicit-column INSERT.
- **C2** — `tie_from_ownership` (replaces `discover_from_ownership` + `reconcile_ownership`),
  `ScreeningHit.entity_id` fix, drop the "parent already declared" skip and
  `_OWNERSHIP_SOURCES`. `pipeline.reconcile_case` returns the 3-tuple, persists ties,
  manifest `tie_count`.
- **C3** — `ties_from_own_affiliations` (concern-screen the subject's own discovered
  affiliations against the bundled 1260H list); `reconcile` exposes the
  `DiscoveredAffiliation→finding_id` map; `reconcile_case` stamps each own-affiliation
  tie's `related_finding_id` (the both-at-once join).
- **C4** — `case/service.py`: tie actions, bulk tie action, `WorksheetView.tie_rows`,
  closure rule over both; `case/vocab.py` tie vocabularies.
- **C5** — `case/export.py`: `concern_ties` + `tie_actions` payload, XLSX
  "Concern ties" + "Tie actions" sheets, explicit `columns=` on every sheet (fixes the
  empty Adjudications/Certifications sheets).
- **C6** — API: `tie_rows` in the worksheet payload, tie action routes, reason-codes and
  dismissal-basis-summary split by kind; `_ensure_demo_case_exists` `DEMO_FIXTURE_VERSION`
  rebuild.
- **C7** — `app.py`: the two-section worksheet, combined closure indicator, and the
  `related_finding_id` join surfaced on both rows (no name matching in the UI).
- **C8** — `tests/test_demo_case.py` refresh, docs sweep (`architecture.md`,
  `methodology.md`, `data_sources.md`, `plans/README.md` → Built), and the migration test.

Every commit: `pytest -q` + `cli validate` green; corpus `docker` assertion green; the
`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` trailer.
