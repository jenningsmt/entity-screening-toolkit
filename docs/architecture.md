# Architecture (V1 through V3)

This describes the code as built for V1 through V3 (Epic C's GLEIF ownership graph
and foreign-control flagging, the Section 117 foreign-funding disclosure cross-check,
and Epic E's OpenAlex bibliometric co-authorship/affiliation layer, with the Seven
Sons universities covered via the existing OpenSanctions data rather than a
dedicated list) — see `docs/requirements.md` Section 12 for the phased roadmap. Epic
J (LLM-grounded explanations) and DuckDB VSS semantic-abstract matching remain
deliberately deferred, V3-adjacent follow-ups, not part of any currently-scheduled
phase.

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
                 │ screen.py    │  (OpenSanctionsList + DoD1260HList) -> ScreeningHit,
                 │ section_117  │  plus (if a Section 117 file was supplied) a second,
                 │ .py          │  two-stage cross-check against the same lists
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

  Separately (not part of the chain above — see below):
                 ┌──────────────┐
  GLEIF L1/L2  ─▶│ ownership/   │  bulk-loads GLEIF into DuckDB, resolves each
  CSV files      │ ingest.py    │  entity to an LEI (SQL-blocked, Python-scored,
                 │ match.py     │  reusing resolution/matcher.py), walks the
                 │ graph.py     │  parent/subsidiary graph (recursive CTE), and
                 │ flagging.py  │  flags a foreign ultimate-parent jurisdiction
                 └──────┬───────┘
                        │ ForeignControlFlag
                        ▼
                 (fed into scoring/score.py alongside ScreeningHit, via rescore_run)

  Also separately, a second live-external-source enrichment step:
                 ┌──────────────────┐
  api.openalex   │ bibliometric/     │  resolves each entity to an OpenAlex
  .org (live)  ─▶│ institution_match │  institution (live search+score, no bulk
                 │ author_resolve    │  download), disambiguates each PI to an
                 │ cross_check       │  OpenAlex author (may return several tied
                 └──────┬────────────┘  candidates, never a forced pick), then
                        │ ScreeningHit  walks co-authorship/affiliation history
                        ▼               against the same registered concern lists
                 (fed into scoring/score.py alongside every other ScreeningHit,
                  via the existing screening_hit_weight/multiple_list_hit_bonus
                  factors -- no new scoring changes, via rescore_run)
```

`pipeline.py` exposes five entry points, each with a specific reproducibility
contract (see `docs/methodology.md` for the full rationale):

- **`run_screening(...)`** — ingest → resolve → screen → score → persist. The one and
  only writer of the `scored_entities` DuckDB table (the run's canonical baseline
  score). Writes one `RunManifest`.
- **`rescore_run(run_id, rubric, ...)`** — pure read-compute-return: recomputes scores
  for an already-persisted run under a different rubric, with **zero database
  writes**. This is what backs the Streamlit rubric sliders — dragging one must never
  grow the database. Also loads any persisted `ownership_flags` for the run, so a
  `foreign_control_weight` slider change re-scores instantly too, without redoing any
  GLEIF matching or graph traversal.
- **`enrich_ownership(run_id, ...)`** — a **separate, explicit step from
  `run_screening`**, callable independently against a run that already exists. GLEIF
  is a shared reference dataset, not a per-run ingestion source — `gleif_lei`/
  `gleif_relationships` are a disposable working copy, rebuilt by any call, for any
  run. Never touches `scored_entities`; writes `lei_matches`/`ownership_flags` plus a
  durable, run-scoped `GleifSnapshotManifest`.
- **`enrich_bibliometric(run_id, ...)`** — a **separate, explicit step from
  `run_screening`**, same posture as `enrich_ownership`: OpenAlex is a live external
  source, not a per-run ingestion source. Re-derives PI names from `raw_nsf_awards`
  (`resolved_entities` doesn't retain PI-level detail) and rebuilds the run's
  concern lists from `raw_opensanctions_targets`/`raw_dod_1260h` as already
  persisted, rather than requiring the caller to re-supply file paths. Groups
  entities by their *resolved* OpenAlex institution ID (not `entity_id`) so a
  spelling-variant split from Epic B's exact-match grouping doesn't duplicate
  OpenAlex calls or hits. Never touches `scored_entities`; writes
  `openalex_author_matches`/new `ScreeningHit`s plus a durable, run-scoped
  `BibliometricSnapshotManifest`.
- **`export_scored_entities(...)`** — writes a CSV or Excel file plus its own
  immutable `ExportManifest`, unconditionally, on every call. A downloaded file's
  score values are always traceable to the rubric that actually produced them, which
  is not necessarily the rubric recorded in the source run's `RunManifest`.

`common/storage.py` persists raw records, resolved entities, screening hits, scored
entities, and (if `enrich_ownership`/`enrich_bibliometric` have run) LEI matches,
ownership flags, and OpenAlex author matches into a DuckDB file (DuckDB, not SQLite
— see `docs/requirements.md` Section 7) for ad-hoc querying alongside the file
exports.

## Module map

| Package | Responsibility |
|---|---|
| `entity_screening/common/` | Canonical schema (`schema.py`), DuckDB storage (`storage.py`), run/export/GLEIF/bibliometric manifests — reproducibility (`manifest.py`) |
| `entity_screening/ingestion/` | Per-source ingesters (`nsf.py`, `opensanctions.py`, `dod_1260h.py`, `section_117.py`) implementing the `BaseIngester` streaming contract (`base.py`) |
| `entity_screening/resolution/` | Name normalization (`normalize.py`, including the Section-117-specific `strip_institutional_governance_affix`) and fuzzy scoring (`matcher.py`) |
| `entity_screening/screening/` | Entity-of-concern list registry (`lists.py`, registered: `OpenSanctionsList`, `DoD1260HList`), the screening pass (`screen.py`), the Section 117 two-stage cross-check (`section_117.py`), and the bundled DoD 1260H curated snapshot (`data/dod_1260h.json`) |
| `entity_screening/scoring/` | User-editable rubric (`rubric.py`, includes `foreign_control_weight`) and score decomposition (`score.py`) |
| `entity_screening/output/` | CSV/Excel export (`export.py`) |
| `entity_screening/ownership/` | GLEIF bulk ingestion (`ingest.py` — deliberately *not* a `BaseIngester`, see its module docstring), SQL-blocked LEI resolution (`match.py`), recursive graph traversal (`graph.py`), foreign-control flagging (`flagging.py`) — Epic C |
| `entity_screening/bibliometric/` | OpenAlex REST client with injectable fetch (`openalex_client.py`), live institution resolution (`institution_match.py`), PI-to-author disambiguation that can return several tied candidates (`author_resolve.py`), and the co-authorship/affiliation cross-check (`cross_check.py`) — Epic E. No NetworkX dependency, unlike `docs/requirements.md` Section 7's original guess: OpenAlex's own `works` endpoint already returns each paper's full `authorships` list directly, so checking co-authors/affiliations is flat list iteration, not graph traversal — that guidance was written before this project had seen the real API shape. |
| `entity_screening/pipeline.py` | Shared orchestration: `run_screening`, `rescore_run`, `enrich_ownership`, `enrich_bibliometric`, `export_scored_entities` — called by both the CLI and the API |
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

Add `--gleif-lei-file`/`--gleif-relationships-file` (both required together, or both
omitted) to also run ownership/foreign-control analysis (Epic C) — GLEIF's files
aren't bundled (see `docs/data_sources.md` for exactly where to download them and two
real gotchas: the format and the exact CSV column names).

Add `--section-117-file` (a single Section 117 bulk-download `.xlsx`, also not
bundled) to also run the foreign-funding disclosure cross-check. This chains two
fuzzy matches: `School Name` against the resolved entity (institution match, governed
by `--section-117-institution-threshold`, default 0.90 — see
`entity_screening/resolution/normalize.py:strip_institutional_governance_affix` for
why this needs its own normalization step, not the standard one), then, only for rows
clearing that, the disclosed foreign entity against the same registered concern lists
`screen_entity()` already checks (funder match, governed by the standard
`--threshold`). Omit the flag entirely to skip it — behavior is identical to before
Section 117 existed.

Add `--enrich-bibliometric` (a boolean flag — no file to supply, since this hits
OpenAlex's live REST API rather than a downloaded snapshot) to also resolve this
run's PIs to OpenAlex authors and cross-check their co-authorship/affiliation
history (Epic E) against the same registered concern lists. `--openalex-contact-email`
is optional (OpenAlex's "polite pool" `mailto` parameter). Omit the flag entirely to
skip it — behavior is identical to before Epic E existed. See
`docs/data_sources.md`'s OpenAlex entry for a real, confirmed example of why a PI can
resolve to more than one tied OpenAlex author candidate, and why that's surfaced
rather than silently collapsed.

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
