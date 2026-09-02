# Monops — End-to-End Codebase Evaluation Against `docs/requirements.md`

**Date:** 2026-09-02
**Reviewed at:** `40ca51b` (branch `master`, clean)
**Reviewer:** Claude (Cowork session)
**Scope:** every module under `entity_screening/`, `app.py`, `tests/`, `.github/workflows/`, `infra/`, `docs/`, evaluated against `docs/requirements.md` Sections 2, 6 (Epics A–J), 7, 9/9a/9b, and 10.

---

## 1. Method

Every source file in the package was read in full (≈4,400 LOC of application code, ≈4,000 LOC of tests). Claims in this report that concern runtime behavior were **executed, not inferred** — the suite was run and targeted probe scripts were written against the real modules. Where a finding is empirical, the observed output is quoted.

Test suite result in this session's sandbox: **157 passed, 1 skipped, 7 failed**. All 7 failures are environmental, not defects: 6 need DuckDB's `vss` extension (blocked by the sandbox's HTTP proxy), 1 needs a `.git` directory. This is consistent with the 167-pass figure on your machine.

---

## 2. Verdict

This is, on the engineering merits, a strong codebase — meaningfully stronger than the requirements doc asked for in documentation discipline, provenance, and honesty about limitations. The things it does best are exactly the things the FinchAI framing in Section 1 cares about, and they are done structurally rather than cosmetically.

There are also **four real defects** and **three acceptance-criteria gaps**, all fixable in a focused day. One of them (Finding 1) means a named Epic B acceptance criterion does not actually hold end-to-end, and the test suite does not catch it because it tests the wrong seam.

### Scorecard

| Epic | Verdict | Note |
|---|---|---|
| **A** — Ingestion & Normalization | ✅ Met | Streaming, provenance-tagged, errors logged and counted. Best-in-class relative to the ED-tool baseline it cites. |
| **B** — Entity Resolution & Alias Matching | ⚠️ **Partially met** | Acronym matching, one of three named criteria, is unreachable through the actual screening path (Finding 1). "Transliteration" is accent-folding only. |
| **C** — Ownership & Affiliation Graph | ⚠️ Mostly met | Depth/direction are genuinely queryable and `truncated` is honest. Branching and cyclic graphs are silently flattened (Finding 5). |
| **D** — Entity-of-Concern Screening | ⚠️ Mostly met | All three lists covered; every hit scored and status-constrained. But `matched_field` — named in the criterion — never reaches any output (Finding 4). |
| **E** — Bibliometric Affiliation Layer | ⚠️ Mostly met | Disambiguation is excellent and honest about ties. The OpenAlex precision caveat is UI-only, not "alongside every result" (Finding 6). |
| **F** — Scoring & Explainability | ✅ Met | Weights user-editable via three surfaces; every total decomposes. One design question below. |
| **G** — Output & Reporting | ✅ Met | Export + `ExportManifest` per call is better than the criterion asked for. |
| **H** — Testing & Validation | ⚠️ Mostly met | 167 tests, real CI incl. a Docker integration job, `validate` subcommand. The known-difficult set tests the scorer in isolation, not the screening path — which is why Finding 1 shipped. |
| **I** — Packaging & Documentation | ✅ **Exceeds** | Non-goals lead the README; per-source licensing is complete; architecture doc is genuinely good. |
| **J** — Evidence-Grounded Explanation | ➖ Deferred by design | Correctly out of scope. The Section 9a schema-discipline prerequisite **is** done and is tested (`test_evidence_is_self_contained_without_a_further_join`). |

### Non-functional requirements (Section 10)

| NFR | Verdict |
|---|---|
| Explainability first | ✅ Met |
| Confidence over booleans | ✅ Met |
| Language discipline ("candidate", never "confirmed") | ✅ **Met structurally** — `MatchStatus` with one member makes the alternative unrepresentable. This is the single best decision in the codebase. |
| Reproducibility | ✅ Met — five distinct manifests, `git_commit` baked into the container, pinned embedding-model revision |
| Batch-first, not live-dependent | ⚠️ Partially — Epic E and the VSS layer are live-API-dependent by construction. Documented, but it is a real departure from the stated NFR. |
| Streaming at scale | ⚠️ Mostly — NSF/OpenSanctions/GLEIF all stream or bulk-load correctly. `get_author_works()` accumulates an author's entire works corpus in a Python list with no cap (Finding 7). |
| License compliance **surfaced in output** | ⚠️ Partially — fully documented in `docs/data_sources.md`; not present in any exported row. Same one-line fix as Finding 6. |

---

## 3. What is genuinely strong

Stating these plainly because they are the parts worth pointing at in an interview, and because the findings section below is longer.

1. **`MatchStatus` as a single-member enum.** Section 10 asked for language discipline "enforced in the data schema." Most implementations would have written a docstring. This makes "confirmed" a compile-time impossibility across resolution, screening, ownership, bibliometric, scoring and export, and then asserts it in `cli.py validate` so CI fails if anyone widens it. That is the difference between a claim and a mechanism.

2. **`TopicSimilarityFlag` deliberately carries no `MatchStatus` and is never read by `score.py`.** Refusing to blend an advisory semantic signal into a numeric risk score — and encoding that refusal in the type rather than in a convention — is a better judgment call than most production systems make.

3. **The manifest family.** Five manifests answering five different questions, with the `ExportManifest`-vs-`RunManifest` distinction explicitly reasoned about because re-scoring can drift from the run's original rubric. `GleifSnapshotManifest`'s "run A's flags must survive run B replacing the shared tables" reasoning is a real bug class caught in design rather than in production.

4. **Real bugs found by real data, and documented as such.** The `api.research.gov` DNS death, the OpenAlex 429 crash, the `Chinese Academy of Sciences` → `Chinese Academy of Ordnance Science` 0.8387 false positive that drove the bibliometric threshold to 0.90, the GLEIF CSV-vs-XML column-name trap, Section 117's merged title row and 11% content-duplicate rows. Each is written down with the evidence. This is the strongest signal in the repo that the work was actually done against real data.

5. **`docs/methodology.md`'s known-limitations section.** Sixteen limitations, several genuinely unflattering, none hedged. Including a *documented residual gap* as an asserted test (`test_strip_institutional_governance_affix_documented_residual_gap`) so that accidentally fixing it gets noticed is a level of discipline I rarely see.

6. **CI that tests the thing that actually broke.** The Docker job doesn't just check both containers are "up" — it execs into the Streamlit container and curls the API by compose service name, because that is the exact regression that shipped once. Then it asserts real result counts *and* that `git_commit` is a real SHA, not null.

---

## 4. Findings

Ranked by consequence. Every one was reproduced.

---

### Finding 1 — Acronym matching is unreachable through the screening path (Epic B acceptance criterion not met)

**Severity: high.** This is the one that matters.

`resolution/matcher.py:score_pair` implements acronym matching correctly. `screening/lists.py:candidates_for()` then blocks on the **first 3 characters of the normalized name** before `score_pair` is ever called — and an acronym never shares a 3-character prefix with its expanded form. The scorer's acronym branch can therefore only fire when the concern-list entry *already* carries both the full name and the acronym as separate variants.

Reproduced against the real modules:

```
=== score_pair alone (what the known-difficult set tests) ===
  International Business Machines Corporation  vs IBM             -> 0.900 acronym
  Zhongxing Telecommunication Equipment Corp.  vs ZTE Corporation -> 0.900 acronym
  Beijing Institute of Technology              vs BIT             -> 0.900 acronym

=== the same pairs THROUGH screen_entity's blocking layer ===
  entity=International Business Machines Corporation  list entry=IBM              hits=0
  entity=Zhongxing Telecommunication Equipment Corp.  list entry=ZTE Corporation  hits=0
  entity=Beijing Institute of Technology              list entry=BIT              hits=0

=== reverse direction (entity IS the acronym) ===
  entity=IBM   list entry=International Business Machines Corporation  hits=0
  entity=BIT   list entry=Beijing Institute of Technology              hits=0
```

Zero hits in every direction, both ways round.

**Why the test suite doesn't catch it.** `test_known_difficult_pairs` calls `score_pair` directly. Three of its five true positives are acronym cases, all pass at the unit level, and none is ever exercised through `screen_entity`. Epic H's criterion — "a documented test set of known-difficult name pairs... is checked on every run" — is satisfied literally, but at a seam that cannot see the defect. `test_blocking_does_not_drop_a_true_match_outside_default_block` looks like it covers this but uses `"Acme Corp"` vs `"Acme Corporation"`, which normalize to the *same* block.

**Why the Seven Sons test passes anyway.** `test_seven_sons_also_match_via_their_real_acronym_aliases` works because the real OpenSanctions entries carry both the full name *and* the acronym as aliases, so the block index contains both keys. That's a property of OpenSanctions' data quality, not of your matching logic — and the test's own docstring reads as if it's proving the alias-matching path works generally.

**`docs/methodology.md` half-documents this.** The "Screening uses a blocking step" bullet correctly states that a name differing in its first three characters won't be found. What it doesn't say — and what a reader would not infer — is that this specifically nullifies one of Epic B's three named acceptance criteria. Right now the repo simultaneously asserts (via the regression fixture) that acronym matching works and (via a limitations bullet) that a whole class of it can't.

**Fix options, in increasing cost:**
- Index each concern-list entry under its **acronym key as well as its name key** in `_block_index`, and query `candidates_for` with both the entity's normalized prefix and the entity's acronym prefix. Cheap, ~10 lines, preserves the tractability argument, and makes the existing acronym scorer reachable.
- Add a second blocking key on a sorted-token or n-gram signature.
- At minimum: move the known-difficult regression set to run through `screen_entity` as well as `score_pair`, so the fixture measures the guarantee the epic actually makes.

---

### Finding 2 — The public demo accepts arbitrary server file paths and unauthenticated live-API enrichment from any visitor

**Severity: high, operational.** This is a deployment finding, not a design one — and `api/main.py`'s own module docstring already predicted it:

> "`/runs` and the export endpoints accept caller-supplied local file paths... that's fine for a single local user, **not fine to expose on a public network** without adding path validation or auth first."

The deployment mitigates this halfway. `docker-compose.prod.yml` binds both containers to `127.0.0.1` and `infra/main.tf` never opens 8000, so FastAPI isn't directly reachable. But `app.py`'s sidebar exposes free-text **"NSF awards JSON file"** and **"OpenSanctions targets.simple.csv"** inputs whose values are forwarded verbatim to `POST /runs`, and Streamlit *is* public at `mikejennings.dev/monops`. The reverse proxy is the front door; the file-path parameter walks straight through it.

Concretely, an anonymous visitor can:
- Point `opensanctions_file` at any path readable inside the API container. `read_csv_auto` will attempt to parse it and the rows are persisted to `raw_opensanctions_targets`.
- Use `ingestion_error_count` and the "Run provenance" panel as a **file-existence and parseability oracle** for the container filesystem.
- Click **"Enrich with bibliometric data"**, firing ~100+ live OpenAlex calls per click against your shared free-tier quota, from your server's IP, with no rate limit anywhere (`grep` for `limit_req`/`auth_basic` across `infra/` and both compose files returns nothing).

Separately and independently: **`app.py` starts a full screening run on every new browser session.** Lines 145–162 — if `st.session_state` has no `run_id`, `_start_new_run()` fires unconditionally, before any user action. Every visitor costs one full ingest→screen→score→persist cycle on a 2 GB box, plus a permanent directory under `data/processed/runs/`. There are already **405 run directories** on disk.

**Suggested fix, in priority order:**
1. Replace the two free-text path inputs with a `selectbox` of a server-side allowlist of bundled fixtures. This is a two-line change to `app.py` plus a matching allowlist check in `create_run` — and the allowlist check must be server-side, since the UI is not the trust boundary.
2. Gate the bibliometric and topic-similarity buttons behind an env-var-controlled flag that is off in `docker-compose.prod.yml`, or behind nginx `auth_basic`. A recruiter doesn't need to trigger live OpenAlex traffic to be impressed.
3. Don't auto-run on page load. Render an empty state with a "Run screening" call to action; reuse the most recent existing run if one exists.
4. Add `limit_req` to the `/monops` location block.

This is worth fixing before the demo is linked in an application — a research-security portfolio piece with an unauthenticated arbitrary-path parameter is the kind of detail a security-minded reviewer would notice, and the repo's own docstring shows you already saw it.

---

### Finding 3 — Re-running topic-similarity for the same run silently produces zero flags

**Severity: high (silent wrong answer).**

`storage.insert_paper_embeddings` is the only `insert_*` in `storage.py` with **no `DELETE FROM ... WHERE run_id = ?`** first. `insert_lei_matches`, `insert_ownership_flags`, `insert_openalex_author_matches` and `insert_topic_similarity_flags` all delete-then-insert and document the "current state, re-runnable" contract. `insert_paper_embeddings` appends.

Reproduced:

```
embed_and_persist_papers call #1: paper_embeddings rows = 1  (1 unique paper)
embed_and_persist_papers call #2: paper_embeddings rows = 2  (1 unique paper)
embed_and_persist_papers call #3: paper_embeddings rows = 3  (1 unique paper)
```

The consequence is worse than duplication, because of how `_rank_against_corpus` works. It computes `ROW_NUMBER() OVER (PARTITION BY openalex_work_id ORDER BY similarity DESC)` and flags a paper only if `top_similarity - runner_up_similarity >= margin`. With a duplicated embedding row, the runner-up **is a duplicate of the winner**:

```
ranking with duplicated rows -> top=AreaA 1.0000, runner_up=AreaA 1.0000,
                                margin=0.0000  (DEFAULT_MARGIN=0.1)
```

Margin collapses to zero, every flag is filtered out, and `insert_topic_similarity_flags` — which *does* delete first — wipes the previous run's correct flags and writes nothing. **A second topic-similarity run on the same `run_id` turns a correct non-empty result into a silent empty one, with no error.**

The UI reachs this trivially: the "Compute topic-similarity flags" button has no guard against being clicked twice.

**Fix:** add the delete to `insert_paper_embeddings` (one line, matching its four siblings), plus a regression test asserting that two consecutive `enrich_topic_similarity` calls on one `run_id` return equal flag sets.

---

### Finding 4 — `enrich_bibliometric` duplicates screening hits on every re-run

**Severity: medium.**

`pipeline.py:471` calls `storage.insert_screening_hits(conn, all_hits, run_id)`, which is append-only. The function's own docstring and `docs/architecture.md` both describe `enrich_bibliometric` as having "current state" semantics like `enrich_ownership`. It half-does: `insert_openalex_author_matches` deletes correctly, `insert_screening_hits` does not.

Reproduced:

```
before any enrichment:            screening_hits = 0
after 1st enrich_bibliometric:    returned 1 hits; screening_hits table = 1; author_matches = 1
after 2nd enrich_bibliometric:    returned 1 hits; screening_hits table = 2; author_matches = 1
after 3rd enrich_bibliometric:    screening_hits table = 3
rescore_run -> Montana State University: 3 hits shown to reviewer, total_score=50.0
```

The score is unaffected (`score_entity` uses `max` confidence), but the **evidence trail a reviewer reads is not**: the UI's evidence inspector and the CSV export both show the same finding three times. For a tool whose entire value proposition is "an auditor could follow this back to source records," a triplicated evidence trail is a real correctness problem even though no number changes.

This one is genuinely awkward to fix, and the awkwardness is the actual design issue: a naive `DELETE FROM screening_hits WHERE run_id = ?` would also delete the run's *original* V1 screening hits. `screening_hits` is a single table serving three producers (`screen_entity`, `cross_check_section_117`, `cross_check_bibliometric`) with three different lifecycles, and only one of them is append-once.

**Fix:** add a `producer` (or `stage`) column to `screening_hits`, and have each enrichment step delete only its own producer's rows for the run. This also fixes half of Finding 5 for free.

---

### Finding 5 — `matched_field` never leaves the database, and bibliometric hits borrow the concern list's name

**Severity: medium (Epic D acceptance gap + explainability).**

Epic D's criterion: *"every hit records match confidence and the specific evidence (**matched name variant, matched field**) that produced it."*

`ScreeningHit.matched_field` is populated correctly, persisted to DuckDB correctly — and then dropped at both output boundaries. `api/dto.py:ScreeningHitOut` doesn't declare it; `output/export.py:_serialize_row` doesn't emit it. Reproduced:

```
API ScreeningHitOut fields: ['list_name', 'matched_variant', 'confidence', 'evidence', 'status']
CSV hit-object keys:       ['confidence', 'evidence', 'list_name', 'matched_variant', 'status']
CSV contains 'matched_field'?  False
```

This compounds with a second issue. `cross_check_bibliometric` sets `list_name=concern_list.list_name` — so a bibliometric hit is tagged `opensanctions_consolidated` or `dod_section_1260h`, exactly like a direct name match against the entity itself. (`cross_check_section_117` correctly uses its own distinct `LIST_NAME`; bibliometric is the only producer that borrows.) With `matched_field` stripped, the export and the UI's `list_hits` column cannot distinguish:

- the awardee's **own name** matching a 1260H entry (a strong, direct finding), from
- a **co-author's institution** on one of 456 papers matching a 1260H entry (a much weaker, second-order finding), from
- the PI's **own past affiliation** (`bibliometric_past_affiliation` vs `bibliometric_co_author_institution`).

These are materially different claims and the export flattens all three into "hit against `dod_section_1260h`." A reader has to dig into the nested `evidence` JSON and infer from the presence of an `author_resolution` key — which is exactly what `app.py:272` does, and which the module docstring frames as a deliberate workaround for `matched_field` not being on the DTO.

It also affects scoring: `multiple_list_hit_bonus` fires on `len({hit.list_name}) > 1`, so a direct OpenSanctions hit plus a co-author's-institution DoD hit reads as "two independent lists corroborate" when it is really one direct and one second-order signal.

**Fix:** add `matched_field` to `ScreeningHitOut` and to the export row's hit objects (two lines each), and give bibliometric hits their own `list_name` — or a `producer` column per Finding 4 — so the provenance of a hit is visible without parsing nested JSON.

---

### Finding 6 — The OpenAlex precision caveat lives only in the Streamlit UI

**Severity: medium (Epic E acceptance gap).**

Epic E's third criterion is specific: *"every result surfaces OpenAlex's own stated match-precision caveat **inline, not buried in documentation** — e.g., a persistent disclaimer alongside **every** bibliometric result, not just a one-time README note."*

`OPENALEX_PRECISION_DISCLAIMER` is defined at `app.py:31` and rendered as an `st.caption` next to each bibliometric hit. That satisfies the criterion for the Streamlit path only. Reproduced:

```
CSV/API contain any OpenAlex precision caveat?  False
```

An analyst who exports the CSV — the workflow Epic G exists to serve — receives a bibliometric hit at confidence 1.0 with no caveat at all. Same for any API consumer. The disclaimer is presentation-layer decoration, and "buried in the UI layer" is a variant of the failure the criterion was written to prevent.

What makes this worth fixing is that **the codebase already knows the right pattern**: `TopicSimilarityFlag.recommendation` is a field on the dataclass with a default value, so the caveat travels with the data through storage, DTO and UI and cannot be dropped by a consumer. Doing the same for bibliometric hits — a `caveat` key inside `evidence`, populated in `cross_check.py` — is a handful of lines and makes the criterion true everywhere.

The same fix pattern closes the Section 10 license-compliance gap ("surfaced in output, not just in a README"): a `source_license` / `attribution` key alongside it.

---

### Finding 7 — The ownership graph flattens branching and cyclic chains

**Severity: medium (Epic C).**

`ownership/graph.py:parent_chain` runs a `WITH RECURSIVE` CTE with `UNION ALL` (no de-duplication, no visited set), then flattens all results into a single tuple ordered by depth. That is correct for a strictly linear chain and wrong for anything else. Reproduced against a synthetic GLEIF table where `SUB` has two direct parents:

```
branching graph (SUB has two direct parents P1, P2):
  parent_chain    -> chain=('P1','P2','TOPA','TOPB')  truncated=False
  ultimate_parent -> ('TOPB', False)     <- chain[-1] picks ONE arbitrarily

cyclic graph A<->B:
  chain=('B','A','B','A','B')  truncated=True
```

Two consequences:

1. `flagging.py:flag_from_match` takes `result.chain[-1]` as the ultimate parent and writes `full_path = (match.lei, *result.chain)` into `ForeignControlFlag.relationship_path`. With branching, that `relationship_path` **describes a path that does not exist in the data** — it is an ordering artifact — and the reported ultimate parent is an arbitrary pick between two genuine ones. For a system whose non-negotiable is "traceable to underlying evidence records," a fabricated path in the evidence field is the worst-shaped bug available.
2. Epic C's criterion says traversal depth and direction must be queryable, *"not collapsed into a single value."* Depth and direction are handled well; **branching is collapsed**, which is the same class of loss the criterion was guarding against.

The cycle case is bounded by `max_depth` so nothing hangs, but the chain is nonsense and `truncated=True` misreports it as "there is more beyond this."

This is a real-data question, not a hypothetical: GLEIF's Level 2 file does contain entities with multiple active `IS_DIRECTLY_CONSOLIDATED_BY` edges. Worth noting that `ParentChain`'s docstring is unusually careful about the *depth* honesty problem — this is the adjacent honesty problem it didn't consider.

**Fix:** either return `chain` as a `tuple[tuple[str, ...], ...]` of distinct paths, or add a `branch_count` / `ambiguous: bool` field and refuse to emit a `ForeignControlFlag` with a single `relationship_path` when the walk branched. Add a `WHERE NOT list_contains(path, r.end_lei)` style guard for cycles.

---

### Finding 8 — The deployed demo shows nothing

**Severity: medium, but it is the highest-leverage item for the project's stated goal.**

Section 4 names the secondary audience as "a recruiter, hiring manager, or GitHub visitor," and Section 2's last goal is a project that "needs no explanation of relevance." Right now, with the shipped defaults, a visitor to `mikejennings.dev/monops` sees:

```
entities: 53   hits: 0
```

53 entities screened, 0 candidate matches, and "Show only candidate matches" is checked by default — so the results table renders **empty**. The evidence-trail selectbox has no options. The scoring sliders move nothing. Every capability the project is meant to demonstrate is invisible until the visitor knows to click "Enrich with bibliometric data" — the button that currently times out (see Finding 9).

This is correct behavior, and you've already diagnosed the structural reason (NSF only funds US-based recipients, so direct name matches against OpenSanctions/1260H are always zero). But "correct and empty" is a bad first ten seconds for the audience the requirements name.

The proximate cause is smaller than the structural one: the default `opensanctions_file` is `tests/fixtures/sample_opensanctions_targets.csv`, which contains **three rows** — ZTE, "Acme Testing Materials", and one deliberately-null-name test row. The DoD 1260H list ships with 214 real entries and is doing real work; the OpenSanctions side of the demo is a unit-test fixture.

**Options, roughly in order of effort:**
- Ship a curated real OpenSanctions subset as `tests/fixtures/demo_opensanctions_targets.csv` — a few thousand real rows including the Seven Sons entries you already verified exist there — the same curation move you made for `demo_nsf_awards.json`. This alone would probably produce a non-empty table.
- Default "Show only candidate matches" to unchecked, so the 53 screened entities are at least visible with their scores and provenance.
- Pre-compute and ship one enriched run's results, so the bibliometric layer (the Rod Wing → BGI Genomics tie you deliberately built the dataset around) is visible on load rather than behind a slow live call.
- Add a one-paragraph "what you're looking at, and why zero direct matches is the correct answer" note at the top of the page. The empirical `awardeeCountryCode=CN → totalCount: 0` finding is genuinely interesting and currently lives only in a doc.

---

### Finding 9 — Bibliometric enrichment fetches every author's full works corpus twice, unbounded

**Severity: medium (performance; this is your open timeout item).**

Confirming your diagnosis and adding to it. `openalex_client.get_author_works` pages with no cap and accumulates into one Python list — for Rod Wing, 456 works, three sequential API round-trips, all held in memory. `enrich_bibliometric` calls it once per resolved author; `enrich_topic_similarity` then calls it **again** for the same authors in `embed_and_persist_papers`. Running E and the VSS layer together doubles the OpenAlex traffic and the wall-clock for the works walk, and neither path caches.

This also breaches Section 10's streaming NFR in the one place the project has a millions-of-records source: OpenSanctions and GLEIF stream properly; OpenAlex's works corpus is the only load-to-memory path left.

On the two options in your brief: **do both, but with a third piece.**
1. Raise the `_api_post` timeout, and — more usefully — give the bibliometric and topic-similarity calls their own longer timeout rather than raising it for `POST /runs` too. A 120-second run-screening timeout is a reasonable guardrail; a 120-second enrichment timeout is not.
2. Cap `get_author_works` — but cap it with an explicit `max_works` parameter that is **recorded in `BibliometricSnapshotManifest`**, not a bare constant. A silently truncated works history is a reproducibility claim you can no longer make, and this project's whole discipline is that such things go in the manifest. This is the same reasoning `ParentChain.truncated` already applies to the ownership walk; the bibliometric walk deserves the same treatment, which arguably makes the cap an improvement rather than a trade-off.
3. Persist works once per author per run and have `enrich_topic_similarity` read them back instead of re-fetching. This halves the cost of the combined path and is probably the single biggest wall-clock win available.

Streamlit will also disconnect the websocket on a long synchronous POST regardless of the client timeout, so consider `st.status`/progress feedback around the call.

---

## 5. Smaller observations

- **`score_entity` uses only the single highest-confidence hit.** An entity with 1 hit at 0.95 and an entity with 40 hits at 0.95 score identically. Defensible (it avoids letting the bibliometric layer's volume-multiplication dominate the ranking), and arguably correct — but it is undocumented, and it means the ranked table can't distinguish "one strong signal" from "a pattern." Worth a sentence in `methodology.md` either way; possibly worth a `hit_count` factor with a low default weight.
- **`ScoringRubric` has no `bibliometric_hit_weight`.** Bibliometric hits ride the general `screening_hit_weight`, so Epic F's "change the weighting if I disagree with it" can't express "I trust direct name matches more than co-authorship inference" — which is exactly the disagreement an analyst would most want to express. Depends on Finding 5's fix landing first.
- **`normalize.py:transliterate` folds Unicode combining marks only.** That covers `Société Générale`, which is what the fixture tests. It does not cover pinyin variants, Cyrillic, or any actual script transliteration — which is what "transliteration variants" means in a sanctions-screening context. The limitation is honestly noted in `methodology.md`; the acceptance criterion's wording implies more than the implementation delivers. Worth either narrowing the criterion's language or naming `unidecode`/`nomenklatura` as the V4 path.
- **`_http_get` retries only on HTTP 429.** A 500/502/503 from OpenAlex, or a `requests.ConnectionError`, still crashes the whole enrichment and discards every hit found so far — the exact failure mode the 429 retry was added to prevent. Widening the retry predicate is a two-line change.
- **`resolve_entities_from_nsf` groups by exact normalized name**, so "Montana State University" and "Montana State University-Bozeman" stay separate entities. `enrich_bibliometric` compensates by regrouping on the resolved OpenAlex institution ID, but the entity table itself, the CSV export, and the entity count in the UI header all still double-count. Documented, and probably right for V1, but the export is where it's most visible.
- **`docs/deployment-runbook.md` Section 7 still documents the un-`sudo`'d `git pull`** you hit the dubious-ownership error on. Worth fixing while it's fresh.
- **`Project Monops Logo.jpeg` is committed at the repo root with a space in the filename** and isn't referenced anywhere. Either put it in the README header or move it under `docs/`.

---

## 6. Answers to the open items in your brief

**"The new 70-record dataset had `ingestion_error_count: 1` on every test run — one real NSF record is malformed."**

It isn't an NSF record. `demo_nsf_awards.json` is clean — 70/70 records have both `id` and `awardeeName`, and 70/70 have both `piFirstName` and `piLastName` (53 distinct awardee names). The single error comes from the **OpenSanctions fixture**:

```
source: opensanctions_targets_simple
reason: missing required column(s): name
raw:    {"id": "os-003", "schema": "Company", "name": null, "aliases": "Missing Name Entity"}
```

That row is deliberate — it's the fixture row that proves Epic A's "ingestion failures are logged, not silently dropped." Working exactly as designed; nothing to fix. It'll disappear on its own if you swap in a real OpenSanctions demo subset per Finding 8.

**"Bibliometric enrichment timeout."** See Finding 9 — your diagnosis is right, and I'd add the double-fetch and the manifest-recorded cap.

**"Which quick fix to pick?"** Both, plus persisting works once. But I'd put Finding 3 (silent zero-flag on re-run) and Finding 2 (public arbitrary-path input) ahead of the timeout in the queue: the timeout is visible and annoying, those two are invisible and wrong.

---

## 7. Suggested order of work

**Before linking the demo anywhere:**
1. Finding 2 — allowlist the file-path inputs server-side; gate or rate-limit the enrichment buttons; stop auto-running on page load.
2. Finding 3 — one-line `DELETE` in `insert_paper_embeddings`, plus the re-run regression test.

**To close the acceptance-criteria gaps (half a day, high interview value):**

3. Finding 1 — index concern-list entries under their acronym key; move the known-difficult set to run through `screen_entity` too.
4. Finding 6 — move the OpenAlex caveat into `evidence` as a data field; same for per-source license/attribution.
5. Finding 5 — `matched_field` onto the DTO and the export row; distinct `list_name` or a `producer` column for bibliometric hits.

**Then:**

6. Finding 4 — `producer` column, letting each enrichment step delete only its own rows.
7. Finding 9 — manifest-recorded works cap, persist-once, per-endpoint timeouts.
8. Finding 8 — curated real OpenSanctions demo subset so the front page shows something.
9. Finding 7 — branching/cycle honesty in `parent_chain`.

Findings 1, 5, 6 and 7 all share a shape worth naming: in each one, the codebase makes a careful, well-reasoned guarantee in one layer and then quietly loses it at a boundary — the scorer's acronym logic lost at the blocking step, `matched_field` lost at the DTO, the caveat lost outside Streamlit, the branch structure lost in a flattened tuple. The engineering instinct here is consistently good; the gap is in verifying the guarantee end-to-end rather than at the unit that implements it. A small number of tests written at the outermost seam — export row and API response, not the function that builds them — would have caught four of the seven findings in this report.

---

*Prepared 2026-09-02 against commit `40ca51b`. All runtime claims reproduced against the modules as committed; see Section 1 for method.*
