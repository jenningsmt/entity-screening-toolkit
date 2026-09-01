# DuckDB VSS Semantic Topic-Similarity Layer (deferred from V3)

## Context

Section 9a proposed DuckDB's vector-similarity-search (VSS) extension for "semantic
matching over OpenAlex paper abstracts/titles... a real, defensible way to gain
vector-search experience," deferred out of the V3/Epic E plan since it needed its
own embedding-model decision and reference corpus that Epic E's core acceptance
criteria didn't require. This plan designs that deferred piece — and, following the
same discipline as every prior plan in this project, real data changed the design
substantially before any code was written.

### Finding 1: there was no real reference corpus to compare against — now there is

Unlike every other epic, which screens against a concrete external list
(OpenSanctions, DoD 1260H, GLEIF, OpenAlex institutions), "semantic similarity to
sensitive technology areas" had no corresponding real, sourced list in this
project's data sources. Two real government documents were acquired and inspected
directly (not designed from memory or secondhand summary) to fill that gap:

- **Primary corpus — the War Department's 6 Critical Technology Areas (Nov 17,
  2025 restructuring).** This is *not* the commonly-cited 14-area framework — that
  was narrowed to 6 as of this restructuring, and the current official page is now
  branded "War Department," not "Department of Defense." **`cto.mil` is unreachable
  from this sandboxed environment** (the same DNS-blocking pattern already hit with
  `api.research.gov` this project), so the exact area names, the November 2025 date,
  and the "War Department" branding were cross-verified across multiple independent
  defense-trade sources (DefenseScoop, Breaking Defense, AFCEA, ExecutiveGov,
  HSToday) rather than the primary page directly — **re-verify the live `cto.mil/cta/`
  page's exact wording at implementation time**, same caution as every other
  can't-fully-verify source in this project. Each of the 6 areas (Applied AI,
  Biomanufacturing, Contested Logistics, Quantum & Battlefield Info Dominance,
  Scaled Directed Energy, Scaled Hypersonics) carries a genuine one-to-two-sentence
  description — real, usable prose for both embedding and for showing an analyst
  *why* something got flagged.
- **Secondary corpus — the White House OSTP Critical and Emerging Technologies
  (CET) List, February 2024** (confirmed current — no newer version found).
  Downloaded and read directly (the real PDF, not a summary): **18 top-level
  categories, each with bulleted subcategories that are bare 2-4 word technical
  terms with zero prose anywhere in the document** ("Foundation models," "Synthetic
  data approaches for training, tuning, and testing"). A bare label embeds far more
  ambiguously than a full sentence, and the resulting evidence trail is much thinner
  ("similar to 'Foundation models'" tells an analyst little). **Treated as a
  secondary, explicitly lower-confidence supplementary signal, never pooled with the
  DoD corpus as equivalent quality** — and each CET category is embedded as one
  passage concatenating all of its subfield terms together, not per-subfield, to
  give the embedding more to work with than a 2-3 word fragment alone.

### Finding 2: OpenAlex has no plain abstract field, and 18% of real papers have none

Pulled real OpenAlex work records directly: there is no `abstract` string field at
all, only `abstract_inverted_index` (a word→position-list map — publishers'
copyright terms don't allow OpenAlex to republish plain abstract text). Reconstructing
plain text from it is a straightforward positional sort-and-join, verified against 5
real papers (reconstructed text read as coherent, correct English). In a real 50-work
sample (Montana State University), **9 of 50 (18%) had no abstract at all** — those
works are skipped for topic-similarity purposes, same "known limitation, stated
plainly" posture as every other real coverage gap in this project. OpenAlex also
already ships its own `primary_topic`/`concepts`/`keywords` classification per work —
a legitimate simpler alternative that was considered and set aside, since Section 9a's
actual intent was specifically to demonstrate real vector-search/embedding
engineering, not to relabel OpenAlex's own pre-computed tags.

### Finding 3: DuckDB VSS itself works, but persisting the index is a real crash risk

Verified live in this environment (already-installed DuckDB 1.5.5): `INSTALL vss;
LOAD vss;` succeeds, `array_cosine_distance` and `CREATE INDEX ... USING HNSW` both
work. But DuckDB's own current documentation is explicit that **HNSW index
persistence to disk is experimental specifically because WAL crash-recovery isn't
implemented for custom indexes** — an unexpected shutdown with uncommitted changes to
an HNSW-indexed table can corrupt the index, and index serialization is
non-incremental (the whole index is rewritten on every checkpoint). This project's
main DuckDB file is a long-lived, persistent working file, not disposable — the same
category of risk this project has avoided elsewhere (e.g. GLEIF's `gleif_lei`/
`gleif_relationships` are a disposable, rebuilt-per-call working copy, never treated
as durable). **Resolution: persist the embedding *vectors* as plain `FLOAT[384]`
columns in a durable table (safe — no custom-index WAL risk, it's just data); build
the HNSW index ephemerally in memory per query call from those persisted vectors,
never on disk.** This mirrors the GLEIF pattern exactly: durable underlying data,
disposable derived working structure.

### Finding 4: the embedding model choice, and what real validation shows

This is an asymmetric retrieval problem — a short technology-area description
compared against a long paper abstract — not symmetric sentence-similarity, so a
general default (e.g. `all-MiniLM-L6-v2`) is the wrong shape of tool.
**`BAAI/bge-small-en-v1.5`** (384-dim, ~130MB, CPU-only) is built for exactly this
query-vs-passage pattern via an instruction prefix on the query side only
(`"Represent this sentence for searching relevant passages: "` on the short CTA
description; plain text on the long abstract). Pinned to its exact HuggingFace
revision for reproducibility (the same discipline as `GleifSnapshotManifest`
recording dataset versions): **`5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`**.
Installed via the CPU-only PyTorch wheel
(`pip install torch --index-url https://download.pytorch.org/whl/cpu`) to avoid
pulling unneeded CUDA binaries — neither `torch` nor `sentence-transformers` were
previously installed; this is a genuinely new, sizable dependency (comparable in
scale to the GLEIF/OpenSanctions storage decisions already made deliberately in
`docs/requirements.md` Section 8).

**Real validation run** (2 true positives, 2 true negatives — a real but small
sample, see the binding verification item below): a real hypersonics-vehicle
abstract scored highest against "Scaled Hypersonics" (0.70), clearly ahead of every
other category (next-highest 0.57); a real quantum-computing abstract scored highest
against "Quantum and Battlefield Information Dominance" (0.66), also clearly ahead
(next-highest 0.54). **But a real, unrelated climate-science abstract (Andrew
Felton's own real rangeland-ecology paper) scored 0.59 against "Biomanufacturing"** —
higher than either true positive's own second-best category, and not obviously
separable from a true positive by an absolute cosine-similarity cutoff alone.
**Conclusion, confirmed by real data rather than assumed: this needs a
relative-ranking rule (the top match must lead the field by a real margin), not a
single absolute threshold** — exactly the kind of measured, real-data-calibrated
decision this project has made everywhere else (Section 117's institution threshold,
the bibliometric concern-threshold fix). The exact margin needs a larger real
validation pass during implementation (see binding verification below) before being
trusted as a default.

### The output-shape decision: an advisory flag, not a scored hit

A semantic-similarity signal can establish that a paper's topic *resembles* a
technology-area description; it cannot establish that the paper has a military
application or that any actual risk exists — that judgment call genuinely needs a
subject-matter expert, not this system. So a topic-similarity result is
**deliberately not a `ScreeningHit`, does not carry a `MatchStatus`, and does not
feed `score_entity()`'s numeric score at all** — it's a separate, parallel advisory
output ("flagged for expert review"), never blended into or contaminating the scored
pipeline the way a real concern-list match legitimately does.

## Architecture

A third live-external-source enrichment step, alongside `enrich_ownership` and
`enrich_bibliometric`, but producing a structurally different kind of output
(advisory, not a match) and gated behind an optional new dependency
(`torch`/`sentence-transformers`) the rest of the project doesn't need — so it's its
own separate, optional pipeline step, not folded into `enrich_bibliometric`.

- **New bundled reference-corpus files** (static, hand-curated, same posture as
  `screening/data/dod_1260h.json` — small, not-machine-native, periodically-updated
  government documents, not worth building download infrastructure for):
  - `entity_screening/bibliometric/data/dod_critical_technology_areas.json` — the 6
    real areas with their real descriptions, a `provenance` field naming the
    November 2025 restructuring, the secondary sources used (since `cto.mil` itself
    was unreachable), and a note to re-verify against the live page.
  - `entity_screening/bibliometric/data/cet_list.json` — the 18 real categories,
    each with its subfields concatenated into one passage per category, a
    `provenance` field naming the real Feb 2024 OSTP PDF, and an explicit
    `confidence_tier: "secondary"` field distinguishing it from the DoD corpus.
- **`bibliometric/embeddings.py`** — thin wrapper: `embed_query(text)` (applies the
  bge instruction prefix), `embed_passage(text)` (plain), both backed by a pinned
  `SentenceTransformer("BAAI/bge-small-en-v1.5", revision="5c38ec7c...")`. An
  injectable embed function, mirroring `openalex_client.py`'s `FetchFn` pattern, so
  most tests never load the real model.
- **`bibliometric/topic_similarity.py`** — `reconstruct_abstract(abstract_inverted_index)`
  (Finding 2's positional sort-and-join); `compute_topic_similarity_flags(entity_id,
  resolved_authors, dod_corpus, cet_corpus, fetch, embed_fn, margin, ...)`: fetches
  each resolved author's works (reusing `openalex_client.get_author_works`,
  same as `cross_check_bibliometric`), reconstructs abstracts, skips works with none
  (Finding 2), embeds each, and applies the relative-ranking decision rule from
  Finding 4 **independently within each corpus** — see "Resolved during review"
  below for why pooling both corpora into one ranking would be a real bug, not a
  simplification.
- **New schema type**: `TopicSimilarityFlag` in `common/schema.py` — deliberately
  **no `MatchStatus`** (see "output-shape decision" above): `entity_id`, `pi_name`,
  `openalex_work_id`, `work_title`, `technology_area`, `corpus_tier` ("primary" /
  "secondary"), `similarity_score`, `evidence` (dict: the embedding model revision,
  the reconstructed-abstract excerpt actually compared, the runner-up categories and
  their scores so the margin that triggered the flag is visible, not hidden — same
  self-contained-evidence discipline as every other type), and a fixed
  `recommendation` field whose value is always something like "Topically similar to
  a named critical-technology area; consult a subject-matter expert to assess actual
  relevance — this signal establishes topical resemblance only, not application or
  risk."
- **New storage table**: `topic_similarity_flags` — entirely separate from
  `screening_hits`; never read by `score_entity()`.
- **New manifest type**: `TopicSimilarityManifest` in `common/manifest.py` — records
  `run_id`, `computed_at`, the embedding model name + pinned revision, both corpus
  files' provenance, and `flags_count`. Same durable, run-scoped, "current state"
  pattern as `BibliometricSnapshotManifest`.
- **`pipeline.py`**: new `enrich_topic_similarity(run_id, *, margin=..., db_path=...,
  runs_dir=..., fetch=None, embed_fn=None)` — requires `enrich_bibliometric` to have
  already run for this `run_id` (reads `openalex_author_matches` to know which PIs/
  authors to walk); does not touch `scored_entities` or `screening_hits`.

## Resolved during review — binding acceptance criteria

Two gaps raised on review, folded in now so they don't get lost between approval and
implementation (same discipline as every prior plan's review cycle in this project):

**1. Rank within each corpus independently — never pool DoD and CET into one
comparison.** DoD's 6 areas are full-sentence descriptions; CET's 18 are
concatenated multi-term fragments (Finding 1). Short/fragment-like and
long/sentence-like text sit at different points in an embedding-similarity
distribution for reasons that have nothing to do with actual topical relevance —
pooling all 24 candidates into one ranking risks a CET category out- or
under-ranking a DoD category purely on this text-length artifact, quietly
undermining the tier separation the rest of this plan is careful to preserve
elsewhere (a single flag's own evidence already keeps `corpus_tier` distinct; this
is the same discipline applied one level up, to the ranking decision that decides
whether a flag fires at all). Fix: `compute_topic_similarity_flags` computes the
top-match-vs-runner-up margin **twice, independently** — once within DoD's 6, once
within CET's 18 — never as one 24-way comparison. A single work can independently
clear the primary-tier rule, the secondary-tier rule, both, or neither. Today's real
validation is already consistent with this scoping (the climate-paper false
positive was checked only within DoD's 6, never pooled against CET), so this makes
an already-correct implicit choice explicit and intentional rather than leaving it
to be gotten wrong later by accident.

**2. Measure flag volume, not just hand-picked-pair precision.** The bibliometric
cross-check's own real bug — 27 false positives from one fuzzy collision, recurring
across every co-author on every paper — was a volume-multiplication problem
invisible in a small hand-checked sample and only caught once it ran at real scale.
The same risk applies here: a prolific PI's large body of work could generate a wall
of advisory flags that overwhelms rather than helps a reviewer, defeating the
advisory design's whole purpose even if every individual flag is precisely correct.
Binding verification item 3 below is revised accordingly.

## Real-data verification still needed during implementation (binding, not optional)

1. **Re-verify `cto.mil/cta/`'s exact live text directly** before finalizing
   `dod_critical_technology_areas.json`'s bundled descriptions — this plan's account
   is cross-verified across multiple secondary sources but the primary page itself
   was unreachable from this sandboxed environment.
2. **Calibrate the relative-ranking margin against a real sample meaningfully larger
   than 2 true positives / 2 true negatives** before trusting a specific default —
   today's validation confirms the *shape* of the right rule (margin-based, not an
   absolute cutoff, computed per-corpus per binding criterion 1 above) but 4 data
   points isn't enough to set the actual number with confidence.
3. **Real precision check, including flag volume, not just correctness on hand-picked
   pairs**: run `enrich_topic_similarity` against a real, broader set of resolved
   PIs' real papers and record both what's actually flagged (including "nothing
   flagged," a valid, worth-stating result) *and* flags-per-PI / flags-per-run
   counts — a prolific real PI producing an unreadable wall of flags is exactly the
   kind of at-scale failure a small hand-checked sample won't surface, the same
   lesson the bibliometric cross-check's 27-false-positive bug already taught this
   project once.

## CLI / API / UI surface

- CLI `run`: new `--enrich-topic-similarity` boolean flag; errors clearly if
  `--enrich-bibliometric` wasn't also requested in the same invocation (the ordering
  dependency above).
- API: new `POST /runs/{run_id}/topic-similarity` route, mirroring the existing
  enrichment routes' shape.
- `app.py`: a visually distinct section (not folded into the scored table) —
  "Topic-similarity flags (advisory — not a scored match)" — listing each flag's
  `recommendation` text plainly, with the corpus tier and runner-up categories
  visible, never presented alongside `total_score`.

## Tests

- Unit tests for `reconstruct_abstract` against real captured `abstract_inverted_index`
  samples (including a real work with no abstract, proving it's correctly skipped).
- `topic_similarity.py` tests using an injectable `embed_fn` (deterministic fake
  vectors) for the decision-rule logic (margin threshold, corpus-tier tagging,
  evidence self-containment) — no model load in most tests. Includes a dedicated
  test proving the two corpora are ranked independently: a fake embedding
  constructed so a CET fragment would out-rank a DoD sentence under a pooled 24-way
  comparison, asserting the DoD-side flag still fires correctly on its own
  within-DoD margin regardless (i.e., pooling never actually happens).
- One real-model integration test (mirroring
  `test_dod_1260h_default_bundled_file_exists_and_parses`'s "guard the real bundled
  artifact" role): loads the actual pinned `bge-small-en-v1.5` revision and re-runs
  today's exact real validation pairs (hypersonics/quantum true positives, the two
  real climate-paper true negatives), asserting the true positives still rank their
  correct category highest — a regression guard against a future model/revision
  change silently breaking real discrimination.
- Pipeline test proving `enrich_topic_similarity` never writes to `scored_entities`
  or `screening_hits`, and fails clearly if `enrich_bibliometric` hasn't run yet.
- The real-data verification pass above, run once, before calling this done.

## Explicitly out of scope for this pass

Fine-tuning or training any embedding model — only a pretrained, pinned model is
used. Expanding the reference corpus beyond the two real documents acquired here.
Any change to `score_entity()`/the scoring rubric — topic-similarity flags are
deliberately advisory-only and never touch scoring, by design, not by omission.
Epic J (LLM-grounded explanations) — still its own separate future plan.

## Verification

- `pytest -q` — full suite plus the new topic-similarity test files.
- `python -m entity_screening.cli run ... --enrich-bibliometric --enrich-topic-similarity`
  against a real NSF PI with real papers — confirms `topic_similarity_flags` is
  populated (or genuinely empty, both valid outcomes) and the manifest is written.
- The real-data verification pass above, before calling this done.
