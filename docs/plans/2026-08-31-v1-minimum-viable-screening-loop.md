> Reconstructed from the conversation transcript that approved it — the original
> plan-mode file this was written to (`~/.claude/plans/proud-mixing-magpie.md`) was
> overwritten by the next plan-mode session before this `docs/plans/` directory
> existed. Content below is the plan as approved, verbatim from that transcript.

# Entity & Research-Affiliation Screening Toolkit — V1 Implementation Plan

## Context

`docs/requirements.md` is a complete, approved-for-review spec (status: Draft for review) for a portfolio project that reproduces, at hobby scale, entity-resolution and foreign-affiliation due-diligence screening against open data. The repo currently contains only an empty package skeleton (`entity_screening/{bibliometric,ingestion,ownership,resolution,scoring,screening}/__init__.py`, all empty) and `requirements.txt` (duckdb, pandas, pyarrow, rapidfuzz, streamlit, requests, pytest). Nothing has been built yet.

Per the requirements doc's own Section 12 roadmap and Section 11 risk note ("resist the urge to build all nine datasets before shipping anything"), and confirmed with the user, **this plan covers V1 only**: the minimum viable screening loop — NSF award data + OpenSanctions + fuzzy resolution + confidence scoring + CSV export + core tests. V2 (GLEIF ownership graph, Section 117) and V3 (OpenAlex bibliometric layer) are out of scope for this plan; the `ownership/` and `bibliometric/` packages stay empty stubs.

The requirements doc repeatedly invokes patterns "already proven" in named sibling repos. All three reachable siblings were inspected before writing this plan (a fourth, `ed-expedition-ledger`, wasn't reachable on disk):
- **`ed-colony-scout`** (G:\ed-colony-scout): flat repo, no pip packaging, scoring implemented as a frozen dataclass rubric (`STOCK_RUBRIC`) with dict-based user overrides, per-factor scores kept as flat fields alongside the total, argparse CLIs, stdlib unittest.
- **`ring-density-monitor`** (G:\ring-density-monitor): reproducibility done via a provenance/run-manifest mechanism (run_id, score_version, params_json, git_commit, dataset snapshot counts/dates recorded in docs and DB), deterministic ordering rules, streaming ingestion of large dumps, flat pytest `tests/` dir.
- **`ed-sector-surveyor`** (on disk at G:\sector-gap-analyzer — same project, renamed mid-life; its PyInstaller `dist/` output is literally named `SectorSurveyor`/`EDSectorSurveyor`): the actual 108GB-dump streaming pattern is `ijson.items(handle, "item")` over a binary-mode (optionally gzip) file handle, never materializing the JSON array, paired with independent size-gated batch-flush thresholds (`DEFAULT_COMMIT_EVERY_SYSTEMS=20000`, etc.) so peak memory stays bounded regardless of file size. **Important gap, not a match**: this sibling's actual error handling is `except json.JSONDecodeError: continue` with no log line and no counter, and it has zero per-record provenance tagging (no `source_id`/`retrieved_at` columns) and zero test coverage on the ingestion scripts. So Epic A's "log failures, don't drop them" and "retain source dataset/retrieval date/source-record id" acceptance criteria, and Epic H's ingestion test coverage, are **new bars this project sets for itself** — real engineering to design, not something to copy from the cited precedent.

This project already diverges from all three siblings in ways the requirements doc mandates explicitly: DuckDB/Parquet instead of SQLite, Streamlit instead of Tkinter, and pytest instead of unittest (Epic H says "pytest suite" outright, and only `ring-density-monitor` already used pytest). The plan below keeps the parts of the sibling patterns that still apply (dataclass-based user-editable rubric with per-factor breakdown; a concrete run-manifest for reproducibility; ijson-style streaming reserved for genuinely large single-file JSON dumps) and adapts or exceeds the rest, per the gap noted above. It also keeps the existing package skeleton as the source layout (no pip packaging, no `pyproject.toml` — run via `python -m entity_screening.cli` and `streamlit run app.py`, consistent with how all three siblings are actually run).

## Scope mapping to epics (Section 6)

V1 build order, each phase independently testable:

1. **Epic A — Ingestion**: NSF Award Search API + OpenSanctions `targets.simple.csv`, common schema, streaming, error logging.
2. **Epic B — Resolution**: normalization + rapidfuzz matching + known-difficult regression fixture.
3. **Epic D — Screening**: pluggable entity-of-concern list registry, OpenSanctions wired up for V1 (DoD 1260H / Seven Sons remain unwired stubs for V3, per roadmap — the registry is built generic now so adding them later is additive, not a refactor).
4. **Epic F — Scoring**: editable-weight rubric with per-factor breakdown, "candidate match" status baked into the type system.
5. **Epic G — Output**: CSV/Excel export + run manifest (the reproducibility/methodology mechanism).
6. **Epic H — Testing**: pytest suite, known-difficult regression set, `--validate` CLI mode.
7. **Epic I — Docs**: README already has the non-goals-first framing; add architecture, methodology template, and data-source license/attribution docs.
8. **Epic C / E** (ownership graph, bibliometric): explicitly deferred to V2/V3 — not touched.

## New structure to add

```
entity_screening/
  common/
    __init__.py
    schema.py       # canonical dataclasses: SourceRecord, ResolvedEntity, MatchCandidate,
                     # ScreeningHit, ScoredEntity; MatchStatus enum with a single member
                     # CANDIDATE_MATCH — structurally impossible to emit "confirmed"
    storage.py       # DuckDB connection + schema DDL + Parquet read/write helpers
    manifest.py      # RunManifest dataclass (run_id, started_at/finished_at, git_commit,
                      # dataset snapshot versions/dates/record counts, rubric snapshot,
                      # match thresholds) -> data/processed/runs/<run_id>/manifest.json
  ingestion/
    base.py           # BaseIngester: stream_records() contract; tags every record with
                      # source_dataset, retrieval_date, source_record_id (net-new — no
                      # sibling repo does per-record provenance tagging at ingestion time);
                      # uses Python's `logging` (not print()) to write malformed records to
                      # data/processed/runs/<run_id>/ingestion_errors.jsonl with the raw
                      # content + reason, plus an end-of-run failure count — deliberately
                      # stricter than ed-sector-surveyor's silent `except: continue`
    nsf.py            # NSF Award Search API client -> raw_nsf_awards (DuckDB table)
    opensanctions.py  # streams targets.simple.csv via DuckDB's read_csv_auto (columnar
                      # streaming engine — the "don't load to memory" requirement is met
                      # by DuckDB's own I/O layer here; V1's largest file (434MB) doesn't
                      # need ijson's hand-rolled chunking, which is reserved as the pattern
                      # to reach for if a future large single-file JSON dump is added)
  resolution/
    normalize.py      # corporate-suffix normalization (Inc./LLC/Ltd.), acronym expansion,
                      # transliteration normalization (unidecode)
    matcher.py         # rapidfuzz-based scorer -> MatchCandidate with a confidence score
                        # (never a bare bool)
  screening/
    lists.py           # EntityOfConcernList ABC + registry; OpenSanctionsList is the only
                        # registered impl in V1
    screen.py           # runs resolved entities against every registered list -> ScreeningHit,
                        # each tagged with which list produced it + matched field/variant
  scoring/
    rubric.py           # ScoringRubric frozen dataclass + STOCK_RUBRIC default; to_dict/
                        # from_dict for user overrides (JSON file for CLI, Streamlit sliders
                        # for the UI) — mirrors ed-colony-scout's rubric pattern
    score.py            # per-factor breakdown + total; decomposition always available, never
                        # collapsed to an opaque number
  output/
    __init__.py
    export.py           # CSV/Excel export: candidate matches, confidence, evidence,
                        # source citations, run_id back-reference
  cli.py                 # argparse subcommands: ingest / resolve / screen / score / export /
                        # run (full pipeline) / validate (structural sanity checks, per Epic H)
app.py                   # Streamlit entry point: scored/filterable/explainable table +
                          # rubric weight sliders (repo root, `streamlit run app.py`)
docs/
  architecture.md         # pipeline-stage breakdown (Epic I)
  methodology.md           # template populated from manifest.json per published run:
                            # snapshot dates, thresholds, known limitations
  data_sources.md          # per-source license/attribution (OpenSanctions, NSF, U.S. gov works)
tests/
  fixtures/
    known_difficult_pairs.yaml   # Epic B regression set: true positives that look different,
                                  # true negatives that look similar
    sample_nsf_awards.json        # tiny synthetic fixture, not real bulk data
    sample_opensanctions_targets.csv
  test_normalize.py
  test_matcher.py              # parametrized over known_difficult_pairs.yaml
  test_screening.py
  test_scoring.py
  test_ingestion.py
  test_manifest.py
  test_cli_validate.py
```

`ownership/` and `bibliometric/` stay as their current empty stubs — not deleted (V2/V3 will fill them), not built out.

## Key design decisions worth flagging

- **"Candidate, never confirmed" is a type, not a convention.** `MatchStatus` in `common/schema.py` has exactly one value. Every hit-producing code path returns that type, so there's no code path that could emit a "confirmed" status even by mistake — directly satisfying the Section 10 non-functional requirement ("enforced in the data schema... not left to documentation").
- **Reproducibility via `RunManifest`, mirroring ring-density-monitor's provenance table but file-based** (no long-lived DB in V1's small scale): every `entity_screening.cli run` invocation writes one manifest JSON capturing exactly which snapshot of NSF/OpenSanctions was used, when, and what rubric/thresholds were active. `output/export.py` stamps every exported row's run_id against it, so a CSV row is traceable back to the exact inputs that produced it — this is also the concrete mechanism behind the Epic G "companion methodology document."
- **Screening list registry is generic from day one**, even though only OpenSanctions ships in V1, specifically so the 1260H and Seven Sons lists (Epic D acceptance criteria mentions all three, but the roadmap sequences them into V3) slot in later as new `EntityOfConcernList` implementations without touching `screen.py`.
- **No pip packaging.** Matches both inspected siblings' convention (no `pyproject.toml`/`setup.py`) and this repo's own existing `requirements.txt`-only setup. Run via `python -m entity_screening.cli <subcommand>` and `streamlit run app.py`.
- **pytest, not unittest** — this deviates from ed-colony-scout on purpose because Epic H explicitly names pytest and `ring-density-monitor` already uses it; `requirements.txt` already lists `pytest`.

## Verification

- `pip install -r requirements.txt`
- `python -m entity_screening.cli ingest --source nsf --source opensanctions` against the tiny fixtures (or a size-capped real pull) to confirm streaming ingestion + provenance tagging + malformed-record logging.
- `pytest` — full suite including the known-difficult regression set in `tests/test_matcher.py`.
- `python -m entity_screening.cli validate` — structural sanity check mode (Epic H).
- `python -m entity_screening.cli run` end-to-end against fixtures, confirm a manifest JSON and a CSV export are produced, and that every row's status is `candidate_match`.
- `streamlit run app.py` — manually confirm the scored/filterable table renders, weight sliders re-score visibly, and every result shows its evidence/source trail.

---

### What actually shipped vs. this plan

Implementation stayed close to this plan, with a few real deviations worth noting
(see `docs/architecture.md` and `docs/methodology.md` for the as-built shape):
- `known_difficult_pairs.yaml` became `.json` — avoided adding `pyyaml` as a
  dependency purely for a small regression fixture.
- Two real bugs were found and fixed only by actually running the code, not from the
  plan alone: an acronym-matching bug (computing acronyms before stripping
  "Corporation" broke IBM/ZTE-style matches) and a Windows-default-encoding bug in
  `read_text()` calls that silently corrupted accented fixture text.
- `common/storage.py`'s DuckDB persistence was defined per-plan but not actually
  wired into the CLI pipeline until this was caught during a review pass — a real gap
  between "planned" and "built" worth naming rather than glossing over.
