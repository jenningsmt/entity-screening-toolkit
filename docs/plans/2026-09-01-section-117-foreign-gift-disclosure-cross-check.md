# V2 — Section 117 Foreign Gift & Contract Disclosure Cross-Check

## Context

This is the last piece of "V2" per `docs/requirements.md` Section 12's roadmap
sentence ("Add GLEIF ownership graph (Epic C) + Section 117 foreign-funding
cross-check + foreign-control flagging") — Epic C and foreign-control flagging are
already built. Unlike Epic C, Section 117 has no dedicated Epic letter in Section 6;
it's named only in the roadmap line and the Section 5 data-source table ("Foreign
funding disclosure records... Self-reported; coverage gaps possible"), so this plan
has to establish its own acceptance criteria rather than quote existing ones.

I downloaded and inspected the real bulk data file before designing anything, same
discipline as GLEIF — and it changed the design meaningfully from what the roadmap
sentence alone suggests.

### What's actually in the real data

Downloaded `Sec117PublicRecordsCompleteFeb2025.xlsx` (the legacy bulk-download file,
`fsapartners.ed.gov` — real direct link, confirmed working): **117,152 rows, 18
columns, ~9.3MB.** This is NSF/OpenSanctions-scale, not GLEIF-scale — no bulk-SQL
treatment needed; the standard `BaseIngester`/`SourceRecord` pattern fits directly.

Real columns: `OPEID`, `School Name`, `State`, `Transaction Type` (`Gift` /
`Contract` / `Restricted Gift` / `Restricted Contract` / `Real Estate`), `Foreign
Government Source` (a **Yes/No boolean**, not a name — this surprised me), `Attribution
Country`, `Amount`, `Receipt Date`, `Contract Start/End Date`, `Restricted Transaction
Foreign Government Legal Name`, `Restricted Transaction Foreign Government Name`,
`Restricted Transaction Description`, `Institution Owned by Foreign Source`, `Foreign
Source Owner Name`, `Foreign Source Ownership Date`, `Changes Due to Foreign Source
Owner`, `Legacy`.

**The decisive finding: only ~5,571 of 117,152 rows (4.75%) name a specific foreign
entity at all.** Those are the `Restricted Contract`/`Restricted Gift` rows with
`Restricted Transaction Foreign Government Legal Name` populated (real examples:
"SAUDI ARABIA CULTURAL MISSION", "ABU DHABI INVESTMENT AUTHORITY", "UNITED ARAB
EMIRATES EMBASSY") — genuinely useful, named, embassy/cultural-mission/sovereign-fund
entities, exactly the kind of thing worth cross-referencing. The other ~95% of rows
(regular `Gift`/`Contract` transactions) report only `Attribution Country` — no
entity name exists to fuzzy-match against anything. A separate, much rarer
disclosure type (`Foreign Source Owner Name`, only 5 rows in this file — whether the
*institution itself* is foreign-owned) also names an entity and is folded into the
same "any named foreign entity, whichever column it's in" handling rather than built
as a separate feature, given how rare it is.

This means the cross-check is correctly scoped as "search the ~5% of disclosures that
name a specific entity," not "search all 117K disclosures" — a much smaller, more
precisely targeted problem than the roadmap sentence implies on its own, and a good
match for the user's framing: this is fundamentally a fuzzy-matching problem against
messy self-reported text, not a new architecture problem.

**Known gap, stated plainly:** the Section 117 portal relaunched in January/February
2026 with, per ED's own press release, "11 additional data elements." The dashboard
at `foreignfundinghighered.gov` is a JS-rendered SPA I couldn't access with this
session's tools (no headless browser available), so I verified against the legacy
bulk file, not whatever the current post-relaunch download looks like. **Re-verify
the current download URL and schema at implementation time** — same category of
caution as GLEIF's CSV-vs-XML trap, flagged now rather than assumed away.

### Real-data verification: the four concerns raised in review

Before finalizing this plan, four things were checked directly against the real
117,152-row file (and, for the institution-matching question, real NSF award data
pulled live from `api.nsf.gov` — the correct current endpoint, not
`api.research.gov/common/webapi/...` which the existing `ingestion/nsf.py` currently
points at and which no longer resolves at all; **that's a separate, pre-existing bug
this investigation surfaced, not part of Section 117's scope, worth its own follow-up
fix**). All four surfaced real, concrete findings, not false alarms:

**1. Institution-name matching (the concern I'd have trusted least too) — confirmed
real, and fixable.** `School Name` in Section 117 uses each institution's common name
("University of Idaho", "Boston University", "University of Central Florida"). Real
NSF `awardeeName` values for the *same real institutions*, pulled live, are frequently
the legal/governing-board name instead: "Regents of the University of Idaho",
"Trustees of Boston University", "The University of Central Florida Board of
Trustees". Run through the actual `resolution/matcher.py:score_pair` and
`resolution/normalize.py:normalize_for_matching` as they exist today, these real pairs
scored **0.72, 0.74, 0.73** respectively — below even the standard 0.80 threshold, let
alone a 0.90 institution threshold — and landed in **different** 3-character blocks in
every case (`uni` vs `reg`, `bos` vs `tru`, `uni` vs `the`), confirming the exact
failure mode raised: this isn't "scores low," it's "never reaches the scorer at all"
under the existing blocking scheme.

The fix: a new, narrowly-scoped `strip_institutional_governance_affix()` function
(see New/changed files) that strips leading `Regents of (the)`, `Board of Regents
(of)`, `Trustees of`, `The`, and trailing `Board of Trustees`, `(The)` before the
institution-match stage only. Re-tested against the same real pairs plus two more
(Michigan-Ann Arbor, a "(The)" suffix variant), **5 of 6 real pairs went to a clean
1.0 in the same block** after stripping. The one that didn't — "University of Nevada
, Reno" vs "Board of Regents, NSHE, obo University of Nevada, Reno" (a
system-consortium "obo" naming style with an acronym embedded mid-string) — scored
0.85 and stayed in a different block even after stripping. That residual case is a
real, honestly-documented gap, not chased further with more special-casing (see
Explicitly out of scope) — proportional to how rare that specific naming pattern is,
same judgment already applied to the acronym-matching limitation documented in
`docs/methodology.md`.

**2. Confidence-collapse — resolved by the same fix.** With
`strip_institutional_governance_affix()` in place, real institution matches cluster
tightly at 0.97–1.0 (exact matches at 1.0; a real "MD" vs "M.D." punctuation variant
at 0.967), not near a loose threshold edge. That's exactly the condition under which
demoting institution-match confidence to `evidence` context (rather than blending it
into `ScreeningHit.confidence`) is justified — the plan's original design was correct,
but only *because* of this fix; without it, the institution threshold would have had
to drop low enough (~0.65–0.70) to catch legal-name variants, and at that point a
single funder-only confidence number really would overstate the weaker link, exactly
as raised in review. Keeping `institution_threshold` at 0.90 is now justified by real
data rather than assumed.

**3. Legal-name/government-name co-occurrence — confirmed common, and the plan's
extract logic was solving the wrong problem.** Of the 5,576 real rows naming any
foreign entity, **5,569 (99.9%) have *both* `...Foreign Government Legal Name` and
`...Foreign Government Name` populated** — this is the dominant case, not a rare edge.
But inspecting the actual pairs shows they are not two competing aliases for the same
entity: `Legal Name` is consistently the specific entity ("Kuwait Embassy", "Saudi
Arabia Cultural Mission", "Abu Dhabi Investment Authority") while `Government Name` is
consistently just the country/government-level name ("Kuwait", "Saudi Arabia", "United
Arab Emirates"). Confirmed further: `Government Name` populated *without* `Legal Name`
occurs in **zero** real rows; `Legal Name` without `Government Name` occurs in only 2.
So the original "first-non-null-wins across three plausible aliases, second is a
discarded alias" framing was wrong — `Government Name` is not an alternate name worth
independently fuzzy-matching against a concern list at all (a bare country name
matching an entity list is a different, much weaker, and mostly meaningless signal).
`extract_named_foreign_entity` needs to change from "alias precedence" to "`Legal
Name` is the entity when present (essentially always is, when any is); `Government
Name` is government/country-level context surfaced in `evidence`, never itself passed
to stage-2 matching; `Owner Name` handles the structurally distinct foreign-ownership
disclosure type." Same function signature, corrected semantics — no discarded-alias
risk after all, because there was never a second real alias to discard.

**4. Exact-duplicate rows — confirmed real and substantial: ~11% of all rows.**
5,493 distinct row-tuples repeat in the file, totaling 12,856 of 117,152 rows (~11%)
involved in exact duplication — e.g. the identical `(Arizona State University,
Contract, Saudi Arabia, $20,952, same three dates)` row appears 45 times. There's no
natural per-transaction key in the file, and repeated identical amounts plausibly
represent genuinely separate recurring disclosures (not just file artifacts), so a
pure content hash for `source_record_id` would silently collapse many real, distinct
rows into one in `raw_section_117` — confirmed as a real risk, same discipline as the
DoD 1260H curation note's explicit deduplication concern. Fix: `source_record_id` is a
hash of the row's content **plus its ordinal position in the source file**, so every
row gets a unique ID regardless of content collisions, and nothing is silently
dropped.

## Architecture: reuses Epic D's screening infrastructure, not Epic C's pattern

Unlike GLEIF (a shared reference dataset needing its own ingestion model, storage
tables, and manifest), Section 117 fits the **existing** per-run ingestion model
exactly like NSF/OpenSanctions/1260H: modest scale, ingested fresh each run, no
decoupled "enrich" step needed. And unlike Epic C (which needed new schema types —
`OwnershipMatch`, `ForeignControlFlag` — because "parent jurisdiction differs" isn't
representable as a `ScreeningHit`), a Section 117 cross-check hit *is* structurally
identical to any other screening hit: an entity's name (here, indirectly — the
*disclosed funder's* name) matched something on a registered concern list. So:

- **No new schema types.** Cross-check hits are ordinary `ScreeningHit`s tagged
  `list_name="section_117_foreign_funding_disclosure"`.
- **No new storage tables.** Raw records go into a new `raw_section_117` table via
  the *already-generic* `storage.insert_source_records()`; hits go into the
  *already-generic* `screening_hits` table via `storage.insert_screening_hits()`.
- **No new manifest type.** One more `DatasetSnapshot` in the existing `RunManifest`,
  written by `run_screening()` itself — this is NOT a separate `enrich_*` step.
- **No scoring changes.** A Section 117 hit is scored by the existing
  `screening_hit_weight`/`multiple_list_hit_bonus` rubric factors, unmodified — an
  entity independently flagged by both, say, OpenSanctions *and* a Section 117
  disclosure correctly earns the existing multi-list bonus for free.

The one genuinely new piece of logic is the cross-check itself, which chains **two**
fuzzy matches using the **existing** `resolution/matcher.py:score_pair()` both times
— reused exactly as instructed, not reimplemented:

1. Block + score Section 117 rows against the resolved entity's `canonical_name` on
   **`School Name`**, after applying a new, narrowly-scoped
   `strip_institutional_governance_affix()` normalization step (institution-name
   match — is this disclosure even about the entity being screened?). Verified
   against real data (see Context) that this step is what makes a legal/
   governing-board-style name from NSF (e.g. "Regents of the University of Idaho")
   actually reach and clear a 0.90 threshold against Section 117's common-name style
   ("University of Idaho") — without it, real matches score 0.72–0.81 and land in a
   different block entirely.
2. For rows clearing that threshold *and* carrying a named foreign entity (the ~5%,
   from `extract_named_foreign_entity` — see below), block + score that entity name
   against the **registered concern lists** (`screening/lists.py` — OpenSanctions,
   DoD 1260H) exactly the way `screen_entity()` already does it (funder-name match —
   is the disclosed funder itself a concern?).

Only rows clearing *both* thresholds produce a hit. The schema-discipline principle
already applied to `ScreeningHit.evidence` and `ForeignControlFlag.evidence` applies
here too: the institution-match confidence, the funder-match confidence, the
`Restricted Transaction Foreign Government Name` (country/government-level context —
see below, never itself used as a match candidate), and the underlying disclosure
fields (transaction type, country, amount, date, `source_record_id`) all go into
`evidence`, self-contained, not just the single `confidence` number (which is the
funder-match confidence — the institution match is what determined *whether* this row
applies to this entity at all, so it's context, not the headline score). This
funder-only-confidence design is verified sound against real data, not assumed: with
the governance-affix fix in place, real institution matches cluster at 0.97–1.0, not
near the threshold edge, so they're uniform enough to safely demote to context (see
Context's concern-2 finding — without the affix fix this would not have held).

**`extract_named_foreign_entity` semantics, corrected against real data:** not an
"alias precedence" pick among three interchangeable candidates as originally framed.
Real data shows `Restricted Transaction Foreign Government Legal Name` is populated in
5,571 of 5,576 real named rows and is consistently the specific entity ("Kuwait
Embassy"), while `...Foreign Government Name` is consistently just the
country/government name ("Kuwait") and is never populated on its own — so it is
government-level context, not a second alias, and is never independently passed to
stage-2 matching (a bare country name against an entity concern list is a different,
near-meaningless signal). The function returns `Legal Name` when present, else
`Government Name` (the 2-row fallback case), else `Foreign Source Owner Name` (the
structurally distinct foreign-ownership-of-institution disclosure type, ~5 rows);
`Government Name` is still surfaced in `evidence` whenever populated, for context.

## New/changed files

- **`entity_screening/ingestion/section_117.py`** — `Section117Ingester(BaseIngester)`,
  same shape as `nsf.py`/`opensanctions.py`/`dod_1260h.py`. Reads the `.xlsx` via
  `openpyxl` (already a dependency, added earlier for Excel *export* — same library
  reads it too, no new dependency; header is row 2, not row 1 — row 1 is a merged
  title/description cell, confirmed against the real file). Yields one `SourceRecord`
  per row; `source_record_id` is a hash of the row's own values **plus its ordinal
  position in the file** — confirmed against real data that a pure content hash would
  collide: ~11% of real rows (12,856 of 117,152) are exact content duplicates of
  another row, plausibly genuine repeated disclosures (e.g. recurring gift amounts),
  not file artifacts, so they must not be silently deduplicated. Per-row
  `IngestionError` logging (NSF/OpenSanctions-style, not GLEIF's aggregate-count
  style — this scale doesn't need it) for rows missing `School Name` or `Transaction
  Type`.
- **`entity_screening/resolution/normalize.py`** — new
  `strip_institutional_governance_affix(name: str) -> str`, strips leading `Regents
  of (the)`, `Board of Regents (of)`, `Trustees of`, `The`, and trailing `Board of
  Trustees`, `(The)`. Deliberately **not** folded into the general
  `normalize_for_matching()` used by every other source — this is a higher-ed
  governance-naming pattern specific to matching NSF's legal-awardee-name convention
  against Section 117's common-name convention, with no evident reason to apply it to
  OpenSanctions/DoD-1260H/GLEIF company-name matching. Called only from
  `screening/section_117.py`'s institution-match stage, before `score_pair`.
- **`entity_screening/screening/section_117.py`** — the cross-check itself:
  - A small blocked index over Section 117 records by normalized (and
    governance-affix-stripped) `School Name` (same blocking philosophy as
    `screening/lists.py:EntityOfConcernList`, ~15 lines, written standalone rather
    than extracted into a shared helper — this is only the second use of the
    pattern, not a third, so a shared abstraction isn't clearly worth the
    indirection yet).
  - `extract_named_foreign_entity(record) -> str | None` — returns `Restricted
    Transaction Foreign Government Legal Name` when present (true for 5,571 of 5,576
    real named rows), else `...Foreign Government Name` (2-row real fallback), else
    `Foreign Source Owner Name` (the structurally distinct foreign-ownership
    disclosure type, ~5 real rows); `None` for the ~95% of rows with no named entity
    (nothing to cross-check for that row). Per the real-data finding above, this is
    not alias-precedence among interchangeable options — `Government Name` is
    government/country-level context, never itself an independent match candidate,
    but still carried into `evidence` whenever populated.
  - `cross_check_section_117(entity, section_117_records, concern_lists,
    institution_threshold, funder_threshold, block_size) -> Iterator[ScreeningHit]` —
    the two-stage match described above, reusing `resolution/matcher.py:score_pair`
    for both stages and `screening/lists.py`'s registered concern lists for stage 2.
- **`pipeline.py:run_screening()`** — one more optional ingestion call (Section 117,
  skipped entirely if no file is supplied — same "optional, no bundled fallback"
  posture as GLEIF), and the per-entity loop calls `cross_check_section_117(...)`
  alongside the existing `screen_entity(...)` call, merging both into the same `hits`
  list before scoring — Section 117 hits flow through every downstream stage
  (storage, scoring, export, API) as ordinary `ScreeningHit`s with no further changes
  needed there.
- **`common/storage.py`** — one more `CREATE TABLE IF NOT EXISTS raw_section_117`
  entry in `SCHEMA_DDL`, identical shape to the other three `raw_*` tables.

## CLI / API / UI surface

- CLI `run`: new optional `--section-117-file` (single file — unlike GLEIF's L1+L2
  pair, this is one `.xlsx`) and `--section-117-institution-threshold` (default
  **0.90**, deliberately higher than the standard 0.80 — misattributing a disclosure
  to the *wrong* school by a loose institution-name match is a worse failure mode
  than the standard screening threshold is tuned for, since it would misfile evidence
  under an unrelated entity, not just miss a real match). The funder-vs-concern-list
  stage reuses the existing `--threshold`, since that step *is* exactly what
  `screen_entity()` already does elsewhere in the same run.
- API: `RunRequest` gains optional `section_117_file` and
  `section_117_institution_threshold` fields, same "omit to skip" semantics as
  `dod_1260h_file`.
- `app.py`: one more optional sidebar file-path input, matching the GLEIF fields'
  presentation (blank = skip).

## Tests

- A tiny synthetic `.xlsx` fixture built to the *real* 18-column schema, header on
  row 2 (not CSV — the ingester reads `.xlsx`, so the fixture has to exercise that
  real code path, matching the real file's title-row-then-header-row layout): one
  `Restricted Contract` row with a named entity matching a concern-list fixture
  entity, one regular `Gift` row with only a country (must **not** produce a hit —
  proving the ~95% case is correctly excluded, not silently mismatched), one row
  whose `School Name` doesn't match any resolved entity (institution threshold not
  cleared), one `Foreign Source Owner Name` row (the rare foreign-ownership
  disclosure path), one row with both `Legal Name` and `Government Name` populated
  with different values (proving `Government Name` lands in `evidence` but is never
  itself matched against concern lists), and two exact-duplicate rows (proving
  `source_record_id` uniqueness via ordinal position, not just content).
- `resolution/normalize.py` unit tests for `strip_institutional_governance_affix()`
  against the real pairs found above (Idaho, Boston University, Central Florida,
  Michigan-Ann Arbor all → clean matches; the Nevada/NSHE "obo" case stays a
  documented miss, asserted as such rather than silently passing or being ignored).
- `tests/test_ingestion.py`-style additions for `Section117Ingester` (provenance
  tagging, malformed-row logging, header-row offset, duplicate-content row IDs).
- `tests/test_screening_section_117.py` for `extract_named_foreign_entity` and
  `cross_check_section_117` against the synthetic fixture.
- `tests/test_pipeline.py`-style addition: `run_screening` with a
  `--section-117-file` fixture produces the expected hit, tagged with the right
  `list_name`, and contributes to the score via the *existing* rubric factors
  (proving no scoring changes were actually needed, not just assumed).
- **Real-data verification** (same discipline as GLEIF's timing pass): run
  `Section117Ingester` against the actual current bulk file (re-verified/re-downloaded
  at implementation time per the portal-relaunch caveat above) end-to-end, and
  specifically check whether any of the real named entities (embassies, cultural
  missions, sovereign funds) already resolve against the real bundled DoD 1260H list
  or a real OpenSanctions pull — record whatever is actually found (including
  "nothing matched," which is itself a valid, worth-stating result) rather than
  assuming a hit exists to test against.

## Explicitly out of scope for this pass

The ~95% of disclosure rows with country-only attribution (no entity name — nothing
to fuzzy-match, so no hit-generation attempted for them; they're still ingested into
`raw_section_117` for potential future country-level analysis, just not part of this
cross-check). The residual system-consortium "obo" institution-naming gap found
during real-data verification (e.g. "Board of Regents, NSHE, obo University of
Nevada, Reno") is a documented known limitation, not chased with further
special-casing — proportional to how rare that specific naming pattern is, and
consistent with how the existing acronym-matching gap is already documented in
`docs/methodology.md` rather than solved outright; add a corresponding bullet there
during implementation. Fixing `ingestion/nsf.py`'s dead `api.research.gov` endpoint
(discovered during this investigation; the correct live endpoint is
`http://api.nsf.gov/services/v1/awards.json`) is a separate, pre-existing bug outside
Section 117's scope — worth flagging to the user as its own follow-up, not silently
bundled into this change. Re-verifying the post-January-2026 portal's exact current
schema is a prerequisite to trust at implementation time, not something resolved by
this plan. No UI beyond the existing evidence-trail display (Section 117 hits render
exactly like any other `ScreeningHit` already does — no new UI code needed at all).

## Verification

- `pytest -q` — full suite plus the new Section 117 test files.
- `python -m entity_screening.cli run --nsf-file ... --opensanctions-file ...` (no
  `--section-117-file`) — confirms existing behavior is completely unchanged when
  Section 117 is omitted.
- Same command **with** `--section-117-file` pointed at the synthetic fixture —
  confirms a hit appears tagged `section_117_foreign_funding_disclosure`, with both
  match confidences visible in `evidence`, and that the country-only row produces
  nothing.
- The real-data pass above, run once against the actual current bulk file before
  calling this done.
