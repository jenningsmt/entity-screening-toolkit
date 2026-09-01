# Methodology (Epic G)

Every pipeline run (`python -m entity_screening.cli run`, or `POST /runs` via the API)
writes a `RunManifest` to `data/processed/runs/<run_id>/manifest.json`. Every export —
CSV or Excel, from the CLI or the API's `/export.csv`/`/export.xlsx` — writes its own
`ExportManifest` to `data/processed/runs/<run_id>/exports/<export_id>/manifest.json`,
alongside the file itself. If ownership analysis (Epic C) has been run, a third
`GleifSnapshotManifest` lands at `data/processed/runs/<run_id>/ownership/manifest.json`.
If bibliometric enrichment (Epic E) has been run, a fourth
`BibliometricSnapshotManifest` lands at
`data/processed/runs/<run_id>/bibliometric/manifest.json`.
**These are four different manifests answering four different questions**, and the
distinction matters (see "Manifests, not one" below): none of these files — not
this document — are a substitute for shipping the actual manifest(s) alongside any
published result.

## Manifests, not one

`docs/requirements.md` Section 9a's FastAPI layer lets a run be re-scored under a
different rubric via `GET /runs/{id}/scores` without re-running ingestion or
screening — that's what makes the Streamlit rubric sliders re-score instantly. Epic C
adds a second, independent axis of drift on top of that: ownership enrichment
(`POST /runs/{id}/ownership`) can be run against a run using whatever GLEIF snapshot
happens to be supplied at the time, separately from when the run itself was created,
and can be re-run later against a newer GLEIF download. So:

- **`RunManifest`** describes ingestion/screening provenance: which dataset snapshots
  were used, the screening confidence threshold, and the rubric active when the run
  was first created. Treat that last field as a historical fact about the run's
  creation, never as a live claim about what any specific export's scores were
  computed under.
- **`ExportManifest`** describes exactly what produced one specific file's score
  values: the rubric and thresholds active at the moment that file was written. Every
  row in the file carries the resulting `export_id`, so the file is self-describing
  even separated from its manifest. If you're citing a CSV's numbers, cite the
  `ExportManifest` next to it, not the parent run's `RunManifest`.
- **`GleifSnapshotManifest`** describes exactly which GLEIF Level 1/2 download
  produced a run's foreign-control flags. It's written into the run's own directory
  specifically so it survives independently of the shared, disposable `gleif_lei`/
  `gleif_relationships` DuckDB tables, which get replaced by the *next*
  `enrich_ownership` call for *any* run — those tables are a working copy, this file
  is the durable record. Re-running ownership enrichment for the same run overwrites
  this file (a "current state" model, like `scored_entities`, not a versioned history
  like `ExportManifest`'s per-call uniqueness).
- **`BibliometricSnapshotManifest`** generalizes the same durability principle to a
  source with no file path at all: OpenAlex is a live, continuously-updated API, not
  a downloaded snapshot. Its job is provenance of *when* a run's bibliometric
  enrichment queried OpenAlex, not *which* file — there is no "which" here the way
  GLEIF has a specific CSV. Same "current state," overwritten-on-re-run semantics as
  `GleifSnapshotManifest`.

## What `RunManifest` records

| Field | Meaning |
|---|---|
| `run_id` | Unique identifier for this run; every row exported under it carries this as `run_id`. |
| `started_at` / `finished_at` | UTC timestamps bounding the run. |
| `git_commit` | The exact commit of this codebase the run executed against — read from a `GIT_COMMIT` env var if set (how the API container gets it; see `Dockerfile.api` and `scripts/compose-up.ps1`), otherwise from `git rev-parse HEAD` for native runs. `null` if neither is available. |
| `dataset_snapshots` | Per source: `source_dataset`, `retrieved_at`, `location` (file path or API endpoint), and `record_count` — the exact data snapshot used. |
| `rubric` | The `ScoringRubric` weights active when the run was created — historical, see above. |
| `match_thresholds` | The screening confidence threshold applied during screening (this one doesn't drift — screening, unlike scoring, isn't redone on rescore). |
| `ingestion_error_counts` | How many records were rejected as malformed during ingestion (see `ingestion_errors.jsonl` in the same run directory for the specific records and reasons). |

## What `ExportManifest` records

| Field | Meaning |
|---|---|
| `export_id` | Unique identifier for this specific export; every row in the file carries this as `export_id`. |
| `source_run_id` | Which run's persisted entities/hits this export was scored from. |
| `exported_at` | UTC timestamp of the export. |
| `rubric` | The exact `ScoringRubric` weights that produced this file's score values — may differ from `source_run_id`'s `RunManifest.rubric`. |
| `match_thresholds` | Copied from the source run at export time, for convenience. |
| `format` | `"csv"` or `"xlsx"`. |

## What `GleifSnapshotManifest` records

| Field | Meaning |
|---|---|
| `run_id` | Which run this ownership enrichment was computed for. |
| `loaded_at` | UTC timestamp of the enrichment call. |
| `lei_record_count` / `relationship_record_count` | Rows actually loaded from the supplied GLEIF files (Level 2 count is post-filter — only ACTIVE `IS_DIRECTLY_CONSOLIDATED_BY`/`IS_ULTIMATELY_CONSOLIDATED_BY` rows are kept). |
| `gleif_lei_file` / `gleif_relationships_file` | The exact file paths supplied for this enrichment call. |

## What `BibliometricSnapshotManifest` records

| Field | Meaning |
|---|---|
| `run_id` | Which run this bibliometric enrichment was computed for. |
| `queried_at` | UTC timestamp of the enrichment call — the only "snapshot date" that exists for a live API source. |
| `pi_count` | Distinct PI names re-derived from `raw_nsf_awards` for this run and passed to author disambiguation. |
| `resolved_author_count` | Total `ResolvedAuthor` rows persisted (every tied candidate counts separately — see the ResolvedAuthor known limitation below). |
| `openalex_api_base_url` | The OpenAlex API endpoint queried. |

## Known limitations (V1 through V3)

- **Entity resolution is intra-source only.** `pipeline.py:resolve_entities_from_nsf`
  groups NSF award records into entities by exact match on a normalized awardee name;
  it does
  not yet attempt cross-source resolution beyond the screening step itself. A real
  alias that doesn't survive suffix-stripping/transliteration/acronym-expansion
  won't be grouped (see Epic B's normalization rules in `resolution/normalize.py`).
- **Screening uses a blocking step.** `screening/lists.py` only compares a candidate
  entity against entries sharing a 3-character normalized-name prefix, to keep
  screening tractable against a large list (e.g. OpenSanctions' full target file).
  A true match that differs in its first three characters (e.g. a name that starts
  with a translated/reordered word) will not be found. This is a standard
  entity-resolution trade-off, not a bug, but it is a real recall limit worth
  stating explicitly per Section 10's "known limitations" requirement.
- **Bare acronym/fuzzy matching can't catch a genuine alias with no shared
  characters** (e.g. a university's English name vs. an unrelated commonly-used
  short name in another language). That class of match is out of reach for string
  similarity alone and is a documented, not silently ignored, gap.
- **This build covers all of V1, V2, and V3**: NSF Award Search, OpenSanctions,
  DoD's Section 1260H list, GLEIF ownership/foreign-control flagging (Epic C), the
  Section 117 foreign-funding disclosure cross-check, and the OpenAlex bibliometric
  co-authorship/affiliation layer (Epic E) with the Seven Sons universities covered
  via OpenSanctions (no dedicated list — see `docs/data_sources.md`). Epic J
  (LLM-grounded explanations) and DuckDB VSS semantic-abstract matching remain
  deliberately deferred, V3-adjacent follow-ups (`docs/requirements.md` Section 9a)
  and are not reflected in any run's results.
- **A PI can genuinely resolve to more than one OpenAlex author identity, and this
  project does not force a single pick when that happens.** Real data confirmed this
  is not a rare edge case: a real NSF PI's name, even narrowed server-side to
  authors ever affiliated with the exact target institution, returned three
  distinct OpenAlex author records — two sharing an identical ORCID (collapsed to
  one identity, since that's almost certainly the same person, unmerged in
  OpenAlex) and a third, distinct candidate with no ORCID (a genuine open tie).
  `ResolvedAuthor` and any resulting bibliometric `ScreeningHit` both surface this
  explicitly in `evidence` rather than silently guessing the "most likely" one — see
  `docs/data_sources.md`'s OpenAlex entry for the real example.
- **A bibliometric `ScreeningHit`'s `confidence` is the funder/institution-vs-
  concern-list match confidence only** — the author-disambiguation confidence that
  determined *which* real person this hit is even about is inlined into
  `evidence["author_resolution"]`, not blended into the headline number, mirroring
  the same funder-only-confidence design (and the same review discipline) already
  applied to Section 117's two-stage match. Whether this needs to become a compound
  of both confidences instead is exactly the kind of question that needs checking
  against real, higher-volume PI data before being trusted at scale — flagged here
  as a known open question, not a settled one.
- **`enrich_bibliometric` only re-derives PIs from NSF records with both
  `piFirstName` and `piLastName` populated** — records missing either are still
  screened normally by every other epic, just not bibliometrically enriched.
- **The Section 117 cross-check only searches disclosures that name a specific
  foreign entity** (~5% of rows in the real Feb 2025 bulk file) — the other ~95%
  report only a country, with no entity name to fuzzy-match against anything; those
  rows are still ingested (for potential future country-level analysis) but never
  produce a hit. `ScreeningHit.confidence` for a Section 117 hit is the funder-match
  confidence only; the institution match (is this disclosure even about the entity
  being screened?) is demoted to `evidence` context, which is sound only because real
  institution matches cluster at 0.97–1.0 once
  `strip_institutional_governance_affix` is applied (see below) — not because the
  institution match matters less in principle.
- **`strip_institutional_governance_affix` handles the common NSF-legal-name-vs-
  Section-117-common-name drift, but not every naming style.** A rarer
  system-consortium "obo" convention (e.g. "Board of Regents, NSHE, obo University of
  Nevada, Reno") stays a documented miss — confirmed against the real data, not
  chased with further special-casing given how rare that specific pattern is (see
  `docs/plans/2026-09-01-section-117-foreign-gift-disclosure-cross-check.md`).
- **GLEIF name-to-LEI matching inherits every limitation of fuzzy name matching, at
  a scale where it shows up more often** — see `docs/data_sources.md`'s GLEIF entry
  for two concrete, real (not hypothetical) examples found while building this:
  a large well-known company whose actual parent entity has no LEI at all (voluntary
  registration, genuinely incomplete coverage), and a same-normalized-name collision
  between two unrelated real companies. Both are properties of the shared matcher
  (`resolution/matcher.py`), not something specific to the GLEIF integration, but
  GLEIF's ~3.4M entities make them concretely observable in a way OpenSanctions and
  DoD 1260H's much smaller lists don't.
- **A foreign-control flag inherits the uncertainty of two separate matches, not
  one**: the name-to-LEI match, and (if the walk to the ultimate parent was
  `truncated`) the fact that a deeper, undiscovered parent might exist. Both are
  surfaced in the flag's own `evidence`, not hidden behind a single confidence number.
- **The DoD 1260H list is a static, hand-curated snapshot, not a live feed** (see
  `docs/data_sources.md`). It's bundled with the package
  (`entity_screening/screening/data/dod_1260h.json`) and needs periodic manual
  re-curation from its source — a run's manifest records which snapshot was used via
  the `dod_section_1260h` dataset snapshot's `location` and `retrieved_at` fields, but
  it won't ever reflect a more recent designation than whatever's bundled in the
  codebase at the time.

## Reproducing a published result

1. Locate the exported file's own `ExportManifest`
   (`data/processed/runs/<run_id>/exports/<export_id>/manifest.json`) — this, not the
   run's `RunManifest`, has the rubric that actually produced the numbers in the file.
2. From the `ExportManifest`'s `source_run_id`, locate the run's `RunManifest` and
   `ingestion_errors.jsonl` for dataset/screening provenance.
3. Re-fetch the exact dataset snapshot(s) named in `RunManifest.dataset_snapshots`
   (same file, or the same API date range) — snapshots are not re-downloaded
   automatically.
4. Check out the `git_commit` recorded in the `RunManifest`.
5. Re-run ingestion/screening with the same `match_thresholds`
   (`RunManifest.match_thresholds`, via `--threshold`), then re-score with the
   `ExportManifest`'s `rubric` (via `--rubric-file`, a JSON file matching that block).
6. If the exported rows carry `ownership_flags`, also locate
   `data/processed/runs/<run_id>/ownership/manifest.json` and re-download the exact
   GLEIF snapshot named there (`gleif_lei_file`/`gleif_relationships_file` — these are
   the paths as supplied at enrichment time, not a permanent GLEIF snapshot ID, since
   GLEIF republishes Golden Copy files daily) before re-running
   `--gleif-lei-file`/`--gleif-relationships-file`.
7. If the exported rows carry a bibliometric `ScreeningHit` (one with
   `evidence["author_resolution"]`), locate
   `data/processed/runs/<run_id>/bibliometric/manifest.json` for the `queried_at`
   timestamp — there is no snapshot file to re-download here (OpenAlex is a live,
   continuously-updated API), so exact reproduction means re-running
   `--enrich-bibliometric` and accepting that OpenAlex's own underlying data may
   have changed since `queried_at`, not that a fixed input is being re-supplied.
