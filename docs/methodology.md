# Methodology (Epic G)

Every pipeline run (`python -m entity_screening.cli run`, or `POST /runs` via the API)
writes a `RunManifest` to `data/processed/runs/<run_id>/manifest.json`. Every export —
CSV or Excel, from the CLI or the API's `/export.csv`/`/export.xlsx` — writes its own
`ExportManifest` to `data/processed/runs/<run_id>/exports/<export_id>/manifest.json`,
alongside the file itself. If ownership analysis (Epic C) has been run, a third
`GleifSnapshotManifest` lands at `data/processed/runs/<run_id>/ownership/manifest.json`.
**These are three different manifests answering three different questions**, and the
distinction matters (see "Three manifests, not one" below): none of these files — not
this document — are a substitute for shipping the actual manifest(s) alongside any
published result.

## Three manifests, not one

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

## Known limitations (V1 + Epic C)

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
- **This build covers NSF Award Search, OpenSanctions, DoD's Section 1260H list, and
  GLEIF ownership/foreign-control flagging (Epic C).** Section 117 disclosures, the
  Seven Sons seed list, and OpenAlex bibliometric matching remain V3 scope
  (`docs/requirements.md` Section 12) and are not reflected in any run's results.
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
