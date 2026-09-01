# Methodology (Epic G)

Every pipeline run (`python -m entity_screening.cli run`, or `POST /runs` via the API)
writes a `RunManifest` to `data/processed/runs/<run_id>/manifest.json`. Every export —
CSV or Excel, from the CLI or the API's `/export.csv`/`/export.xlsx` — writes its own
`ExportManifest` to `data/processed/runs/<run_id>/exports/<export_id>/manifest.json`,
alongside the file itself. **These are two different manifests answering two different
questions**, and the distinction matters (see "Two manifests, not one" below): neither
file — not this document — is a substitute for shipping the actual manifest(s)
alongside any published result.

## Two manifests, not one

`docs/requirements.md` Section 9a's FastAPI layer lets a run be re-scored under a
different rubric via `GET /runs/{id}/scores` without re-running ingestion or
screening — that's what makes the Streamlit rubric sliders re-score instantly. That
also means a run's *original* rubric and the rubric that produced any *particular*
exported file's score values can legitimately differ. So:

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

## Known limitations (V1)

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
- **V1 covers NSF Award Search, OpenSanctions, and DoD's Section 1260H list.** GLEIF
  ownership chains, Section 117 disclosures, the Seven Sons seed list, and OpenAlex
  bibliometric matching are V2/V3 scope (`docs/requirements.md` Section 12) and are
  not reflected in any V1 run's results.
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
