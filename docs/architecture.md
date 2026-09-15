# Architecture (V1 through V3, plus the deferred VSS topic-similarity layer)

This describes the code as built for V1 through V3 (Epic C's GLEIF ownership graph
and foreign-control flagging, the Section 117 foreign-funding disclosure cross-check,
and Epic E's OpenAlex bibliometric co-authorship/affiliation layer, with the Seven
Sons universities covered via the existing OpenSanctions data rather than a
dedicated list), plus the semantic topic-similarity layer against real DoD/CET
critical-technology reference corpora originally deferred out of V3 (Section 9a's
DuckDB VSS proposal) — see `docs/requirements.md` Section 12 for the phased roadmap
and `docs/plans/2026-09-01-vss-topic-similarity-layer.md` for that layer's own plan.
Epic J (LLM-grounded explanations) is now built (`entity_screening/explanation/`,
`docs/plans/2026-09-15-epic-j-evidence-grounded-explanation.md`) against the HB127/COI
case worksheet's `Finding`/`ConcernTie` observations.

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

  A third, structurally different enrichment step -- advisory, never scored:
                 ┌──────────────────┐
  api.openalex   │ bibliometric/     │  reconstructs each paper's abstract
  .org (live)  ─▶│ embeddings.py     │  (OpenAlex has no plain abstract field,
                 │ topic_similarity  │  only a word-position index), embeds it
                 │ .py               │  (pinned BAAI/bge-small-en-v1.5), and
                 └──────┬────────────┘  ranks it against two real reference
                        │               corpora -- DoD's 6 Critical Technology
                        ▼               Areas, the White House OSTP's 18-
                 TopicSimilarityFlag    category CET list -- independently,
                                        never pooled into one ranking

  NOT fed into scoring/score.py, ever -- carries no MatchStatus, surfaced
  separately as "consult a subject-matter expert" advisory text. Requires
  enrich_bibliometric to have already run for this run_id.
```

`pipeline.py` exposes six entry points, each with a specific reproducibility
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
  OpenAlex calls or hits. Fetches each resolved author's works exactly once
  per run and persists them to `raw_openalex_works` keyed by
  `openalex_author_id` (optionally capped via `max_works_per_author`, recorded
  in the manifest below) — `enrich_topic_similarity` reads this same
  persisted copy back rather than re-fetching, which used to double OpenAlex
  traffic and wall-clock for the combined path. Never touches
  `scored_entities`; writes `openalex_author_matches`/new `ScreeningHit`s
  (tagged `producer="bibliometric"`, replaced rather than duplicated on a
  re-run — see the storage paragraph below) plus a durable, run-scoped
  `BibliometricSnapshotManifest`.
- **`enrich_topic_similarity(run_id, ...)`** — a **separate, explicit step**
  requiring `enrich_bibliometric` to have already run for this `run_id` (reads
  `openalex_author_matches` to know which PIs/authors to walk; raises a clear error
  otherwise). Ranks each real paper against the DoD/CET reference corpora
  independently (never pooled into one ranking — see
  `docs/plans/2026-09-01-vss-topic-similarity-layer.md`'s binding acceptance
  criteria). **Never touches `scored_entities` or `screening_hits`** —
  `TopicSimilarityFlag` carries no `MatchStatus` and is deliberately excluded from
  `scoring/score.py` entirely; a semantic-similarity signal can establish topical
  resemblance, not application or risk. Reads each resolved author's works from
  `raw_openalex_works` (persisted by the prior `enrich_bibliometric` call) rather
  than fetching live — this step makes no OpenAlex calls at all. Writes
  `paper_embeddings`/`topic_similarity_flags` plus a durable, run-scoped
  `TopicSimilarityManifest`.
- **`export_scored_entities(...)`** — writes a CSV or Excel file plus its own
  immutable `ExportManifest`, unconditionally, on every call. A downloaded file's
  score values are always traceable to the rubric that actually produced them, which
  is not necessarily the rubric recorded in the source run's `RunManifest`.

`common/storage.py` persists raw records, resolved entities, screening hits, scored
entities, and (if the corresponding `enrich_*` step has run) LEI matches, ownership
flags, OpenAlex author matches, each resolved author's raw OpenAlex works
(`raw_openalex_works`, keyed `(run_id, openalex_author_id)` — written once by
`enrich_bibliometric`, read back by `enrich_topic_similarity` rather than
re-fetched), paper embeddings, and topic-similarity flags into a
DuckDB file (DuckDB, not SQLite — see `docs/requirements.md` Section 7) for ad-hoc
querying alongside the file exports.

`screening_hits` is one table serving three producers with three different
lifecycles — `run_screening`'s direct name matching (`producer="direct_name"`),
its optional Section 117 cross-check (`"section_117"`), and `enrich_bibliometric`
(`"bibliometric"`) — only one of which (direct name matching, as part of a fresh
`run_screening` call) is genuinely append-once; the other two are independently
re-runnable against an existing `run_id`. `insert_screening_hits` groups an
incoming batch by the `producer` values actually present and deletes only
`WHERE run_id = ? AND producer = ?` for each before inserting, so re-running
`enrich_bibliometric` for a run replaces that run's bibliometric hits without
touching its direct-name or Section 117 hits. Embeddings are stored as plain `FLOAT[384]`
data, never via a persisted HNSW index — DuckDB's own docs flag on-disk HNSW
persistence as experimental (WAL crash-recovery isn't implemented for custom
indexes), so cosine similarity is computed directly via DuckDB's
`array_cosine_distance` function instead.

## Module map

| Package | Responsibility |
|---|---|
| `entity_screening/common/` | Canonical schema (`schema.py`), DuckDB storage (`storage.py`), run/export/GLEIF/bibliometric manifests — reproducibility (`manifest.py`) |
| `entity_screening/ingestion/` | Per-source ingesters (`nsf.py`, `opensanctions.py`, `dod_1260h.py`, `section_117.py`) implementing the `BaseIngester` streaming contract (`base.py`) |
| `entity_screening/resolution/` | Name normalization (`normalize.py`, including the Section-117-specific `strip_institutional_governance_affix`) and fuzzy scoring (`matcher.py`) |
| `entity_screening/screening/` | Entity-of-concern list registry (`lists.py`, registered: `OpenSanctionsList`, `DoD1260HList`), the screening pass (`screen.py`), the Section 117 two-stage cross-check (`section_117.py`), the bundled DoD 1260H curated snapshot (`data/dod_1260h.json`), the foreign-adversary-country list (`adversary_list.py`, `data/adversary_countries.json` — Use Case 01 step 4), and restricted-party screening (`rps_schema.py`/`rps_screen.py`/`rps_store.py`/`rps_service.py` — Use Case 02 step 5, a deliberately separate object graph from the case model, see `rps_schema.py`'s own module docstring) |
| `entity_screening/scoring/` | User-editable rubric (`rubric.py`, includes `foreign_control_weight`) and score decomposition (`score.py`) |
| `entity_screening/output/` | CSV/Excel export (`export.py`) |
| `entity_screening/ownership/` | GLEIF bulk ingestion (`ingest.py` — deliberately *not* a `BaseIngester`, see its module docstring), SQL-blocked LEI resolution (`match.py`), recursive graph traversal (`graph.py`), foreign-control flagging (`flagging.py`) — Epic C |
| `entity_screening/bibliometric/` | OpenAlex REST client with injectable fetch (`openalex_client.py`), live institution resolution (`institution_match.py`), PI-to-author disambiguation that can return several tied candidates (`author_resolve.py`), the co-authorship/affiliation cross-check (`cross_check.py`) — Epic E — plus the deferred VSS topic-similarity layer: a pinned embedding-model wrapper (`embeddings.py`) and the ranking logic against `data/dod_critical_technology_areas.json`/`data/cet_list.json` (`topic_similarity.py`). No NetworkX dependency, unlike `docs/requirements.md` Section 7's original guess: OpenAlex's own `works` endpoint already returns each paper's full `authorships` list directly, so checking co-authors/affiliations is flat list iteration, not graph traversal — that guidance was written before this project had seen the real API shape. |
| `entity_screening/pipeline.py` | Shared orchestration: `run_screening`, `rescore_run`, `enrich_ownership`, `enrich_bibliometric`, `enrich_topic_similarity`, `export_scored_entities` — called by both the CLI and the API |
| `entity_screening/cli.py` | `run` (full pipeline, calls `pipeline.py` in-process) and `validate` (structural sanity checks) |
| `entity_screening/api/` | FastAPI layer over `pipeline.py` — `main.py` (batch routes) + `case_routes.py` (Use Case 01) + `rps_routes.py` (Use Case 02, step 5) + `dto.py` (HTTP request/response models, kept separate from `common/schema.py`'s internal engine model) + `deps.py` (shared action-secret gate and path resolution `case_routes.py`/`rps_routes.py` both reuse without importing `main.py`, which would be circular; also the data-file allowlist helpers `rps_routes.py` uses — `case_routes.py` never accepts a caller-supplied file path at all, so it has no need of them) |
| `entity_screening/case/` | Use Case 01 (HB 127 researcher screening): the case model (`store.py`), worksheet/adjudication/lifecycle operations (`service.py`), the controlled reason-code vocabularies (`vocab.py` — discrepancies, concern ties, and restricted-party-screening dispositions, three separate sets), the investigative-file export (`export.py`), and the self-healing demo case (`demo.py`) |
| `entity_screening/reconciliation/` | Two statutory tests: `reconcile.py` produces `Finding`s (the §51B.153 omission test) from `discover.py`'s publication path; `discover.py`'s `tie_from_ownership` / `ties_from_own_affiliations` produce `ConcernTie`s (the §51B.151(b) tie test). `match.py` is the institution-name matcher shared by both |
| `entity_screening/explanation/` | Epic J — evidence-grounded explanation generation over `Finding`/`ConcernTie`: fully templated recitation (`skeletons.py`, no LLM call), the one allowed generative step (`generate.py` — a real Claude call behind an injectable `call` parameter, citation-grounded via the API's own document-citation feature), a forbidden-vocabulary check on generated prose (`lexicon.py`, the free-text analog of `common/schema.py`'s `_FORBIDDEN_OBSERVATION_FIELD_TOKENS`), and idempotent caching (`service.py`/`store.py`, keyed by observation id + evidence hash) |
| `app.py` + `ui_common.py` + `pages/` | Streamlit review UI: thin HTTP clients of the API, two separate visitor-facing views. `app.py` is a thin **router** — `st.set_page_config()`, then `ui_common.render_navigation()` (logo + the two nav buttons, via `st.navigation()`/`st.Page()`, replacing classic `pages/` filename auto-discovery so nav labels are explicit and the switcher can be styled/positioned), then `pg.run()`. `pages/0_HB127_Case_Worksheet.py` is the **HB 127 case worksheet** (the default page) — two sections (discrepancies, concern ties), each with its own disposition control and reason vocabulary, one closure rule over both. `pages/1_Restricted_Party_Screening.py` is the **restricted-party-screening** view (Use Case 02) — deliberately a separate page, not a section of the worksheet, mirroring `rps_schema.py`'s object-graph separation in the UI. `ui_common.py` factors the logo, the nav-button rendering, the sidebar config (API base URL, actor, action-secret gate), and HTTP helpers both pages share — see `docs/plans/2026-09-14-sidebar-navigation.md` |

## Use Case 01 — HB 127 researcher screening (the case path)

`docs/requirements.md` Section 9c moved the project's primary shape from
corpus-in/ranked-list-out to **subject-in / worked-worksheet-and-investigative-file-out**.
`docs/use-case-01-hb127-researcher-screening.md` is the specification;
`docs/plans/2026-09-06-use-case-01-implementation.md` and
`docs/plans/2026-09-06-concern-ties-as-a-distinct-observation.md` are the plans.

**Two statutory tests, two observation types.** §51B.153 bars employment on a *failure
to disclose* a substantial activity — a declaration-versus-record reconciliation, which
produces a **`Finding`**. §51B.151(b) requires a *background check for ties to a foreign
adversary* — a separate question, which produces a **`ConcernTie`** (a declared
employer's ultimate parent on a concern list; the subject's own affiliation history
matching a concern list). Forcing the second through the first mislabels it (the first
real export did exactly that). The worksheet carries both row types under one closure
rule.

```
  POST /cases (synthetic subject + declaration + coverage basis, recorded at intake)
        │
        ▼
  pipeline.reconcile_case ──▶ reconcile.py     ──▶ Finding   (per undisclosed discrepancy)
        │                     discover.py       ──▶ ConcernTie (per §51B.151(b) tie)
        ▼
  case/store.py (findings + concern_ties, current-state per case) + ReconciliationManifest (case_id only)
        │
        ▼
  GET /cases/{id}/worksheet ──▶ analyst actions on BOTH row types (own vocabularies), closure rule
        │
        ▼
  POST /cases/{id}/adjudication  (append-only)  +  /certifications  (§51B.153)
        │
        ▼
  GET /cases/{id}/investigative-file.json|.xlsx  (concern_ties before findings; redacted by default)
```

**The fact/judgment boundary** (use-case doc Section 4) is enforced the same way the
`MatchStatus` rule is: `common/schema.py`'s `Finding` and `ConcernTie`, and every type
in their graphs (`DiscoveredAffiliation`, `DeclarationSearch`, `NearestDeclared`), carry
**no** severity, risk, priority, score, materiality, tier, weight, disposition, or
"would prevent / impair" field. `_OBSERVATION_GRAPH_ALLOWED_FIELDS` is the frozen
per-type allowlist; `cli.py validate` fails CI if any of these types grows a field not
on it. The analyst's decision lives on a separate `WorksheetAction` / `TieAction` /
`Adjudication` record — including the §51B.151(b) "would not prevent" conclusion, which
is a `TieAction.reason_code` value (the human's call), not a schema field. `Subject` and
`Declaration` reject `synthetic=False` in `__post_init__` — this build handles no real
declaration data.

**The batch path is repositioned, not retired.** `pipeline.run_screening` and the
`/runs/*` routes stay callable for **population re-screening** against updated reference
data (use-case doc Section 5's periodic-sweep requirement); they are just no longer the
visitor-facing path. The identifier rename and the retirement of
`resolve_entities_from_nsf` are deferred to the point where the case path can produce a
closed, exported investigative file (Section 9c's stated trigger).

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

Add `--enrich-topic-similarity` (requires `--enrich-bibliometric` in the same
invocation — rejected with a clear error otherwise) to also rank this run's real
papers against the DoD/CET critical-technology reference corpora (the deferred VSS
work). **Needs `torch`/`sentence-transformers` installed** — deliberately *not* part
of the base `requirements.txt` install (see `requirements-vss.txt`), so every other
feature in this project, including the rest of Epic E, never forces a
multi-hundred-MB ML dependency nobody asked for:

```
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-vss.txt
```

Results are **advisory only** — `TopicSimilarityFlag` carries no `MatchStatus`,
never appears in `GET /runs/{run_id}/scores`, and is never blended into
`total_score`. Real validation while designing this surfaced a genuine false-
positive risk in a naive absolute-similarity cutoff (see
`docs/data_sources.md`'s CET/DoD-corpus entry) — the shipped default uses a
relative-ranking margin instead, computed independently within each corpus, and is
explicitly flagged there as provisional pending a larger real calibration pass.

**API + Streamlit UI (two processes):**

```
uvicorn entity_screening.api.main:app --reload
streamlit run app.py   # in a second terminal
```

`streamlit run app.py` still launches both views — `app.py` is a thin router
(`ui_common.render_navigation()`) that registers `pages/0_HB127_Case_Worksheet.py`
(default) and `pages/1_Restricted_Party_Screening.py` via `st.navigation()`/
`st.Page()` and renders them as two styled buttons under the logo, rather than
relying on Streamlit's classic `pages/`-directory auto-discovery (which derives
each label from its filename and pins a plain-link switcher above everything
else, with no supported way to move or restyle it). No separate command for the
restricted-party-screening page.

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
