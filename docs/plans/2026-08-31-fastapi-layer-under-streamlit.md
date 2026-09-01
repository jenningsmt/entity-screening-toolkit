# FastAPI Layer Under Streamlit — Design Plan (for review, not yet building)

## Context

`docs/requirements.md` Section 9a (added mid-V1, after researching FinchAI/ARGUS's
actual technology stack) calls for a FastAPI REST layer sitting over the
`entity_screening` engine, with Streamlit demoted to a thin client of that API rather
than calling the pipeline in-process. Right now `app.py` imports `entity_screening`
modules directly — `NSFAwardIngester`, `OpenSanctionsTargetsIngester`,
`OpenSanctionsList`, `screen_entity`, `score_entity`, and `resolve_entities_from_nsf`
(the last one imported from `entity_screening/cli.py`, itself a pre-existing layering
smell this change also fixes). This is a real architecture change, so per instruction
this plan is for review before anything gets built — CI and the Dockerfile (also
called for in Section 9a) have already been implemented directly since they wrap
existing code rather than reshape it.

A first draft of this plan proposed a `GET /runs/{run_id}/scores` endpoint for
interactive rubric exploration and let `/export.csv`/`.xlsx` stream "the current or a
passed rubric." On review, that creates a real reproducibility gap: a downloaded CSV
could carry scores produced under a rubric that doesn't match what the run's
`RunManifest` says — the same class of problem as a stale git-commit reference, just
in a different field. This revision fixes that with an explicit **reproducibility
invariants** section below, and states the no-DB-write contract for interactive
rescoring explicitly rather than leaving it implied.

## What doesn't change

The tested core engine — `ingestion/`, `resolution/`, `screening/`, `scoring/`,
`output/`, and `common/` (35 passing tests) — stays exactly as built. This is purely
an orchestration-and-presentation-layer change: extracting the orchestration
currently embedded in `cli.py:run_pipeline()` into a shared module both the CLI and
the new API call, and rebuilding `app.py` as an HTTP client instead of a direct
importer.

## Reproducibility invariants (binding on the implementation)

1. **`scored_entities` holds exactly one row per (entity_id, run_id)** — written once,
   by `run_screening`, under the run's own rubric. This is the run's canonical
   baseline score. `rescore_run` (below) **never writes to `scored_entities` or any
   other table** — it is a pure read-compute-return function, full stop, regardless
   of how many times a client calls it. A slider drag during interactive exploration
   must not touch the database.
2. **Every exported file — CSV or Excel, from the CLI or the API — is accompanied by
   its own immutable `ExportManifest`**, written unconditionally at export time (not
   only when the rubric differs from the run's original, which would require drift-
   detection logic that can itself have bugs). The `ExportManifest` records exactly
   which rubric and thresholds produced that file's score values. Every row in the
   exported file carries the resulting `export_id` (alongside the existing `run_id`),
   so the file is self-describing on its own — consistent with the Section 9a
   schema-discipline principle already applied to `ScreeningHit.evidence` — even if
   it's later separated from the directory its manifest lives in.
3. **`RunManifest` continues to describe ingestion/screening provenance only**
   (dataset snapshots, screening threshold, git commit, and the rubric active at
   run-creation time as a historical fact). It is never read as a live claim about
   what any particular export's scores were computed under — that's `ExportManifest`'s
   job.

## New module: `entity_screening/pipeline.py`

`cli.py:run_pipeline()` currently does five things inline: ingest, resolve, screen +
score every entity, persist to DuckDB, export CSV/Excel. This plan extracts:

- `run_screening(nsf_source, opensanctions_source, rubric, threshold, db_path) -> RunManifest`
  — ingest, resolve (moving `resolve_entities_from_nsf` here from `cli.py`), screen,
  score under `rubric`, persist via the existing `common/storage.py` insert
  functions (satisfying invariant 1 above — this is the one and only write to
  `scored_entities`), write and return the `RunManifest`.
- `rescore_run(run_id, rubric, db_path) -> list[ScoredEntity]` — reads the
  already-persisted `resolved_entities` and `screening_hits` rows for a `run_id` back
  out of DuckDB and recomputes `ScoreBreakdown` under a new rubric. Requires two new
  reader functions in `common/storage.py` (`load_resolved_entities(conn, run_id)`,
  `load_screening_hits(conn, run_id)`), symmetric to the existing `insert_*` writers.
  **No writes of any kind** — this is what invariant 1 is about.
- `export_scored_entities(scored_entities, source_run_id, rubric, fmt, db_path) -> ExportManifest`
  — wraps `output/export.py`'s `export_csv`/`export_excel`, generating an `export_id`,
  stamping it into every row, and writing the companion `ExportManifest` (invariant 2).
  Called identically whether the caller is `cli.py`'s single-shot run or the API's
  export endpoint — the CLI path gets an `ExportManifest` too, not just the API path,
  so the guarantee holds everywhere rather than being an API-only special case.

`cli.py:run_pipeline()` becomes a thin wrapper: `pipeline.run_screening(...)`, then
`pipeline.export_scored_entities(...)`, then print the summary. `_cmd_validate` and
argparse setup are untouched.

## `common/manifest.py` addition: `ExportManifest`

New dataclass alongside the existing `RunManifest`, same start/write/load pattern:

```
export_id: str
source_run_id: str
exported_at: str
rubric: dict
match_thresholds: dict
format: str        # "csv" | "xlsx"
```

Written to `data/processed/runs/<source_run_id>/exports/<export_id>/manifest.json`.

## `output/export.py` change

`FIELDNAMES` gains `export_id` alongside the existing `run_id`, so a row can be
traced back to (a) the run that produced its underlying entity/hits and (b) the
specific rubric-scoring pass that produced its specific score values.

## New package: `entity_screening/api/`

- `main.py` — FastAPI app + routes:
  - `POST /runs` (**`def`, not `async def`** — FastAPI runs sync routes in its
    threadpool, so the batch pipeline call doesn't block the event loop; irrelevant
    at demo scale but free to get right). Body: nsf source, opensanctions source,
    rubric, threshold. Calls `pipeline.run_screening(...)` (V1 stays
    batch/synchronous per Section 10's NFR — no job queue). Returns `run_id` +
    summary counts.
  - `GET /runs/{run_id}/manifest` — returns the `RunManifest` JSON, so Streamlit can
    surface exact run provenance (git commit, dataset snapshot, rubric, thresholds)
    somewhere visible rather than leaving it a backend-only property.
  - `GET /runs/{run_id}/scores?...rubric query params...` — calls
    `pipeline.rescore_run(...)` (pure, no persistence — invariant 1), returns scored
    entities as JSON. This is what the Streamlit sliders hit on every change.
  - `GET /runs/{run_id}/export.csv` / `/export.xlsx` — calls
    `pipeline.export_scored_entities(...)`, always producing a fresh `ExportManifest`
    (invariant 2). Returns the file, with `export_id` surfaced via an `X-Export-Id`
    response header so a caller can note it without parsing the file body.
  - `GET /rubric/default` — stock rubric weights, so the UI knows what sliders to
    initialize with without hardcoding defaults in two places.
  - `GET /health` — trivial liveness check; costs nothing now, standard once this is
    headed toward actual deployment.
- `dto.py` (not `schemas.py` — a name one letter away from `common/schema.py` in a
  different package is exactly the kind of thing that's easy to mix up narrating this
  in an interview) — pydantic request/response models. Separate from
  `common/schema.py`'s frozen dataclasses, which stay the internal engine model;
  `dto.py` just shapes what crosses the HTTP boundary, with small conversion helpers.

New dependencies (`requirements.txt`): `fastapi`, `uvicorn[standard]`, and `httpx`
(required by FastAPI's `TestClient` for testing the routes — `requests` is already
present for Streamlit's client-side calls).

## `app.py` rewrite

The sidebar/slider/dataframe/evidence-inspector UI structure stays conceptually the
same; what changes is the data-fetching half, which today calls `entity_screening`
modules directly. It becomes `requests` calls against an API base URL (sidebar text
input or env var, default `http://localhost:8000`):
- On load / "Run screening": `POST /runs`, then `GET /runs/{id}/manifest` to display
  provenance (git commit, dataset snapshots, thresholds) somewhere visible in the UI.
- On every slider change: `GET /runs/{id}/scores?...` (ephemeral preview, matches
  invariant 1 — nothing is written by dragging a slider).
- On a new "Download CSV"/"Download Excel" button: `GET /runs/{id}/export.csv` (or
  `.xlsx`) using the *current* slider rubric, surfacing the returned `export_id` next
  to the download so the user can see which manifest describes the file they just got.

## New tests

- `tests/test_pipeline.py` — `run_screening`, `rescore_run` (asserting it performs
  zero writes — e.g. row counts in `scored_entities` unchanged after calling it), and
  `export_scored_entities` (asserting a distinct `ExportManifest` per call, even
  across two exports of the same run) against the existing fixtures and a `tmp_path`
  DuckDB file.
- `tests/test_api.py` — FastAPI `TestClient` hitting `/runs`, `/runs/{id}/manifest`,
  `/runs/{id}/scores`, `/runs/{id}/export.csv`, `/rubric/default`, `/health`
  end-to-end against the same fixtures. Include a test that exports the same run
  twice under two different rubrics and asserts the two files carry two different
  `export_id`s with two matching, distinct `ExportManifest`s.

## Local dev / docs impact

Local development now needs two processes: `uvicorn entity_screening.api.main:app
--reload` and `streamlit run app.py`. `docs/architecture.md`, `docs/methodology.md`
(the `ExportManifest` concept belongs there alongside `RunManifest`), and the README
quickstart need a short update — done as part of implementation, not its own task.

## Explicitly out of scope for this change

No job queue/async workers (batch-first NFR), no auth layer (still a local/portfolio
demo), no change to the CLI's ability to run fully offline without the API server up
— `cli.py` keeps calling `pipeline.run_screening()`/`export_scored_entities()`
in-process directly, it does not route through the API. Terraform/CDKTF and actually
deploying this split are separate, later work per your sequencing.

## Verification (once approved and built)

- `pytest -q` — full suite including new `test_pipeline.py`/`test_api.py`.
- `python -m entity_screening.cli run --nsf-file ... --opensanctions-file ...` — still
  works standalone, no API server required, and now also writes an `ExportManifest`.
- `uvicorn entity_screening.api.main:app --reload`, then:
  - `curl localhost:8000/health` — liveness.
  - `curl -X POST localhost:8000/runs -d '{...}'` — confirm a run executes and
    `scored_entities` gains exactly one row per entity.
  - `curl localhost:8000/runs/{id}/scores?...` twice with different rubric params —
    confirm `scored_entities` row count is unchanged between calls (invariant 1).
  - `curl localhost:8000/runs/{id}/export.csv?...` twice with different rubric params
    — confirm two distinct `export_id`s and two distinct `ExportManifest` files on
    disk, each matching the rubric actually used (invariant 2).
- `streamlit run app.py` against a running API — confirm sliders re-score via network
  calls with no DB growth, and a downloaded export shows the correct `export_id`.

---

### What actually shipped vs. this plan

Implementation matched this plan closely, with two deviations, both improvements
made during the build rather than the plan being wrong:
- `run_screening` returns `tuple[RunManifest, list[ScoredEntity]]` rather than just
  `RunManifest` — avoids forcing every caller to immediately call `rescore_run` just
  to get back data already computed in memory.
- A real bug was found only by running the code against a live, persistent,
  multi-request server (not caught by any unit test, since each one used a fresh
  `tmp_path` database): `resolved_entities`' primary key was `entity_id` alone, but
  `entity_id` is a deterministic hash of the normalized name, so the same real-world
  entity recurring across two separate runs against the same database violated the
  constraint — exactly what happens on every subsequent `POST /runs` a long-lived API
  server handles. Fixed to a composite `(entity_id, run_id)` key; see
  `docs/architecture.md` and the corresponding commit for the full story.
