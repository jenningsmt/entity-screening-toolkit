# Remediation Pass — Findings from the 2026-09-02 Codebase Evaluation

**Status:** Built, with one deliberate re-scoping (2026-09-02). Workstreams
3, 4, 1, 6, 5a, 5b, 7, the cross-cutting test files, 9, 8a, and 8c landed
first, each as its own commit, in the order given below except where
explicitly re-sequenced (8a/8c moved ahead of 2, matching the dependency
note in Workstream 2's own section).

**Re-scoping, decided after the fact:** Workstream 8b as originally written
called for a pre-computed run with bibliometric enrichment baked in, and
Workstream 2 was gated on it landing first specifically to avoid gating
run-creation before there was anything non-blank to show. OpenAlex
rate-limited the build machine for the length of this session, blocking any
enrichment-inclusive bake. Rather than leave both blocked, 8b was re-scoped
to a **screening-only** self-healing demo run (`api/main.py:DEMO_RUN_ID` /
`_ensure_demo_run_exists` — built lazily on first request rather than baked
into the Docker image, sidestepping the image-vs-volume-mount shadowing
problem a literal "bake into the image" approach would have hit given
`docker-compose.yml`'s `./data:/app/data` bind mount). This is sufficient to
satisfy Workstream 2's actual dependency: Workstream 8a already means a
screening-only run shows a real, non-blank, explained table on load (53
real entities, 0 direct hits, with the "why zero is expected" panel) — the
specific failure mode ("blank page and a disabled button") the 8b-before-2
gate existed to prevent. Adding bibliometric (and ownership) enrichment to
this baked-in run is still worth doing once OpenAlex access is confirmed
working again, but it is no longer a blocker for anything else in this plan.

Workstream 9's real CLI timing measurement (its own "before choosing a
timeout value" section) was also blocked by the same OpenAlex rate limit;
the 600s enrichment timeout `app.py` ships with is a documented, reasoned
placeholder, not a live-measured one. Re-measure and adjust once OpenAlex
access is confirmed working again.
**Source:** `docs/2026-09-02-codebase-evaluation.md` (9 findings, all reproduced against `40ca51b`)
**Audience:** Claude Code, working this repo directly

---

## Context

An end-to-end evaluation against `docs/requirements.md` found four real defects and three acceptance-criteria gaps. Three of the seven share one shape: **a guarantee made carefully in one layer and quietly lost at a boundary** — the acronym scorer lost at the blocking step, `matched_field` lost at the DTO, the OpenAlex caveat lost outside Streamlit. The remediation is therefore not only nine fixes; it is also two test files written at the *outermost* seam (export row, API response, re-run idempotency) that would have caught four of the nine and will prevent the class recurring.

Two of the fixes below were prototyped and verified against the real modules before this plan was written. Their verified output is quoted inline — **do not redesign them, implement them.**

### Working agreements for this pass

- **This repo's docstrings are load-bearing documentation, not noise.** Several encode real findings against real data (the `api.research.gov` DNS death, the 0.8387 false positive, the GLEIF CSV column-name trap). Extend them; never strip or "clean up" one to make a diff smaller.
- **Every behavior change updates `docs/methodology.md` and/or `docs/architecture.md` in the same commit**, per existing house practice. Several known-limitations bullets in `methodology.md` become wrong as a result of this work and must be rewritten, not left stale — they are called out per workstream below.
- **Commit per workstream**, in the order given. Each is independently verifiable and independently revertable.
- Add this file to the `docs/plans/README.md` index (Status: Built) as part of the final commit.
- `pytest` must pass at every commit boundary. `python -m entity_screening.cli validate` must pass at every commit boundary.

### Decide this before starting

**Workstream 5b changes scoring semantics** (bibliometric hits get their own weight, and stop firing `multiple_list_hit_bonus`). Existing scoring tests and the demo's numbers change. Confirm this is wanted; if not, do 5a (surfacing) and skip 5b (rubric). Everything else in this plan is settled.

*Resolved since the first draft:* an earlier version flagged OpenSanctions redistribution as an open licensing question and proposed site-wide HTTP basic auth as one response. Both are now settled — the data is CC BY-NC 4.0 and redistribution is permitted with attribution, and the access-control decision landed on gating *actions* rather than access. See Workstreams 8c and 2 respectively.

---

## Workstream 1 — Make acronym matching reachable (Finding 1)

**Epic B acceptance criterion currently does not hold end-to-end.** `matcher.py:score_pair` scores acronym pairs at 0.90, but `screening/lists.py:candidates_for()` blocks on the first 3 characters of the normalized name before the scorer is ever reached, and an acronym never shares a 3-char prefix with its expansion. Verified: zero hits in both directions for IBM/ZTE/BIT.

### Design (verified — implement as specified)

Index every concern-list entry under **two** key types, and query under **both**:

- `normalize_for_matching(variant)[:block_size]` — as today.
- `acronym(strip_corporate_suffix(transliterate(variant))).lower()[:block_size]` — new. Skip when the acronym is 1 character or fewer, mirroring `score_pair`'s own `len(left_acronym) > 1` guard.

`candidates_for(name)` computes the same two keys for the *entity* name, unions the two candidate lists, and de-duplicates by `entry_id` preserving order. Indexing and querying both key types is what makes it work in both directions: `IBM` reaches the full name via its own name-key hitting the entry's acronym-key, and the full name reaches `IBM` via its acronym-key hitting the entry's name-key.

Prototype run against the real modules:

```
=== the three failing acronym cases, WITH the proposed fix ===
  [PASS] entity=International Business Machines Corporation  entry=IBM                             0.90 acronym
  [PASS] entity=Zhongxing Telecommunication Equipment Corp.  entry=ZTE Corporation                 0.90 acronym
  [PASS] entity=Beijing Institute of Technology              entry=BIT                             0.90 acronym
  [PASS] entity=IBM                                          entry=International Business Machines 0.90 acronym
  [PASS] entity=BIT                                          entry=Beijing Institute of Technology 0.90 acronym
  [PASS] entity=NUAA                                         entry=Nanjing University of Aero...   0.90 acronym

=== regression: the true NEGATIVES must still not match ===
  [PASS] National Institutes of Health   vs National Instruments Corporation
  [PASS] American Electric Power Company vs American Electric Technologies Inc
  [PASS] Apple Inc.                      vs Apple Leasing Corporation
  [PASS] Springfield State University    vs ZTE Corporation

=== candidate-set growth cost (20,000 synthetic entries) ===
  old block for 'Global Aerospace Corporation': 4002 candidates
  new block:                                    4002 candidates
```

Blocking is a *candidate* step only — `score_pair` and the threshold still gate every result, so a wider block costs time, not precision. On the synthetic stress case the candidate set did not grow at all.

### Files

- `entity_screening/screening/lists.py` — `_block_index()` and `candidates_for()`. Factor the acronym-key computation into a module-level `_acronym_key(name, block_size)` helper; do not inline it twice.
- `entity_screening/screening/section_117.py` — `_block_index()` there is a *separate* implementation over Section 117 rows keyed by `School Name`. Apply the same two-key treatment, and compute the entity-side keys the same way, so the institution match isn't left with the defect this workstream removes elsewhere.

### Tests (binding)

- **Move the known-difficult regression set through the screening path.** `tests/test_matcher.py:test_known_difficult_pairs` currently calls `score_pair` directly, which is why this shipped. Add a second parametrized test — `test_known_difficult_pairs_through_screen_entity` — that builds a one-entry `OpenSanctionsList` from each pair's `right` and asserts `bool(screen_entity(...))` equals `expect_match`. Epic B's guarantee is about screening, so the regression set must be checked at that seam.
- `tests/test_screening.py`: replace `test_blocking_does_not_drop_a_true_match_outside_default_block`. It currently uses `"Acme Corp"` vs `"Acme Corporation"`, which normalize to the *same* block and so tests nothing. Use a genuine cross-block acronym pair.
- Assert the four true negatives above still produce zero hits through `screen_entity`.

### Docs

- `docs/methodology.md`, "Screening uses a blocking step" bullet: rewrite. It is currently half-true — it names the 3-char limitation but does not say the limitation nullified a named Epic B criterion, and after this fix the acronym case is no longer a limitation at all. State what the blocking step still cannot reach (a genuine alias sharing neither a name prefix nor an acronym).
- `tests/test_screening_seven_sons.py:test_seven_sons_also_match_via_their_real_acronym_aliases` — its docstring implies it proves the alias-matching path works generally. It passes only because the real OpenSanctions entries happen to carry both spellings. Amend the docstring to say what it actually proves, now that the general case is covered elsewhere.

---

## Workstream 2 — Close the public demo's exposure (Finding 2)

`api/main.py`'s module docstring already called this: caller-supplied local file paths are "not fine to expose on a public network." `docker-compose.prod.yml` binds the containers to `127.0.0.1` and Terraform never opens 8000, but `app.py`'s free-text **"NSF awards JSON file"** and **"OpenSanctions targets.simple.csv"** inputs forward straight through nginx to `POST /runs`. There is no `limit_req` or `auth_basic` anywhere in `infra/` or either compose file.

**Do this workstream once Workstream 8b has landed** — see the dependency note at the end of this section. The UI is not the trust boundary for the allowlist; that check is server-side.

### The design decision: gate actions, not access

The obvious move is site-wide HTTP basic auth on `/monops`. **Don't.** Two reasons, one strategic and one mechanical.

*Strategic:* `docs/requirements.md` Section 4 names recruiters and hiring managers as the audience, and Section 9 justifies paying for Lightsail specifically to remove the cold-start friction of a managed free tier. A password prompt is worse friction than a cold start, and credentials pasted into a cover letter are not meaningfully auth anyway. Locking the front door defeats the reason the door exists.

*Mechanical:* it would not work even if it were wanted. Streamlit is a single-page websocket app — every interaction, including the enrichment buttons, travels over one connection to the same `/monops` URL. There is no separate path for nginx to protect, so `auth_basic` at that layer is all-or-nothing by construction.

So: **the read path stays open, and the expensive or dangerous *actions* get gated inside the app.** That collapses what were four separate sub-fixes into one coherent change.

Gating in the app rather than at the edge is normally theatre, and it is worth being explicit about why it is not here: `docker-compose.prod.yml` binds the API to `127.0.0.1`, `infra/main.tf` never opens 8000, and the Streamlit container reaches FastAPI over the internal Docker network. The app genuinely is the only route to the API. The server-side allowlist in 2b stays regardless, as defence in depth for the day that stops being true.

### 2a — Gate the mutating and expensive actions behind a shared secret

- **Open, no secret required:** viewing the pre-computed demo run, the scored table, the evidence trail, rubric sliders, and exports of that run. This is the demo, and it is what the audience in Section 4 actually needs to see.
- **Behind the secret:** starting a *new* run (`POST /runs`), and all three enrichment steps (ownership, bibliometric, topic-similarity).

Implementation: an `st.text_input(type="password")` in the sidebar compared against `MONOPS_ACTION_SECRET`. When the env var is **unset, everything is unlocked** — local dev and the CLI are untouched, which is the correct trust boundary for a single local user. When set and unmatched, render the gated controls disabled with a one-line caption saying they are disabled on the public demo, rather than hiding them: a reviewer should be able to *see* that ownership, bibliometric and topic-similarity enrichment exist. Set the secret in `docker-compose.prod.yml`.

This subsumes the old "disable live enrichment entirely" approach and is strictly better — an anonymous visitor can no longer fire 175–297 live OpenAlex calls per click against the shared free-tier quota from your server's IP (see Workstream 9 for that call count), but you can still demo the live path yourself from the public URL.

### 2b — Server-side data-file allowlist (defence in depth)

- New helper in `api/main.py`, resolved at call time like `_db_path()`/`_runs_dir()`: read `MONOPS_DATA_FILE_ALLOWLIST` (os-pathsep-separated paths). When **unset, behavior is unchanged.**
- When set, `create_run` validates `nsf_file`, `opensanctions_file`, `section_117_file` and `dod_1260h_file` against it after `Path(...).resolve()`, returning `HTTPException(400)` on a miss. Resolve *before* comparing so `../` traversal cannot slip past.
- `enrich_ownership_route`'s `gleif_lei_file`/`gleif_relationships_file` get the same treatment — same parameter class, same exposure.
- `docker-compose.prod.yml` sets the env var on the `api` service to the bundled fixtures only.
- `app.py`: replace both `st.text_input` path fields with `st.selectbox` over a module-level list of the bundled fixtures. UX, not security — the server check is the control.

### 2c — Stop auto-running on every page load

`app.py` lines 145–162 call `_start_new_run()` unconditionally whenever `st.session_state` has no `run_id` — so every new browser session costs a full ingest→screen→score→persist cycle on a 2 GB box plus a permanent run directory. There are already 405 of them. With 2a in place this would also simply fail for every anonymous visitor, so it has to change regardless.

Replace with: on load, show the pre-computed demo run (Workstream 8b). Only start a new run on an explicit click, and only when the action gate is satisfied. Keep the existing stale-`run_id` 404 recovery path — that logic is correct and worth preserving.

### 2d — Rate limit

`infra/nginx/monops.conf`: add a `limit_req_zone` in the `http` context (this file is included from `sites-available`, so the zone may need to go in a separate `conf.d` snippet — check where `user_data.sh` places it) and `limit_req` on the `/monops` location. Exempt the websocket upgrade path or Streamlit's live channel will stutter.

### 2e — Keep the demo out of search indexes and casual scrapers

Requested, and cheap. Two pieces, both in `infra/nginx/monops.conf`:

- `add_header X-Robots-Tag "noindex, nofollow" always;` inside the `/monops` location. Use `always` so it is emitted on error responses too. Note the nginx gotcha: `add_header` in a location block *replaces* rather than extends any inherited headers, so if a parent block ever gains its own `add_header`, both must be restated here.
- A `location = /robots.txt` block serving a `Disallow: /monops/` file from `/var/www/monops-placeholder/`, laid down by `infra/user_data.sh` alongside the placeholder `index.html`.

Two honest limits worth recording in the runbook rather than assuming: `robots.txt` is host-wide, so revisit it when a real portfolio site lands at the apex; and neither measure stops a scraper that ignores them — they are hygiene against indexing, not access control. The rate limit in 2d is the actual defence against volume.

### Tests

`tests/test_api.py`: allowlist set + path outside it → 400; allowlist set + path inside it → 200; allowlist unset → current behavior unchanged (this last one guards the CLI/local trust boundary). Action secret set + absent or wrong → 403 on `POST /runs` and all three enrichment routes; correct secret → 200; secret unset → 200 (local dev unchanged).

### Docs

`docs/deployment-runbook.md`: new subsection listing the two env vars, stating plainly that the public instance runs with the allowlist on and the action gate set, and recording the two `robots.txt`/`X-Robots-Tag` limits above. While in that file, fix the Section 7 "Day-2 redeploys" `git pull` — it is missing the `sudo git config --global --add safe.directory /opt/monops` / `sudo git -C /opt/monops pull` / `sudo systemctl restart monops` sequence that actually works, because `user_data.sh` clones as root and redeploys run as `ubuntu`.

### Dependency

**Workstream 8b must land first.** Gating run creation without a pre-computed run to display leaves an anonymous visitor with a blank page and a disabled button — strictly worse than today's empty results table. The commit sequence below reflects this.

---

## Workstream 3 — Idempotency: paper embeddings (Finding 3)

`storage.insert_paper_embeddings` is the only `insert_*` in `storage.py` without a `DELETE FROM ... WHERE run_id = ?` first. Its four siblings all delete-then-insert and document the "current state, re-runnable" contract.

The consequence is a **silent wrong answer**, not just duplication. `_rank_against_corpus` flags a paper only when `top_similarity - runner_up_similarity >= margin`; with a duplicated embedding row the runner-up *is the winner's duplicate*, so margin collapses to `0.0000` against `DEFAULT_MARGIN = 0.10` and every flag is filtered out. `insert_topic_similarity_flags` then correctly deletes the previous run's flags and writes nothing. Verified:

```
embed_and_persist_papers call #1: paper_embeddings rows = 1  (1 unique paper)
embed_and_persist_papers call #2: paper_embeddings rows = 2
embed_and_persist_papers call #3: paper_embeddings rows = 3
ranking with duplicated rows -> top=AreaA 1.0000, runner_up=AreaA 1.0000, margin=0.0000
```

The UI reaches this by clicking "Compute topic-similarity flags" twice.

### Fix

One line: add the `DELETE FROM paper_embeddings WHERE run_id = ?` to `insert_paper_embeddings`, and extend its docstring to match its siblings' wording.

**Watch the ordering.** `compute_topic_similarity_flags` is called once per `entity_id` in a loop inside `enrich_topic_similarity`, and `insert_paper_embeddings` is called once per entity from inside it. A `DELETE WHERE run_id = ?` alone would have entity N's insert wipe entities 1..N−1. Delete on `(run_id, entity_id)` — the natural scope, matching how the ranking query already filters (`WHERE p.run_id = ? AND p.entity_id = ?`).

### Test

`tests/test_pipeline_topic_similarity.py`: call `enrich_topic_similarity` twice on one `run_id` with a fixed fake fetch/embed, and assert the two flag lists are equal and non-empty. This is the regression that matters — without it the fix is invisible.

---

## Workstream 4 — Idempotency and hit provenance: the `producer` column (Finding 4)

`pipeline.py:471` calls the append-only `insert_screening_hits`, so re-running `enrich_bibliometric` duplicates hits (1 → 2 → 3 verified) even though `insert_openalex_author_matches` correctly deletes. The score is unaffected (`score_entity` uses `max`), but **the evidence trail a reviewer reads triplicates** — in the UI inspector and in the CSV both. For a tool whose entire claim is auditability, that is a correctness problem regardless of the numbers.

The naive fix breaks things: `DELETE FROM screening_hits WHERE run_id = ?` would also delete the run's original V1 hits. `screening_hits` serves three producers with three different lifecycles, and only one is append-once. That missing dimension is the actual defect, and adding it also fixes half of Workstream 5.

### Design

- Add `producer: str = "direct_name"` to `ScreeningHit` in `common/schema.py`, positioned **after** `status` (which already has a default, so ordering rules require it there). All construction sites in this codebase are keyword-based, so this is safe.
- Producer values: `"direct_name"` (`screening/screen.py`), `"section_117"` (`screening/section_117.py`), `"bibliometric"` (`bibliometric/cross_check.py`). One value per pipeline *stage* — the finer distinction between a PI's own past affiliation and a co-author's institution already lives in `matched_field` and should stay there.
- `storage.insert_screening_hits(conn, hits, run_id)` groups the incoming hits by `producer` and deletes only `WHERE run_id = ? AND producer = ?` for each producer present. Called with an empty list for a producer, it must not delete anything — a caller passing no hits is not asserting "that stage found nothing", and `run_screening` already skips Section 117 entirely when no file is supplied.
- `load_screening_hits` selects and reconstructs `producer`.

### Schema migration — read this

`CREATE TABLE IF NOT EXISTS` will **not** add a column to the existing DuckDB file. The deployed instance mounts `./data` as a volume with a live `entity_screening.duckdb`, and there is a 7.3 MB one in local dev. Verified working on DuckDB 1.5.5:

```
ALTER TABLE ADD COLUMN IF NOT EXISTS: OK, idempotent -> ['a', 'producer']
```

Add to `storage.connect()`, after the `SCHEMA_DDL` execute:

```sql
ALTER TABLE screening_hits ADD COLUMN IF NOT EXISTS producer VARCHAR;
```

Backfill existing rows to `'direct_name'` in the same step (`UPDATE screening_hits SET producer = 'direct_name' WHERE producer IS NULL`) so old runs still render. Put a comment on it explaining why an `ALTER` sits beside the DDL — the next person will otherwise assume the DDL is the whole schema story.

### Test

`tests/test_pipeline_bibliometric.py`: `enrich_bibliometric` twice on one `run_id` → `screening_hits` row count identical after both, and the run's original direct-name hits still present. Same shape for `run_screening` + `cross_check_section_117`.

### Docs

`docs/architecture.md` and `docs/methodology.md` both describe `enrich_bibliometric` as having "current state" semantics like `enrich_ownership`. That was aspirational, not true. After this workstream it is true — leave the wording but add the `producer` mechanism to the storage-layer description in `architecture.md`'s module map.

---

## Workstream 5 — Surface `matched_field` and hit provenance (Finding 5)

Epic D's criterion: *"every hit records match confidence and the specific evidence (**matched name variant, matched field**) that produced it."* `matched_field` is populated and persisted correctly, then dropped at both output boundaries. Verified:

```
API ScreeningHitOut fields: ['list_name','matched_variant','confidence','evidence','status']
CSV hit-object keys:       ['confidence','evidence','list_name','matched_variant','status']
CSV contains 'matched_field'?  False
```

This compounds with `cross_check_bibliometric` setting `list_name=concern_list.list_name` — so a co-author's institution matching a 1260H entry on one of 456 papers is tagged identically to the awardee's own name matching that entry directly. (`section_117.py` correctly uses its own `LIST_NAME`; bibliometric is the only borrower.) The export flattens three materially different claims into one label, and `app.py:272` works around it by sniffing for an `author_resolution` key in the nested evidence JSON.

### 5a — Surfacing (do this regardless)

- `api/dto.py`: add `matched_field: str` and `producer: str` to `ScreeningHitOut`, and populate both in `scored_entity_to_dto`.
- `output/export.py`: add both keys to `_serialize_row`'s hit objects.
- `app.py`: replace the `"author_resolution" in evidence` sniff at line 272 with a direct `hit["producer"] == "bibliometric"` check, and add a `hit_kinds` column to the results dataframe showing distinct producers alongside the existing `list_hits`. Keep `list_hits` — it is still the right answer to "which concern list", it was just carrying two questions at once.

### 5b — Scoring semantics (confirm before implementing)

Two consequences of the current model that 5a exposes but does not fix:

- `multiple_list_hit_bonus` fires on `len({hit.list_name}) > 1`, so a direct OpenSanctions hit plus a bibliometric co-author hit against 1260H reads as "two independent lists corroborate" — when it is one direct and one second-order signal.
- `ScoringRubric` has no bibliometric weight, so Epic F's "change the weighting if I disagree with it" cannot express *"I trust a direct name match more than a co-authorship inference"* — the single disagreement an analyst is most likely to have.

Proposed, if approved:

- Add `bibliometric_hit_weight: float = 25.0` to `ScoringRubric` (half of `screening_hit_weight`'s 50.0 — a defensible default, and the point is that it is now adjustable, not that 25 is correct).
- `score_entity` partitions hits on `producer == "bibliometric"`, emits `factors["screening_hit"]` from the max-confidence non-bibliometric hit and `factors["bibliometric_hit"]` from the max-confidence bibliometric hit.
- `multiple_list_hit_bonus` counts distinct `list_name` among **non-bibliometric** hits only.
- `api/main.py:rubric_overrides` and `app.py`'s `RUBRIC_SLIDER_RANGES` gain the new field.

Backward compatibility is fine: `rubric_from_dict` already falls back to stock defaults for missing fields, so old `RunManifest`/`ExportManifest` rubric blocks still load. Existing scoring tests and the demo's numbers **will** change — update them deliberately, and note the change in `docs/methodology.md`.

While in `score.py`, add a short docstring note that scoring uses only the single highest-confidence hit per factor, so an entity with 1 hit at 0.95 and one with 40 at 0.95 score identically. That is a defensible choice (it stops the bibliometric layer's volume multiplication dominating the ranking) but it is currently undocumented and surprising.

### Test

New `tests/test_output_contract.py` — see the Cross-cutting section below. This is the file that makes 5 and 6 permanent.

---

## Workstream 6 — Move the OpenAlex caveat and licence attribution into the data (Finding 6)

Epic E's third criterion is explicit: *"every result surfaces OpenAlex's own stated match-precision caveat inline, not buried in documentation — a persistent disclaimer alongside every bibliometric result."* `OPENALEX_PRECISION_DISCLAIMER` lives at `app.py:31` as an `st.caption`. Verified: no caveat text reaches the CSV or the API. An analyst exporting the CSV — the workflow Epic G exists for — gets a bibliometric hit at confidence 1.0 with nothing attached. "Buried in the UI layer" is a variant of the failure the criterion was written against.

The same gap exists for Section 10's *"licence terms tracked per source and **surfaced in output**, not just in a README"* — fully documented in `docs/data_sources.md`, absent from every exported row.

**The codebase already knows the right pattern.** `TopicSimilarityFlag.recommendation` is a dataclass field with a default, so the caveat travels with the data through storage, DTO and UI and no consumer can drop it. Do the same here.

### Design

New `entity_screening/common/attribution.py`: a module-level mapping from source/list identifier to `{attribution, license, caveat}`, with the strings lifted verbatim from `docs/data_sources.md` so there is one wording and two readers. Add a docstring pointing at that file as the canonical prose source, and a note that the two must be kept in step.

Each producer injects `evidence["source_attribution"] = attribution_for(<source>)`:

- `screen.py` and `section_117.py` — keyed on the matched concern list.
- `cross_check.py` — the concern list's entry **plus** the OpenAlex precision caveat, since a bibliometric hit inherits uncertainty from both.

No DTO or export changes needed: `evidence` is already serialized whole through both boundaries, which is exactly why this is the right shape.

`app.py` then reads the caveat from the hit rather than from its own module constant — delete `OPENALEX_PRECISION_DISCLAIMER` so there is no second copy to drift.

### Test

Covered by `tests/test_output_contract.py` below. Add a `cli.py validate` check that every registered list name has an attribution entry, so adding a list without attribution fails CI.

---

## Workstream 7 — Honest ownership traversal (Finding 7)

`ownership/graph.py:parent_chain` runs a `WITH RECURSIVE` CTE with `UNION ALL`, no visited set, then flattens every result into one tuple ordered by depth. Correct for a linear chain, wrong otherwise. Verified:

```
branching (SUB has two direct parents P1, P2):
  parent_chain    -> chain=('P1','P2','TOPA','TOPB')  truncated=False
  ultimate_parent -> ('TOPB', False)     <- chain[-1] picks ONE arbitrarily
cyclic A<->B:
  chain=('B','A','B','A','B')  truncated=True
```

`flagging.py:flag_from_match` then writes `full_path = (match.lei, *result.chain)` into `ForeignControlFlag.relationship_path` — **a path that does not exist in the data**, an ordering artifact presented as evidence. For a system whose non-negotiable is traceability, a fabricated evidence path is the worst-shaped bug available. Epic C's criterion says depth and direction must not be "collapsed into a single value"; depth and direction are handled well, but *branching* is collapsed.

### Design (verified — implement as specified)

Carry the path in the CTE and guard cycles with `NOT list_contains(path, r.end_lei)`. Verified on DuckDB 1.5.5:

```
branching SUB: [(['SUB','P1'],1), (['SUB','P2'],1), (['SUB','P1','TOPA'],2), (['SUB','P2','TOPB'],2)]
cyclic X:      [(['X','Y'],1)]    <- terminates, no repeats
leaf (terminal) paths from SUB: [(['SUB','P1','TOPA'],2), (['SUB','P2','TOPB'],2)]
```

The leaf-path variant — adding `AND NOT EXISTS (SELECT 1 FROM gleif_relationships r WHERE r.start_lei = w.node AND NOT list_contains(w.path, r.end_lei))` — returns exactly the distinct real chains, which is what `ultimate_parent` and `flag_from_match` actually need.

- `ParentChain` becomes `chains: tuple[tuple[str, ...], ...]` plus `truncated: bool`. Update `ParentChainOut` in `dto.py` and the `/runs/{run_id}/ownership/{entity_id}` route accordingly. This is a breaking DTO change; it is a portfolio demo with no external consumers, so take the clean shape rather than a compatibility shim.
- `ultimate_parent` returns every distinct terminal node, not one.
- `flag_from_match` emits **one `ForeignControlFlag` per distinct foreign ultimate parent**, rather than picking arbitrarily. This mirrors the house principle already established by `disambiguate_pi_to_openalex_author`, which returns a list of tied candidates rather than forcing a pick — same reasoning, same shape.

**That requires dropping the primary key on `ownership_flags`** (currently `PRIMARY KEY (entity_id, run_id)`, which forbids more than one flag per entity). Follow the precedent already set by `openalex_author_matches`, whose DDL has no PK and carries a comment explaining exactly why. Write the equivalent comment here. `insert_ownership_flags` already deletes by `run_id` first, so removing the PK does not create a duplication path. Note the same `ALTER`/recreate migration concern as Workstream 4 — DuckDB cannot drop a PK in place, so this needs a recreate-and-copy in `connect()`, guarded so it runs once.

`score_entity` already uses `max(ownership_flags, key=match_confidence)`, so multiple flags per entity need no scoring change.

### Docs

`docs/methodology.md`'s "A foreign-control flag inherits the uncertainty of two separate matches" bullet becomes three: the name-to-LEI match, truncation, and now **branch ambiguity**. `ForeignControlFlag`'s own docstring is unusually careful about the depth-honesty problem — extend it to the adjacent problem it did not anticipate.

---

## Workstream 8 — Make the demo show something (Finding 8)

With shipped defaults the deployed demo screens 53 entities, finds 0 candidate matches, and — because "Show only candidate matches" defaults to checked — renders an **empty table**. Section 4 names recruiters and hiring managers as the audience and Section 2 asks for a project needing no explanation of relevance.

The structural cause is real and correct (NSF only funds US-based recipients, so direct name matches are always zero; `awardeeCountryCode=CN` returns `totalCount: 0`). The proximate cause is smaller: the default `opensanctions_file` is `tests/fixtures/sample_opensanctions_targets.csv` — **three rows**, one of which is a deliberately-null test row. The 1260H list ships 214 real entries and is doing real work; the OpenSanctions side of the demo is a unit-test fixture.

### 8a — Cheap wins, do these

- Default "Show only candidate matches" to **unchecked**, so 53 screened entities with scores and provenance are visible on load rather than a blank table.
- Add a short "what you're looking at" panel above the table, including the empirical `awardeeCountryCode=CN → totalCount: 0` finding. That zero is genuinely interesting and currently lives only in a doc — it reads as a *finding* when explained and as a *broken demo* when not.

### 8b — Ship a pre-computed enriched run (recommended)

The dataset was deliberately curated around a real, verified hit: Rod A. Wing (`A5006286921`) → two real co-authored papers → BGI Genomics (`I4387152444`) → a real DoD 1260H entry. That is the demo's whole payoff and it is currently behind a slow, now-gated live API call.

Commit a pre-computed run — `data/demo/` with its DuckDB rows and manifests, loaded on first boot — so the bibliometric evidence trail is visible on load. This uses only DoD 1260H (US Government work, public domain) and OpenAlex (CC0), so it carries no redistribution question. Pairs with Workstream 2b: enrichment can be disabled publicly without the demo losing its point.

### 8c — Curated real OpenSanctions subset

**Licensing: checked, and permitted.** An earlier draft of this plan flagged redistribution as an open question. It is not. OpenSanctions publishes the data under **CC BY-NC 4.0**, which explicitly grants *"Share — copy and redistribute the material in any medium or format"* for non-commercial purposes. Committing a curated subset to the public repo is allowed, subject to three conditions that are all easy to meet:

- **Attribution** — creator, copyright notice, licence notice, and a link to the licence. `docs/data_sources.md`'s OpenSanctions entry already covers most of this; add the explicit CC BY-NC 4.0 link.
- **Indicate changes** — a filtered subset is a modification. Ship a short `NOTICE` file beside the fixture stating what was selected, from which download, on what date.
- **No additional restrictions** — do not apply terms or technical measures that stop a recipient doing what the licence permits. (The action gate in Workstream 2a is fine: withholding a service is not restricting a recipient who already has the data.)

Two boundaries worth recording rather than discovering later:

- The **free API-key programme** — which OpenSanctions says does not cover hobby projects — is a separate thing from the CC BY-NC licence on the **bulk downloads**, which is what this project uses. Do not conflate the two; they read as contradictory otherwise.
- OpenSanctions' own gloss makes the paid-licence trigger *"any use inside a for-profit business... even for compliance screening that generates no revenue"* — i.e. the trigger is the business context, not revenue. A personal portfolio project sits outside it. Running this inside an employer would not.

None of this is legal advice; the two source pages are a five-minute read and worth doing once directly.

**Build:** `tests/fixtures/demo_opensanctions_targets.csv`, the same way `demo_nsf_awards.json` was built — a few thousand real rows including the Seven Sons entries already verified present in the real file — with provenance recorded in `docs/data_sources.md` exactly as the NSF demo dataset's is. Workstream 6's attribution-in-`evidence` change then satisfies the CC-BY attribution requirement and Section 10's "surfaced in output, not just in a README" NFR in the same stroke.

This is a genuine improvement but not load-bearing: 8b already carries the demo, so this can slip without the front page reverting to empty.

---

## Workstream 9 — Bibliometric enrichment: the timeout, and the three problems behind it (Finding 9)

**Live symptom:** clicking "Enrich with bibliometric data" against the 53-entity demo dataset fails in the UI with `Bibliometric enrichment failed: ...Read timed out. (read timeout=120)`.

### What is confirmed

- **nginx is not the bottleneck.** `infra/nginx/monops.conf` sets `proxy_read_timeout 86400` and `proxy_send_timeout 86400`.
- **uvicorn/FastAPI has no timeout of its own.** The route is `def`, not `async def`, so FastAPI runs it in its threadpool and simply keeps working.
- **`app.py:98`'s `requests.post(..., timeout=120)` is the only timer in the path.** It surfaces through `except requests.RequestException` at `app.py:202`, which is where the error string above comes from.
- **The work is genuinely large now and never was before.** The old 2-entity fixture had 3 PI names with modest publication counts.

### Measured call volume

Counted by running the real `enrich_bibliometric` against the real `tests/fixtures/demo_nsf_awards.json` through the real pipeline with a call-counting `fetch`:

```
53 entities resolved
                       1 candidate/PI    3 candidates/PI
  institution_search        53                53
  author_search             61                61
  works walks               61               183
  TOTAL                    175               297
```

Real pagination sits on top of the works-walk figure — Rod Wing alone is 3 pages at `per_page=200`.

**Note where the multiplier is.** The works walk is **per resolved author *candidate*, not per PI**. `disambiguate_pi_to_openalex_author` deliberately returns every candidate clearing the threshold rather than forcing a pick, and `cross_check_bibliometric` then calls `get_author_works` on each. `docs/plans/2026-09-01-v3-openalex-bibliometric-affiliation-layer.md`'s Finding 3 records a real PI resolving to three. Any estimate reasoning "one walk per PI" is low by that factor, and the no-forced-pick design — which is correct and should not change — is what makes it so.

### Three root causes, not one

1. **Volume.** 175–297 sequential calls, above.
2. **The 429 retry added in `40ca51b` converted the crash into latency.** `_http_get` sleeps `min(Retry-After or backoff, 30s)`, up to `MAX_RETRIES = 3`, per call — so a throttled call can add up to 90 seconds of pure sleep. At this call volume the rate limiting that motivated that fix is now routinely hit. "It was crashing" and "it's slow" are the same story, and any timeout value has to budget for retry sleep, not just network time.
3. **`_http_get` retries only on 429.** A single 500/502/503 or `requests.ConnectionError` anywhere across 175–297 calls still aborts the whole enrichment and discards every hit already found — exactly the failure the 429 retry was added to prevent, just via a different status code. Negligible at 3 calls; likely at 297. From the UI it is indistinguishable from a timeout, so it will be misdiagnosed as one.

### Why "the API may still be working in the background" is the problem, not the reassurance

It is true — the hits are persisted by `storage.insert_screening_hits`, and `GET /runs/{id}/scores` runs on every Streamlit rerun, so results can appear silently a minute later. Three consequences follow:

- **Retrying after a timeout duplicates the evidence trail.** `insert_screening_hits` is append-only for the bibliometric path (Workstream 4). Timeout → the API finishes anyway and writes N hits → the user clicks again → 2N. Every impatient retry compounds, in the UI inspector and in the CSV alike. **This is why Workstream 4 must land before this one** — raising the timeout on top of a non-idempotent write turns an annoyance into silent data corruption.
- **Abandoned requests are uncancellable and hold a threadpool worker.** Because the route is `def`, each one occupies a worker for its full duration. On a public URL with an ungated enrichment button on a 2 GB box, a handful of clicks exhausts the pool and the whole API — `/health` included — stops answering. Workstream 2b (gating the button) is the mitigation; this is a second reason it matters.
- **It is also the cheapest confirmation of the diagnosis.** After a timeout, wait and interact with the page; if hits appear, the API finished and the client gave up early.

### Before choosing a timeout value: measure it

Do not pick a number from this document. The CLI calls `pipeline.py` in-process with no HTTP client in the path and therefore no 120-second ceiling:

```
python -m entity_screening.cli run --nsf-file tests/fixtures/demo_nsf_awards.json \
    --opensanctions-file tests/fixtures/sample_opensanctions_targets.csv \
    --enrich-bibliometric --openalex-contact-email <address>
```

Time that. It gives the real budget, and running it twice tells you how much of the total is retry sleep. Live OpenAlex latency could not be measured while writing this plan — `api.openalex.org` is blocked by egress policy from both the review container and the desktop VM — so the call counts above are exact and the wall-clock is not estimated at all.

### 9a — Per-call timeouts *(depends on Workstream 4)*

`app.py:_api_post` hardcodes `timeout=120` for every call. Give it a `timeout` parameter. Keep 120s for `POST /runs` — a reasonable guardrail on a synchronous screening run — and give the bibliometric and topic-similarity calls their own much longer value, set from the measurement above with headroom for retry sleep. Wrap both in `st.status` so the user sees progress rather than a frozen page: Streamlit will drop the websocket on a long synchronous POST regardless of the client timeout, so a bigger number alone may not even produce a visible success.

### 9b — Fetch each author's works once per run

`enrich_bibliometric` calls `get_author_works` per resolved author; `enrich_topic_similarity` then calls it **again** for the same authors in `embed_and_persist_papers`. Running both doubles the OpenAlex traffic and the wall-clock.

Persist works once into a new `raw_openalex_works` table keyed `(run_id, openalex_author_id)` and have `embed_and_persist_papers` read them back. This is the single biggest wall-clock win available, and it makes the topic-similarity layer runnable with no network at all once enrichment has run — a real robustness gain given the egress problems already documented in this project. Give the insert the same `DELETE ... WHERE run_id = ?` treatment as its siblings (Workstream 3's lesson).

### 9c — Cap the works walk, and put the cap in the manifest

`get_author_works` pages with no limit and accumulates into one Python list — 456 works for Rod Wing, three sequential round-trips, all in memory. This is also the only load-to-memory path left in a project whose Section 10 NFR requires streaming at scale.

Add `max_works: int | None = None` to `get_author_works`; `enrich_bibliometric` and `enrich_topic_similarity` pass a configurable cap. **Record it as `max_works_per_author` in `BibliometricSnapshotManifest`** — a silently truncated works history is a reproducibility claim you can no longer make, and this project's discipline is that such facts go in the manifest. This is the same treatment `ParentChain.truncated` already gives the ownership walk, which arguably makes the cap an improvement rather than a trade-off. Adding a field with a default keeps `.load()` working on existing manifest files.

Apply the cap to the **works walk**, not to the candidate list. Capping tied author candidates instead would silently reintroduce the forced pick that `disambiguate_pi_to_openalex_author` exists to avoid.

### 9d — Widen the retry predicate

Retry on 429 **plus 5xx plus `requests.ConnectionError`/`Timeout`**, keeping the existing `Retry-After` handling and bounded backoff. Extend `openalex_client.py`'s module docstring account of the real 429 incident rather than replacing it — and add the call-volume figures above, since they are what makes a transient 5xx a near-certainty rather than an edge case.

### 9e — Optional, only if 9a–9d leave it too slow

Bounded concurrency on the institution-search and author-search phases (`ThreadPoolExecutor(max_workers=4)` or similar), which are embarrassingly parallel. Deliberately listed last: it multiplies request rate against a shared free-tier quota and will trade a latency problem for a 429 problem. Do not reach for it until 9b has removed the duplicate works traffic and the measurement says it is still needed.

### Tests

- `tests/test_openalex_client.py`: extend the existing three retry tests to cover a 500 then success, and a `ConnectionError` then success. Assert the total sleep is bounded.
- `tests/test_pipeline_bibliometric.py`: assert `get_author_works` is called exactly once per resolved author across an `enrich_bibliometric` + `enrich_topic_similarity` pair — the call-log fixture `_fake_fetch_factory` already supports this and it is the direct regression test for 9b.
- Assert `max_works_per_author` appears in the written `BibliometricSnapshotManifest`.

### Docs

- `docs/methodology.md`: add a known-limitation bullet for the works cap, stating that a capped run's bibliometric coverage is partial by design and that the cap is recorded in the run's own manifest.
- `docs/architecture.md`: note the `raw_openalex_works` table in the storage description and that topic-similarity reads it rather than re-querying.

---

## Cross-cutting: the two test files that prevent recurrence

Four of the nine findings were invisible to a suite of 167 tests because the suite tests the function that implements a guarantee rather than the boundary that delivers it. Two new files fix the class, not just the instances.

### `tests/test_output_contract.py`

Build one run containing **one hit from each producer** (`direct_name`, `section_117`, `bibliometric`) plus one ownership flag, then assert against the **outermost artifacts** — the parsed CSV row and the `GET /runs/{id}/scores` JSON, not the objects that build them:

- every hit carries `matched_field`, `producer`, `list_name`, `matched_variant`, `confidence`, `status`
- every hit's evidence carries `source_attribution` with non-empty `attribution` and `license`
- every **bibliometric** hit's evidence carries a non-empty OpenAlex precision `caveat`
- no output field anywhere contains the string `"confirmed"`
- `status` is `candidate_match` whenever hits or ownership flags exist, `no_hit` only when neither does

This single file guards Workstreams 5 and 6 permanently and is the direct answer to the pattern behind the evaluation.

### `tests/test_idempotency.py`

For each of `enrich_ownership`, `enrich_bibliometric`, `enrich_topic_similarity`: run twice against one `run_id` with fixed fakes and assert (a) the returned results are equal, (b) row counts in every table the step writes are identical after both, and (c) rows written by *other* producers survive. Guards Workstreams 3 and 4, and would have caught both before they shipped.

---

## Suggested commit sequence

| # | Commit | Workstream | Gate |
|---|---|---|---|
| 1 | Stop paper embeddings duplicating on re-run | 3 | Silent wrong answer |
| 2 | Add `producer` to screening hits; make enrichment steps re-runnable | 4 | Enables commits 7 and 10 |
| 3 | Ship a pre-computed demo run and show it on load | 8a + 8b | **Prerequisite for commit 4** |
| 4 | Gate actions; allowlist paths; stop auto-run; rate-limit; noindex | 2 | Before any public link |
| 5 | Make acronym matching reachable through the blocking step | 1 | Epic B criterion |
| 6 | Carry attribution, licence and the OpenAlex caveat in evidence | 6 | Epic E + §10 criteria |
| 7 | Surface `matched_field` and producer in the API and export | 5a | Epic D criterion |
| 8 | Add a bibliometric scoring weight *(only if 5b approved)* | 5b | Behavior change |
| 9 | Add the output-contract and idempotency test files | cross-cutting | Prevents recurrence |
| 10 | Fetch each author's works once; cap and record it; widen retries; per-call timeouts | 9 | The timeout — **requires commit 2** |
| 11 | Curated real OpenSanctions demo subset | 8c | Optional; licence cleared |
| 12 | Report branching and cyclic ownership chains honestly | 7 | Epic C criterion |
| 13 | Update plans index; final docs sweep | — | Housekeeping |

Commits 1–4 are the ones that matter if the pass gets interrupted. Note that 3 moved ahead of the lockdown deliberately: gating run creation before there is a pre-computed run to display would leave an anonymous visitor with a blank page and a disabled button, which is worse than today's empty table.

Commit 9 can move earlier if you want the tests failing first — several will fail before their fix lands, which is a legitimate way to run this.

**If the bibliometric timeout is blocking demo work,** commit 10 can move to immediately after commit 2. It depends on commit 2 and nothing else, and the dependency is not negotiable: raising the timeout while `insert_screening_hits` is still append-only for the bibliometric path means every timeout-then-retry silently doubles the evidence trail. See Workstream 9's "Why 'the API may still be working in the background' is the problem" for why.

---

## Explicitly out of scope for this pass

- **Epic J** (LLM-grounded explanations). Still correctly deferred. Nothing here blocks it; Workstream 6 arguably helps it, since attribution and caveats in `evidence` are exactly the retrieval context Section 9a specified.
- **Real transliteration** (Cyrillic, pinyin). `normalize.py:transliterate` folds Unicode combining marks only, which covers `Société Générale` and nothing a sanctions screener would call transliteration. Rather than half-build it, either narrow Epic B's wording in `requirements.md` to "diacritic folding" or name `unidecode`/`nomenklatura` as the V4 path — a one-line honest edit either way, and worth doing in commit 12.
- **Cross-source entity resolution.** `resolve_entities_from_nsf` groups by exact normalized name, so "Montana State University" and "Montana State University-Bozeman" stay separate. Documented, correct for V1, out of scope here.
- **Un-streaming OpenSanctions.** `run_screening` calls `list(os_ingester.stream_records())`, materializing the whole 1.22M-row targets file as `SourceRecord` objects — the streaming ingester streams and the pipeline immediately un-streams it. This is a genuine Section 10 scale gap and larger than anything in this pass; it wants its own plan. Worth adding to `docs/methodology.md`'s known limitations in commit 12 so it is recorded rather than carried silently.
- **Splink.** Still correctly a V2/V3 stretch per Section 7.
- **Real user accounts.** Workstream 2a's shared secret is deliberately not an auth system — no per-user identity, no session management, no credential storage. That is the right size for one person gating four buttons on a hobby demo, and building anything more would be scope this project does not need. If the demo ever needs genuine multi-user access control, that is a different plan.
- `Project Monops Logo.jpeg` at the repo root, unreferenced, with a space in the filename. Move it under `docs/` or put it in the README header — trivial, do it in commit 12.

---

## Verification before calling the pass done

1. `pytest -q` green, and the count has grown by the new contract/idempotency tests.
2. `python -m entity_screening.cli validate` green, including the new attribution-coverage check.
3. CI green on all three jobs — `test`, `vss-real-model`, and `docker`. The `docker` job asserts hard-coded counts (`entities_count == 2 and hits_count == 1`) against `sample_nsf_awards.json`; Workstream 1 could legitimately change `hits_count`. If it does, update the assertion **and say so in the commit message** — a changed expected count is a real behavior change, not a test to bend.
4. A real end-to-end run against `demo_nsf_awards.json` with the full pipeline, confirming: bibliometric enrichment run twice produces identical hits; topic-similarity run twice produces identical non-empty flags; the exported CSV carries `matched_field`, `producer`, attribution and the OpenAlex caveat on the right rows.
5. **Bibliometric enrichment completes through the UI, not just the CLI.** Time the CLI run first (Workstream 9), set the UI timeout from that measurement with headroom, then confirm the button actually returns a result in the browser — and that clicking it twice leaves the hit count unchanged.
6. Redeploy and confirm the public instance: shows the pre-computed run on load without starting a new one; leaves the scored table, evidence trail and export open with no secret; refuses run creation and all three enrichments without the action secret and accepts them with it; rejects an out-of-allowlist path with a 400; returns `X-Robots-Tag: noindex, nofollow` on `/monops` (`curl -sI https://mikejennings.dev/monops/`) and serves `/robots.txt`.
7. `docs/methodology.md`, `docs/architecture.md`, `docs/data_sources.md` and `docs/deployment-runbook.md` all reflect what shipped — with particular attention to the limitations bullets this pass makes obsolete. A stale limitations section is worse than none, because this project's credibility rests on that section being trustworthy.
