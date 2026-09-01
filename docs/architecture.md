# Architecture (V1)

This describes the code as built for V1 (see `docs/requirements.md` Section 12 for the
phased roadmap). `ownership/` and `bibliometric/` are empty package stubs reserved for
V2/V3 and are not part of this pipeline yet.

## Two ways in: the CLI and the API

Both `entity_screening/cli.py` and `entity_screening/api/main.py` are thin callers of
the same orchestration module, `entity_screening/pipeline.py` — per
`docs/requirements.md` Section 9a, Streamlit is a REST client of the API, not a direct
importer of the pipeline, while the CLI still calls `pipeline.py` in-process and does
not depend on the API server being up:

```
  cli.py "run"  ──┐
                  ├──▶ pipeline.py ──▶ ingestion/ → resolution/ → screening/ → scoring/
  api/main.py  ───┘         │
     ▲                      ▼
     │              common/storage.py (DuckDB) + common/manifest.py (JSON manifests)
     │
  app.py (Streamlit) ── HTTP (requests) ──▶ api/main.py
```

## Pipeline stages (inside `pipeline.py`)

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
                 │ normalize.py │  normalized awardee name (pipeline.py:
                 │ (used here)  │  resolve_entities_from_nsf)
                 └──────┬───────┘
                        │ ResolvedEntity
                        ▼
                 ┌──────────────┐
                 │ screening/   │  blocks + fuzzy-matches each entity against
                 │ lists.py     │  every registered EntityOfConcernList
                 │ screen.py    │  (OpenSanctionsList + DoD1260HList) -> ScreeningHit
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
                 │ export.py    │  evidence trail, run_id, and export_id
                 └──────────────┘
```

`pipeline.py` exposes three entry points, each with a specific reproducibility
contract (see `docs/methodology.md` for the full rationale):

- **`run_screening(...)`** — ingest → resolve → screen → score → persist. The one and
  only writer of the `scored_entities` DuckDB table (the run's canonical baseline
  score). Writes one `RunManifest`.
- **`rescore_run(run_id, rubric, ...)`** — pure read-compute-return: recomputes scores
  for an already-persisted run under a different rubric, with **zero database
  writes**. This is what backs the Streamlit rubric sliders — dragging one must never
  grow the database.
- **`export_scored_entities(...)`** — writes a CSV or Excel file plus its own
  immutable `ExportManifest`, unconditionally, on every call. A downloaded file's
  score values are always traceable to the rubric that actually produced them, which
  is not necessarily the rubric recorded in the source run's `RunManifest`.

`common/storage.py` persists raw records, resolved entities, screening hits, and
scored entities into a DuckDB file (DuckDB, not SQLite — see
`docs/requirements.md` Section 7) for ad-hoc querying alongside the file exports.

## Module map

| Package | Responsibility |
|---|---|
| `entity_screening/common/` | Canonical schema (`schema.py`), DuckDB storage (`storage.py`), run/export manifests — reproducibility (`manifest.py`) |
| `entity_screening/ingestion/` | Per-source ingesters (`nsf.py`, `opensanctions.py`, `dod_1260h.py`) implementing the `BaseIngester` streaming contract (`base.py`) |
| `entity_screening/resolution/` | Name normalization (`normalize.py`) and fuzzy scoring (`matcher.py`) |
| `entity_screening/screening/` | Entity-of-concern list registry (`lists.py`, registered: `OpenSanctionsList`, `DoD1260HList`), the screening pass (`screen.py`), and the bundled DoD 1260H curated snapshot (`data/dod_1260h.json`) |
| `entity_screening/scoring/` | User-editable rubric (`rubric.py`) and score decomposition (`score.py`) |
| `entity_screening/output/` | CSV/Excel export (`export.py`) |
| `entity_screening/pipeline.py` | Shared orchestration: `run_screening`, `rescore_run`, `export_scored_entities` — called by both the CLI and the API |
| `entity_screening/cli.py` | `run` (full pipeline, calls `pipeline.py` in-process) and `validate` (structural sanity checks) |
| `entity_screening/api/` | FastAPI layer over `pipeline.py` — `main.py` (routes) + `dto.py` (HTTP request/response models, kept separate from `common/schema.py`'s internal engine model) |
| `app.py` | Streamlit review UI: thin HTTP client of the API — scored/filterable table, rubric sliders, evidence-trail inspector, export buttons |

## Why no "confirmed" status is possible

`common/schema.py`'s `MatchStatus` enum has exactly one member, `CANDIDATE_MATCH`.
Every type that carries a match outcome (`MatchCandidate`, `ScreeningHit`) uses this
enum, so there is no code path — in resolution, screening, scoring, or export — that
can produce anything but a scored candidate. This is the concrete mechanism behind
`docs/requirements.md` Section 10's "candidate, not confirmed" non-functional
requirement.

## Running it

**CLI (batch, no server required):**

```
pip install -r requirements.txt
python -m entity_screening.cli validate
python -m entity_screening.cli run \
    --nsf-file tests/fixtures/sample_nsf_awards.json \
    --opensanctions-file tests/fixtures/sample_opensanctions_targets.csv \
    --excel
```

**API + Streamlit UI (two processes):**

```
uvicorn entity_screening.api.main:app --reload
streamlit run app.py   # in a second terminal
```

**Or via Docker Compose (two containers, wired together):**

```
scripts\compose-up.ps1
```

`docker-compose.yml` builds `Dockerfile.api` (the FastAPI service, port 8000) and
`Dockerfile.streamlit` (the UI, port 8501) as separate containers — Streamlit is a
client of the API, so it has nothing to talk to on its own; `docker-compose.yml` sets
`API_BASE_URL=http://api:8000` on the Streamlit container so it resolves the API by
its compose service name rather than `localhost`. `./data` is mounted into the API
container so manifests/exports/the DuckDB file persist on the host across restarts.
There is deliberately no single combined image: one container per process is the
standard Docker pattern, and it mirrors how these two would actually be deployed
(Section 9's nginx + systemd plan runs them as separate managed processes too).

**Why `scripts\compose-up.ps1` and not a bare `docker compose up --build`:**
`.dockerignore` excludes `.git` from the build context — shipping this repo's whole
history into a runtime image just to read one commit hash isn't worth it — so
`common/manifest.py`'s `_git_commit()` can't shell out to `git rev-parse HEAD` inside
the API container the way it can natively. `Dockerfile.api` instead bakes the commit
in at build time via a `GIT_COMMIT` build arg, and the wrapper script is what actually
supplies that value from your current checkout; a bare `docker compose up --build`
will silently build without it and `RunManifest.git_commit` will read `null` again.

`--nsf-file` (CLI) / the "NSF awards JSON file" field (UI) accepts a local,
pre-downloaded NSF Award Search JSON response (the "size-capped demo dataset"
pattern from Section 9); omit it and pass `--nsf-date-start`/`--nsf-date-end`
(CLI only, for now) to pull live from the NSF API instead.
