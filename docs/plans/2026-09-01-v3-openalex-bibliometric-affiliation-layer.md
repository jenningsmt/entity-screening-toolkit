# V3 — OpenAlex Bibliometric Affiliation Layer (Epic E)

## Context

Per `docs/requirements.md` Section 12, "V3 — Bibliometric layer" is "Add OpenAlex
co-authorship/affiliation matching (Epic E) + the Seven Sons / BIS-listed-university
entity-of-concern seed... sequenced last deliberately... benefits from the groundwork
in V1/V2 being solid first" — which it now is. Epic J (LLM-grounded explanations) and
DuckDB VSS semantic-abstract matching are explicitly **out of scope for this plan**
(both deferred per discussion — see "Explicitly out of scope").

Before designing anything, I pulled real data from OpenAlex's live API and re-checked
the real OpenSanctions file already on disk from the Section 117 work — same
discipline as GLEIF and Section 117, and it changed the design meaningfully.

### Finding 1: the Seven Sons are already covered — no new list needed

Grepped the real, already-downloaded `targets.simple.csv` (455MB, ~1.22M rows, the
same file used for Section 117's real-data pass) for all seven "Seven Sons of
National Defence" universities (Beihang University, Beijing Institute of Technology,
Harbin Engineering University, Harbin Institute of Technology, Nanjing University of
Aeronautics and Astronautics, Nanjing University of Science and Technology,
Northwestern Polytechnical University). **All seven already exist as standalone,
well-aliased entries** (e.g. "BIT", "HIT", "NPU;NWPU"), several explicitly citing
"Section 1286" of the NDAA as their designation basis. `OpenSanctionsList` +
`screen_entity()` (built since V1) already catches these with **zero new code**, once
run against a real OpenSanctions download rather than the 3-row test fixture.

Per discussion: this plan adds a **known-important-entity regression test** (mirroring
`tests/fixtures/known_difficult_pairs.json`'s pattern) proving this against a small
fixture containing the seven real names/aliases, plus a documentation note — no new
`SevenSonsList` class or curated JSON file. Building one would duplicate coverage that
already exists — the mirror image of why DoD 1260H needed its own list (nothing else
carried it).

### Finding 2: OpenAlex's real API shape (verified live, not from docs)

`api.openalex.org` is a live JSON REST API — reachable, no API key required (verified
by both a real unauthenticated call succeeding and by fetching the authoritative
current docs directly, which contradicts a stale, incorrect forum claim that a key
became mandatory in February 2026). Free tier: 100,000 credits/day, 100 req/sec;
list/search requests cost 10 credits each, singleton lookups 1 credit — comfortably
sufficient for this project's "bounded set of PIs from NSF award data" scale (Section
8 already called for the targeted-API approach over the 660+GB full snapshot; this
confirms it's also operationally easy). Adding a `mailto` parameter is still
recommended for the "polite pool" (more consistent response times) — cheap to include,
no cost.

Real shapes confirmed via `GET /institutions?search=`, `GET /authors?search=`/`filter=`,
and `GET /works?filter=author.id:...`:
- **Institutions** carry `id` (OpenAlex ID), `ror` (a real external registry ID),
  `display_name`, `display_name_acronyms`, `display_name_alternatives` (including
  native-script names), `country_code`, and — genuinely useful, not something the docs
  led me to expect — `associated_institutions` with typed relationships (e.g.
  Beijing Institute of Technology's real record lists the Ministry of Industry and
  Information Technology as a `"relationship": "parent"` government affiliation).
  No bulk download needed: `/institutions?search=` does full-text ranking server-side
  across the whole ~110K-institution corpus in one call, unlike GLEIF's 3.4M-row bulk
  CSV — so institution resolution here is a live search-then-score call, not a
  bulk-load-then-block pattern.
- **Authors** carry `id`, `orcid` (nullable), `display_name`, `raw_author_names`
  (real alternate-spelling variants), and `affiliations` (a list of institutions with
  the specific `years` each was active) — directly queryable/filterable by
  `affiliations.institution.id`, letting a search be narrowed to "people named X who
  were ever affiliated with institution Y."
- **Works** carry an `authorships` array per work: each entry has `author.id`,
  `institutions` (that author's affiliation *for that specific paper*), `countries`,
  and `raw_affiliation_strings` (the original self-reported text before OpenAlex's own
  disambiguation) — this is the co-authorship graph and the affiliation-history-over-
  time data in one place; no separate call needed for either.

### Finding 3: author disambiguation is genuinely hard, confirmed with a real tied case

Searching for a real PI from an actual NSF award in this repo's own test data ("Andrew
Felton", Montana State University, FY2026) — first with a plain name search, then even
after narrowing server-side to authors ever affiliated with Montana State University's
exact OpenAlex institution ID — returns **three** distinct author records, not one.
Two of the three (`A5067979033` and `A5140693917`) share the **identical ORCID**
(`0000-0002-1533-6071`) — a real, confirmed OpenAlex data-quality issue (an unmerged
duplicate author record), not a hypothetical. The third (`A5110303932`, no ORCID) is a
plausibly-different "Andrew Felton" who also lists a 2026 Montana State University
affiliation. **Institution-filtering alone does not resolve this to one candidate** —
name similarity won't discriminate the ORCID-duplicate pair either, since both show
essentially the same display name.

This directly confirms Epic E's own acceptance criterion — "a documented disambiguation
confidence score, not an assumed 1:1 match" — is a real requirement, not boilerplate
caution: `disambiguate_pi_to_openalex_author` must be able to return **multiple** tied
`ResolvedAuthor` candidates when real data is genuinely ambiguous, with ORCID-sharing
treated as "same underlying identity, unmerged in OpenAlex" (surfaced in evidence) and
a distinct display name + institution overlap treated as a genuine open tie, not
silently collapsed to the top `relevance_score` result.

### Finding 4: PI names live in `raw_nsf_awards`, not on `ResolvedEntity`

Re-checked `pipeline.py:resolve_entities_from_nsf` and `common/storage.py`: NSF's raw
award record already carries `piFirstName`/`piLastName`/`piEmail`/`piId` (confirmed in
this project's own earlier real API pull), and the full raw award dict is preserved in
`raw_nsf_awards.raw` via the existing generic `insert_source_records`. But
`resolve_entities_from_nsf` groups only by *institution* name into `ResolvedEntity`,
and `storage.load_resolved_entities`'s own docstring is explicit that
`source_records` always comes back empty — PI-level detail is not persisted on the
entity at all. So bibliometric enrichment for a given `entity_id` needs to separately
query `raw_nsf_awards` for that run and re-derive the institution grouping using the
**exact same** normalization `resolve_entities_from_nsf` already uses
(`normalize_for_matching` + `uuid.uuid5(uuid.NAMESPACE_DNS, key)`), rather than
touching Epic B's existing resolution code at all.

## Architecture

Mirrors Epic C's shape (GLEIF), not Epic D/Section 117's: OpenAlex is a live external
reference source enriching an *already-existing* run, not a per-run ingestion source
fed into `run_screening` itself.

- **New package content in `entity_screening/bibliometric/`** (currently an empty
  stub, per `docs/architecture.md`):
  - `openalex_client.py` — thin HTTP client: `search_institutions(query)`,
    `search_authors(query, institution_openalex_id=None)`,
    `get_author_works(author_openalex_id)`. Plain `requests` calls (already a
    dependency) against `api.openalex.org`, with a `mailto` param for the polite
    pool. Each function accepts an injectable fetch callable, mirroring
    `ingestion/nsf.py:NSFAwardIngester`'s `fetch_page` pattern, so tests never hit
    the live network.
  - `institution_match.py` — `resolve_entity_to_openalex_institution(entity, ...)`:
    calls `search_institutions`, then scores each candidate's `display_name` +
    `display_name_acronyms` + `display_name_alternatives` via the **existing**
    `resolution/matcher.py:score_pair` (same reuse discipline as GLEIF/Section 117)
    — no bulk download or blocking needed, since OpenAlex's own search already
    ranks server-side across the full corpus.
  - `author_resolve.py` — `disambiguate_pi_to_openalex_author(pi_name, institution_openalex_id, ...)`:
    calls `search_authors` filtered by the resolved institution, groups results by
    ORCID (a shared ORCID = one identity, unmerged in OpenAlex — evidence notes
    this), then scores each remaining distinct identity's `display_name`/
    `raw_author_names` via `score_pair`. Returns a **list** of `ResolvedAuthor`
    candidates (every one clearing the threshold), not a forced single pick — real
    data shows genuine ties are the normal case here, not a rare edge.
  - `cross_check.py` — `cross_check_bibliometric(entity, resolved_authors, concern_lists, ...)`:
    for each `ResolvedAuthor`, walks `get_author_works` and checks (a) every
    co-author's own institution affiliations and (b) the author's own past
    affiliation history (from `author.affiliations`, not just this institution)
    against the **existing** registered concern lists (`screening/lists.py`) using
    the same `score_pair`-based matching `screen_entity` already does — producing
    ordinary `ScreeningHit`s, exactly like Section 117, tagged
    `list_name=<whichever concern list matched>`,
    `matched_field="bibliometric_co_author_institution"` or
    `"bibliometric_past_affiliation"`. **No new scoring changes** — these hits earn
    the existing `screening_hit_weight`/`multiple_list_hit_bonus` rubric factors for
    free, same finding as Section 117. Every hit's `evidence` inlines the
    `ResolvedAuthor` candidate's own tie context (OpenAlex author ID, confidence,
    tied-candidate count, shared ORCIDs if any) directly — never just a reference
    requiring a further join back to `openalex_author_matches` — see "Resolved
    during review" below.
- **New schema type**: `ResolvedAuthor` in `common/schema.py` — genuinely new
  (not representable as `ScreeningHit`), same reasoning as Epic C's `OwnershipMatch`:
  this is an identity-resolution result, not a concern-list match.
  `(entity_id, pi_name, openalex_author_id, display_name, confidence, match_basis,
  evidence, status=MatchStatus.CANDIDATE_MATCH)`. `evidence` carries the full
  candidate context (ORCID, other tied candidate IDs if any, institution/year
  overlap) so a tie is visible, not hidden.
- **New storage table**: `openalex_author_matches` — same "current-state,
  re-runnable" shape as `lei_matches` (delete-and-replace per `run_id` on
  re-enrichment), via new `insert_openalex_author_matches`/`load_openalex_author_matches`
  in `common/storage.py`. Bibliometric `ScreeningHit`s need **no new table** — they
  go into the existing `screening_hits` table exactly like every other hit.
- **New manifest type**: `BibliometricSnapshotManifest` in `common/manifest.py` —
  same durability rationale as `GleifSnapshotManifest` (a live/mutable-over-time
  external source; the run's own directory needs an immune-to-later-runs record of
  exactly what was queried and when). Records `run_id`, `queried_at`,
  `pi_count`, `resolved_author_count`, `openalex_api_base_url`. There's no
  "file" to name (unlike GLEIF's CSV paths) since this hits a live API — the
  manifest's job here is provenance of *when* against a continuously-updated
  source, mirroring `docs/methodology.md`'s reproducibility framing for exactly this
  kind of source.
- **`pipeline.py`**: new `enrich_bibliometric(run_id, *, contact_email=None,
  institution_threshold=..., author_threshold=..., db_path=..., runs_dir=...)`,
  structurally identical to `enrich_ownership`: loads the run's resolved entities,
  re-derives PI names per entity from `raw_nsf_awards` (Finding 4), resolves each
  entity to an OpenAlex institution, disambiguates each of that entity's PIs,
  cross-checks each resolved author, and persists `openalex_author_matches` +
  new `ScreeningHit`s into the existing `screening_hits` table. Keeps a per-run
  cache keyed on the *resolved OpenAlex institution ID* (not `entity_id`) so two
  spelling-variant `ResolvedEntity` rows that resolve to the same real institution
  share one author-resolution/cross-check pass instead of duplicating both the
  OpenAlex calls and the resulting hits — see "Resolved during review" below. Does
  **not** touch `scored_entities` — same rule as `enrich_ownership`; a caller calls
  `rescore_run` afterward. Writes the durable per-run `BibliometricSnapshotManifest`.

## Resolved during review — binding acceptance criteria

Three gaps raised on review, folded in now so they don't get lost between approval
and implementation (same discipline as the GLEIF plan's review cycle):

**1. Institution-resolution deduplication within a run.** `resolve_entities_from_nsf`
groups NSF records by *exact* normalized-name match, deliberately not fuzzy (its own
docstring says so) — so "Montana State University" and "Montana State
University-Bozeman" from two different award records can land as two separate
`ResolvedEntity` rows even though they're one real institution to OpenAlex. Run
naively, `resolve_entity_to_openalex_institution` and everything downstream of it
would resolve both independently: duplicated OpenAlex calls, and — worse — two
near-duplicate bibliometric `ScreeningHit`s under two different `entity_id`s for what
a reviewer would recognize as one institution. Fix: `enrich_bibliometric` keeps a
per-run cache keyed on the *resolved OpenAlex institution ID*, not the entity_id —
each distinct entity still gets its own institution-resolution attempt (so its own
confidence/evidence is recorded), but once two entities resolve to the same OpenAlex
institution ID, author-resolution and cross-check work for that institution's PIs runs
once and the result is shared across every entity that landed on it, rather than
repeated. This is invisible in a single-entity test fixture and only shows up once
real NSF data with real spelling variance runs through it — so the test suite needs a
fixture with two spelling-variant entities resolving to the same OpenAlex institution
ID, asserting the OpenAlex call only happens once (via the injectable fetch callable's
call count) and both entities' scored output reflects the shared result.

**2. Evidence must inline tie context, not leave it one join away.** This project
already has a codified acceptance bar for exactly this
(`test_evidence_is_self_contained_without_a_further_join`, added for Section 9a's
"evidence must work as LLM retrieval context without a further lookup," in
anticipation of Epic J). A `ScreeningHit` produced by walking one tied
`ResolvedAuthor` candidate's co-authorship graph must carry that candidate's tie
context directly in its own `evidence` — e.g. `"author_resolution": {"openalex_author_id":
"A5067979033", "confidence": 0.91, "tied_candidate_count": 2, "shared_orcid_with":
["A5140693917"]}` — not just a reference the reviewer has to separately join back to
`openalex_author_matches` to understand. Without this, an export or a future Epic J
explanation step would see a clean, single-source-looking hit that's actually resting
on a real, documented ambiguity one layer up — exactly the kind of false-confidence
gap Epic J's "never assert beyond what evidence supports" constraint exists to
prevent. `cross_check_bibliometric` copies the relevant fields from the
`ResolvedAuthor` it's walking into every hit's `evidence` it produces from that
candidate. Test: assert a bibliometric `ScreeningHit`'s evidence contains the tie
context with no further lookup required, mirroring the existing self-contained-
evidence test's shape.

**3. Document the Seven Sons coverage trade-off.** Choosing not to build a dedicated
`SevenSonsList` (Finding 1) trades away an independence property the curated-list
approach had: a static bundled file can't silently lose coverage, but reliance on
OpenSanctions' aggregation theoretically could if a future snapshot drops or
re-labels these designations. `docs/data_sources.md` gets one line stating this
plainly, next to the existing "self-reported, coverage gaps possible"-style caveats
already there for other sources — same "known limitation, stated plainly" discipline
already applied everywhere else in this project, not assumed away.

## Real-data verification still needed during implementation (binding, not optional)

Same discipline as Section 117's review cycle — these get checked with real data
before this is called done, and the plan may need a small adjustment based on what's
found, exactly like Section 117's confidence-collapse question:

1. **Does `ResolvedAuthor.confidence` (name-similarity only) cluster tightly enough to
   stand alone**, or does the compounded institution-resolution confidence need to
   factor into a bibliometric `ScreeningHit`'s headline confidence (the same question
   Section 117 had to answer empirically for its two-stage match, resolved by testing,
   not assumption)?
2. **How often do real PIs produce genuine multi-candidate ties** (beyond this plan's
   one confirmed example) — informs whether "return every candidate clearing
   threshold" produces a usable evidence trail or an unreadably noisy one at scale.
3. **Real precision check**: run this against a handful of real NSF PIs at
   institutions with genuine Seven-Sons-adjacent co-authorship (if any turn up) and
   record what's actually found, same as Section 117's real DoD 1260H/OpenSanctions
   pass — including "nothing found," which is itself a valid, worth-stating result.

## CLI / API / UI surface

- CLI `run`: new `--enrich-bibliometric` boolean flag (no file path — the input is a
  live API call against this run's entities) and `--openalex-contact-email` (for the
  polite pool; optional). Mirrors GLEIF's "separate, explicit step" posture: this
  triggers a second call to `pipeline.enrich_bibliometric` after `run_screening`,
  then `rescore_run` before export, exactly like the existing GLEIF branch in
  `cli.py:run_pipeline`.
- API: new `POST /runs/{run_id}/bibliometric` route, mirroring
  `POST /runs/{run_id}/ownership` exactly (same request/response shape pattern,
  `dto.py` gains `BibliometricEnrichmentRequest`/`Summary`).
- `app.py`: one more optional sidebar control ("Enrich with bibliometric data"
  button + contact email field), matching the GLEIF section's presentation.

## Tests

- `tests/fixtures/sample_openalex_responses.json` (or similar) — captured real
  response shapes from this plan's live pulls (institutions, authors incl. the real
  tied-candidate case, works/authorships), used to build injectable fetch fixtures
  for `openalex_client.py` — no test hits the live network.
- Unit tests for `institution_match.py`, `author_resolve.py` (including a test
  asserting the real ORCID-tie behavior is preserved: two same-ORCID candidates
  collapse to one identity; two different-ORCID same-name candidates both surface),
  and `cross_check.py` (including a test asserting a bibliometric `ScreeningHit`'s
  `evidence` inlines its producing `ResolvedAuthor`'s tie context with no further
  lookup required — mirroring the shape of the existing
  `test_evidence_is_self_contained_without_a_further_join`).
- `tests/test_pipeline_bibliometric.py` also covers the institution-deduplication
  fix directly: two spelling-variant NSF entities that resolve to the same OpenAlex
  institution ID must trigger exactly one author-resolution/cross-check pass (proven
  via the injectable fetch callable's call count), with both entities' resulting
  scored output reflecting the shared result.
- `tests/test_screening_seven_sons.py` (or folded into `test_screening.py`) — the
  known-important-entity regression test from Finding 1: a fixture with the seven
  real Seven Sons names/aliases, proving the existing `OpenSanctionsList` +
  `screen_entity()` finds all seven with no new code.
- `tests/test_pipeline_bibliometric.py` — `enrich_bibliometric` end-to-end against
  fixtures, proving it doesn't touch `scored_entities`, does persist
  `openalex_author_matches`, and that resulting `ScreeningHit`s score via the
  *existing* rubric factors (same "prove it, don't assume it" pattern as Section
  117's pipeline test).
- **Real-data verification** per the binding section above, run once against the
  live OpenAlex API before calling this done.

## Explicitly out of scope for this pass

**DuckDB VSS / semantic abstract matching** — deferred per discussion; Epic E's
stated acceptance criteria (author disambiguation, co-authorship/affiliation
cross-check, the persistent OpenAlex-precision disclaimer) don't require it, and it
needs its own embedding-model decision this plan doesn't make. **Epic J
(LLM-grounded explanations)** — deferred per discussion, gets its own future plan
once this bibliometric groundwork is solid, per Section 9a's own sequencing note.
**A new `SevenSonsList` class/curated file** — per Finding 1, not needed; a
regression test suffices. **BIS Entity List coverage beyond the literal seven Seven
Sons institutions** — Section 5's data-source table names "Seven Sons / BIS-listed-
university," but this plan scopes to the seven named institutions only, not a
broader BIS-Entity-List-of-universities tracker, which isn't named anywhere in
Section 6/12's acceptance criteria. **OpenAlex's own persistent precision disclaimer**
(Epic E's third acceptance criterion — "every result surfaces OpenAlex's own stated
match-precision caveat inline") — included in this plan's UI work (the >98%
precision/>90% recall figure from OpenAlex's own blog, quoted verbatim, alongside
every bibliometric result in `app.py`), not deferred.

## Verification

- `pytest -q` — full suite plus the new bibliometric test files.
- `python -m entity_screening.cli run ...` without `--enrich-bibliometric` — confirms
  existing behavior is completely unchanged.
- Same command **with** `--enrich-bibliometric` against a real NSF fixture with a
  real PI name — confirms `openalex_author_matches` is populated, the manifest is
  written, and (if a match exists) a `ScreeningHit` appears with both the author-
  resolution confidence and cross-check confidence visible in evidence.
- The real-data pass above, run once against the live OpenAlex API, with whatever is
  actually found recorded in `docs/data_sources.md`, before calling this done.
