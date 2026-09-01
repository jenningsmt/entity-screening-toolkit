# Methodology (Epic G)

Every pipeline run (`python -m entity_screening.cli run`) writes a companion
`manifest.json` alongside its CSV/Excel export, at
`data/processed/runs/<run_id>/manifest.json`. That file — not this document — is the
authoritative, per-run record of exactly what produced a given result. This document
explains what's in it and how to read it; it is a template to accompany any published
results, not a substitute for shipping the actual manifest alongside them.

## What the manifest records

| Field | Meaning |
|---|---|
| `run_id` | Unique identifier for this run; every exported CSV/Excel row is stamped with it. |
| `started_at` / `finished_at` | UTC timestamps bounding the run. |
| `git_commit` | The exact commit of this codebase the run executed against, if run from a git checkout. |
| `dataset_snapshots` | Per source: `source_dataset`, `retrieved_at`, `location` (file path or API endpoint), and `record_count` — the exact data snapshot used. |
| `rubric` | The full `ScoringRubric` weights active for this run (Epic F — user-editable, so this is what makes a given score reproducible). |
| `match_thresholds` | The screening confidence threshold applied. |
| `ingestion_error_counts` | How many records were rejected as malformed during ingestion (see `ingestion_errors.jsonl` in the same run directory for the specific records and reasons). |

## Known limitations (V1)

- **Entity resolution is intra-source only.** `resolve_entities_from_nsf` groups NSF
  award records into entities by exact match on a normalized awardee name; it does
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
- **V1 covers only NSF Award Search and OpenSanctions.** GLEIF ownership chains,
  Section 117 disclosures, DoD's 1260H list, the Seven Sons seed list, and OpenAlex
  bibliometric matching are V2/V3 scope (`docs/requirements.md` Section 12) and are
  not reflected in any V1 run's results.

## Reproducing a published result

1. Locate the run's `manifest.json` and `ingestion_errors.jsonl`.
2. Re-fetch the exact dataset snapshot(s) named in `dataset_snapshots` (same file, or
   the same API date range) — snapshots are not re-downloaded automatically.
3. Check out the `git_commit` recorded in the manifest.
4. Re-run with the same `rubric` and `match_thresholds` values, either via
   `--rubric-file` (a JSON file matching the `rubric` block) and `--threshold`.
