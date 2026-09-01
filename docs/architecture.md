# Architecture (V1)

This describes the code as built for V1 (see `docs/requirements.md` Section 12 for the
phased roadmap). `ownership/` and `bibliometric/` are empty package stubs reserved for
V2/V3 and are not part of this pipeline yet.

## Pipeline stages

```
                 ┌──────────────┐
  NSF API/file ─▶│  ingestion/  │  streams SourceRecord, tags source_dataset /
                 │  nsf.py      │  retrieval_date / source_record_id, logs
OpenSanctions   ─▶│ opensanctions.py │  malformed records to ingestion_errors.jsonl
  targets.csv    └──────┬───────┘
                        │ SourceRecord
                        ▼
                 ┌──────────────┐
                 │ resolution/  │  groups NSF records into ResolvedEntity by
                 │ normalize.py │  normalized awardee name (cli.py:
                 │ (used here)  │  resolve_entities_from_nsf)
                 └──────┬───────┘
                        │ ResolvedEntity
                        ▼
                 ┌──────────────┐
                 │ screening/   │  blocks + fuzzy-matches each entity against
                 │ lists.py     │  every registered EntityOfConcernList
                 │ screen.py    │  (only OpenSanctionsList in V1) -> ScreeningHit
                 └──────┬───────┘
                        │ ScreeningHit
                        ▼
                 ┌──────────────┐
                 │ scoring/     │  ScoringRubric (user-editable weights) turns
                 │ rubric.py    │  hits into a ScoreBreakdown: total + per-factor
                 │ score.py     │  decomposition — never an opaque number
                 └──────┬───────┘
                        │ ScoredEntity
                        ▼
                 ┌──────────────┐
                 │ output/      │  CSV/Excel export, one row per entity, with
                 │ export.py    │  evidence trail and run_id back-reference
                 └──────────────┘

  common/manifest.py ties every stage together: one RunManifest per invocation
  records exact dataset snapshots, rubric, thresholds, and ingestion error
  counts to data/processed/runs/<run_id>/manifest.json.

  common/storage.py persists raw records, resolved entities, screening hits,
  and scored entities into data/processed/entity_screening.duckdb (DuckDB,
  not SQLite — see docs/requirements.md Section 7) for ad-hoc querying
  alongside the CSV/Excel export.
```

## Module map

| Package | Responsibility |
|---|---|
| `entity_screening/common/` | Canonical schema (`schema.py`), DuckDB storage (`storage.py`), run manifest / reproducibility (`manifest.py`) |
| `entity_screening/ingestion/` | Per-source ingesters (`nsf.py`, `opensanctions.py`) implementing the `BaseIngester` streaming contract (`base.py`) |
| `entity_screening/resolution/` | Name normalization (`normalize.py`) and fuzzy scoring (`matcher.py`) |
| `entity_screening/screening/` | Entity-of-concern list registry (`lists.py`) and the screening pass (`screen.py`) |
| `entity_screening/scoring/` | User-editable rubric (`rubric.py`) and score decomposition (`score.py`) |
| `entity_screening/output/` | CSV/Excel export (`export.py`) |
| `entity_screening/cli.py` | Wires the stages together: `run` (full pipeline) and `validate` (structural sanity checks) |
| `app.py` | Streamlit review UI: scored/filterable table, rubric sliders, evidence-trail inspector |

## Why no "confirmed" status is possible

`common/schema.py`'s `MatchStatus` enum has exactly one member, `CANDIDATE_MATCH`.
Every type that carries a match outcome (`MatchCandidate`, `ScreeningHit`) uses this
enum, so there is no code path — in resolution, screening, scoring, or export — that
can produce anything but a scored candidate. This is the concrete mechanism behind
`docs/requirements.md` Section 10's "candidate, not confirmed" non-functional
requirement.

## Running it

```
pip install -r requirements.txt
python -m entity_screening.cli validate
python -m entity_screening.cli run \
    --nsf-file tests/fixtures/sample_nsf_awards.json \
    --opensanctions-file tests/fixtures/sample_opensanctions_targets.csv \
    --excel
streamlit run app.py
```

`--nsf-file` accepts a local, pre-downloaded NSF Award Search JSON response (the
"size-capped demo dataset" pattern from Section 9); omit it and pass
`--nsf-date-start`/`--nsf-date-end` to pull live from the NSF API instead.
