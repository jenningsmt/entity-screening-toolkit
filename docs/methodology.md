# Methodology (Epic G)

Every pipeline run (`python -m entity_screening.cli run`, or `POST /runs` via the API)
writes a `RunManifest` to `data/processed/runs/<run_id>/manifest.json`. Every export —
CSV or Excel, from the CLI or the API's `/export.csv`/`/export.xlsx` — writes its own
`ExportManifest` to `data/processed/runs/<run_id>/exports/<export_id>/manifest.json`,
alongside the file itself. If ownership analysis (Epic C) has been run, a third
`GleifSnapshotManifest` lands at `data/processed/runs/<run_id>/ownership/manifest.json`.
If bibliometric enrichment (Epic E) has been run, a fourth
`BibliometricSnapshotManifest` lands at
`data/processed/runs/<run_id>/bibliometric/manifest.json`. If topic-similarity
ranking (the deferred VSS layer) has been run, a fifth `TopicSimilarityManifest`
lands at `data/processed/runs/<run_id>/topic_similarity/manifest.json`.
**These are five different manifests answering five different questions**, and the
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
- **`TopicSimilarityManifest`** applies the same reproducibility discipline to a
  new kind of external dependency: an embedding model. It records the exact
  HuggingFace model revision used (not just the model name — a bare name without a
  pinned revision is exactly the place this project's own reproducibility
  discipline could quietly slip), alongside both reference-corpus files' provenance.

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

## What `TopicSimilarityManifest` records

| Field | Meaning |
|---|---|
| `run_id` | Which run this topic-similarity ranking was computed for. |
| `computed_at` | UTC timestamp of the ranking call. |
| `embedding_model` / `embedding_model_revision` | The exact HuggingFace model and pinned revision used — see `entity_screening/bibliometric/embeddings.py`. |
| `dod_corpus_file` / `cet_corpus_file` | The exact bundled reference-corpus file paths used — see `docs/data_sources.md` for their real-document provenance. |
| `flags_count` | Total `TopicSimilarityFlag` rows persisted (a single paper can independently earn a primary-tier flag, a secondary-tier flag, both, or neither — see the corpus-independence note below). |

## Known limitations (V1 through V3)

- **Entity resolution is intra-source only.** `pipeline.py:resolve_entities_from_nsf`
  groups NSF award records into entities by exact match on a normalized awardee name;
  it does
  not yet attempt cross-source resolution beyond the screening step itself. A real
  alias that doesn't survive suffix-stripping/transliteration/acronym-expansion
  won't be grouped (see Epic B's normalization rules in `resolution/normalize.py`).
- **Screening uses a blocking step.** `screening/lists.py` only compares a candidate
  entity against entries sharing a 3-character normalized-name prefix *or* a
  3-character acronym-form prefix, to keep screening tractable against a large
  list (e.g. OpenSanctions' full target file). Both key types are indexed and
  queried specifically so an acronym reaches its full-name expansion and vice
  versa even when the two share no name-prefix at all — "IBM" and
  "International Business Machines" share no characters in that sense, which
  is the normal case for an acronym, not an edge case. (An earlier version of
  this build indexed only the name-prefix key, which meant `matcher.py`'s
  acronym scorer — one of Epic B's three named acceptance criteria — could
  only ever fire when a concern-list entry happened to already carry both the
  full name and the acronym as separate aliases; that gap is fixed as of this
  remediation pass and no longer applies.) What the blocking step still
  cannot reach: a genuine alias sharing neither a name-prefix nor an
  acronym-prefix with the entity (see the next bullet) — that remains a real,
  standard entity-resolution trade-off, not a bug, and is stated explicitly
  per Section 10's "known limitations" requirement.
- **Bare acronym/fuzzy matching can't catch a genuine alias with no shared
  characters** (e.g. a university's English name vs. an unrelated commonly-used
  short name in another language). That class of match is out of reach for string
  similarity alone and is a documented, not silently ignored, gap.
- **Scoring uses only the single highest-confidence hit per factor**, never a
  sum or a count — an entity with 1 hit at 0.95 confidence and an entity with
  40 hits at 0.95 confidence score identically. Deliberate, not an oversight
  (`scoring/score.py`'s module docstring): it stops the bibliometric layer's
  volume-multiplication (every co-author's institution across every one of a
  PI's papers gets checked, not one entity's own name once) from dominating
  the ranked table, at the cost of the table not distinguishing "one strong
  signal" from "a recurring pattern." A `hit_count` factor with a low default
  weight would recover that distinction if it's ever wanted.
- **Bibliometric hits score against their own `bibliometric_hit_weight`, not
  `screening_hit_weight`, as of this remediation pass.** A co-author's
  institution (or a PI's own past affiliation) matching a concern-list entry
  is a second-order signal compared to a direct name match against the
  entity itself; treating the two identically meant Epic F's "change the
  weighting if I disagree with it" couldn't express the single disagreement
  an analyst is most likely to have. `multiple_list_hit_bonus` correspondingly
  now counts distinct lists among *direct* hits only — a direct OpenSanctions
  hit plus a bibliometric co-author hit against DoD 1260H is one direct
  finding and one second-order inference, not "two independent lists
  corroborate." This is a real behavior change: a run's total score and
  factor breakdown for any entity with a bibliometric hit differs from a
  pre-remediation-pass run against the same data (see `ScoringRubric`'s
  `bibliometric_hit_weight` docstring for the default's reasoning).
- **This build covers all of V1, V2, and V3, plus the deferred VSS topic-similarity
  layer**: NSF Award Search, OpenSanctions, DoD's Section 1260H list, GLEIF
  ownership/foreign-control flagging (Epic C), the Section 117 foreign-funding
  disclosure cross-check, the OpenAlex bibliometric co-authorship/affiliation layer
  (Epic E) with the Seven Sons universities covered via OpenSanctions (no dedicated
  list — see `docs/data_sources.md`), and semantic ranking of PIs' real papers
  against real DoD/CET critical-technology reference corpora. Epic J (LLM-grounded
  explanations) remains a deliberately deferred, V3-adjacent follow-up
  (`docs/requirements.md` Section 9a) and is not reflected in any run's results.
- **Topic-similarity flags are advisory only and never appear in an export file.**
  `TopicSimilarityFlag` carries no `MatchStatus`, is never read by
  `scoring/score.py`, and — unlike screening hits and ownership flags — is not
  currently written into `output/export.py`'s CSV/Excel rows at all; it's visible
  only via the API's `/runs/{run_id}/topic-similarity` response and the Streamlit
  UI's own dedicated section. A published export's absence of a topic-similarity
  column does not mean none were found for that run — check
  `data/processed/runs/<run_id>/topic_similarity/manifest.json` separately.
- **The relative-ranking margin (`DEFAULT_MARGIN = 0.10`) is explicitly
  provisional**, calibrated from a real but small validation sample (2 true
  positives, 2 true negatives) while designing this feature — real, unrelated
  papers scored a false-positive-looking 0.59 raw cosine similarity against an
  unrelated DoD category, which is why the shipped design uses a margin (the gap
  between a paper's best and second-best match within one corpus) rather than an
  absolute cutoff; true positives led by ~0.11–0.13, the one real false positive
  found led by only ~0.045. A real end-to-end run against 58 actual papers from a
  real PI (Andrew Felton, Montana State University) correctly produced zero flags,
  with directly spot-checked real margins (0.008–0.047) staying well below the
  threshold — a genuine, verified null result, not an untested default. A larger
  real calibration pass is still needed before trusting this margin further.
- **The two reference corpora are ranked independently, never pooled** — DoD's 6
  full-sentence Critical Technology Area descriptions and the CET list's 18
  concatenated-fragment categories sit at different points in an
  embedding-similarity distribution for reasons unrelated to actual topical
  relevance, so a single paper can independently earn a primary-tier flag, a
  secondary-tier flag, both, or neither.
- **The DoD Critical Technology Areas corpus could not be verified directly against
  its own primary source.** `cto.mil` is unreachable from the environment this
  project was built in (the same DNS-blocking pattern already hit with
  `api.research.gov`); the bundled descriptions are cross-verified across multiple
  independent defense-trade sources instead. Re-verify the live `cto.mil/cta/`
  page's exact wording before treating `dod_critical_technology_areas.json` as
  authoritative for anything beyond this portfolio project.
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
- **A foreign-control flag inherits the uncertainty of three separate things, not
  one**: the name-to-LEI match; (if the walk to the ultimate parent was
  `truncated`) the fact that a deeper, undiscovered parent might exist beyond
  where the walk stopped; and, as of this remediation pass, branch ambiguity —
  a real GLEIF ownership graph can have more than one active
  `IS_DIRECTLY_CONSOLIDATED_BY` edge from a given entity, so the walk can
  genuinely produce more than one distinct chain to more than one distinct
  foreign ultimate parent (`ownership/graph.py:ParentChain.chains` is plural
  for exactly this reason). `pipeline.py:enrich_ownership` now emits one
  `ForeignControlFlag` per distinct foreign ultimate parent rather than
  picking one arbitrarily — a real ownership question can honestly have more
  than one answer, and collapsing that into a single flag either
  under-reported a genuine finding or attached a `relationship_path` that
  didn't exist in the data (an ordering artifact of the earlier flattened
  return shape). All three sources of uncertainty are surfaced in the flag's
  own `evidence`, not hidden behind a single confidence number.
- **A bibliometric run's works coverage can be capped, and a capped run's
  coverage is partial by design.** `bibliometric/openalex_client.py:get_author_works`
  pages with no limit by default and accumulates an author's entire works
  corpus in memory -- 456 works for Rod A. Wing (University of Arizona), the
  demo dataset's deliberately-included prolific real PI, three sequential
  round-trips. A caller (`enrich_bibliometric`) can pass `max_works_per_author`
  to bound both the network cost and the memory footprint; when it does, the
  bibliometric cross-check and the topic-similarity ranking that reads the
  same persisted works both only ever see that capped slice, never the
  author's full real history. The cap actually used is recorded in the run's
  own `BibliometricSnapshotManifest.max_works_per_author` — a silently
  truncated works history would otherwise be a reproducibility claim the run
  could no longer make, the same reasoning `ownership/graph.py:ParentChain.truncated`
  already applies to a bounded ownership walk.
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
8. If citing topic-similarity flags (not part of the CSV/Excel export — see the
   known-limitations note above; fetch them via
   `GET`-equivalent `POST /runs/{run_id}/topic-similarity` or the UI instead), locate
   `data/processed/runs/<run_id>/topic_similarity/manifest.json` for the exact
   embedding model revision and reference-corpus file paths used, then re-run
   `--enrich-topic-similarity` with `requirements-vss.txt` installed.
