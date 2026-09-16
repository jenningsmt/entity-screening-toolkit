# Phase 2 — Epic J grounding gate

## Context

`Claude outputs/monops-remediation-strategy-2026-09-15.md` sequences the
2026-09-15 pre-ship review into six phases. Phase 1 (public-surface hotfix)
shipped and deployed. Phase 2 is next: it lives entirely inside
`explanation/`, its tests, and CI, is independent of Phase 1, and must land
before Phase 4 (reconciliation evidence) — Phase 4's fixture regeneration is
the first time this corrected gate meets real demo evidence.

**The problem.** Epic J's one generative step (`generate_synthesis`) is
supposed to guarantee that every claim in its one generated sentence
resolves back to the evidence. Today it only checks that *at least one*
citation exists anywhere in the whole response — with the real Citations
API, a response is normally a sequence of interleaved cited and uncited
text blocks, so the uncited-block case is the expected shape, not an edge
case. On any deployment with `ANTHROPIC_API_KEY` set, this lets the one
generative step assert things the evidence doesn't support — exactly what
Epic J was built to prevent. It's latent today only because the public box
has no key.

All line numbers below were re-read from the current tree on 2026-09-16
(after Phase 1's edits — `explanation/service.py`'s `_evidence_hash` was
already renamed to `evidence_hash_for` there, which matters for M17 below).

**Does this phase change demo evidence?** No — findings/ties are untouched;
only the explanation layer changes, and its output isn't part of the
findings/ties JSON the demo-evidence-diff check covers. Deploy still happens
(the strategy doc's rule: deploy after every phase), but has no visible
effect on the public box, which has no key — the point is that the *next*
key-bearing deployment is safe, and this phase's own real-model job is what
proves that isn't just an assumption.

---

## Build order

### 1. B1 — real per-block citation grounding, not "any citation anywhere"

**Current state.** `entity_screening/explanation/generate.py` (157 lines).
`_extract` (lines 106–125) walks `response.content`, concatenates *all*
text blocks into one `sentence` string, and pools *all* citations from
*all* blocks into one flat list — the per-block association between a
piece of text and its own citations is thrown away. `generate_synthesis`
(lines 135–156) then only checks `if not sentence or not citations:
continue` (line 151) before `is_clean(sentence)` — a non-empty citations
tuple passes regardless of which block(s) it came from or whether its
offsets mean anything. Nothing checks that a citation's
`document_text[start_char:end_char]` actually equals `cited_text`.
`document_text` is already built locally at line 145
(`_build_document(primary, case_context)`), so both checks are pure local
string operations — no new dependency.

`_extract` is not unit-tested directly anywhere (grepped) — only exercised
through `generate_synthesis` — so its return shape can change freely.

**Fix.**
1. Change `_extract`'s return type from `tuple[str, tuple[Citation, ...]]`
   to `list[tuple[str, tuple[Citation, ...]]]` — one `(text, citations)`
   pair per text block, citations kept per-block instead of pooled.
2. In `generate_synthesis`, after `blocks = _extract(response)`:
   - Join the non-empty block texts into `sentence` and flatten citations
     into the tuple first (cheap, needed for the checks below either way).
   - **Keep an explicit `if not sentence: continue` guard** — today's line
     151 (`if not sentence or not citations: continue`) does two jobs:
     reject ungrounded (no citations) *and* reject empty (no text at all).
     The per-block check below correctly replaces the first job, but is
     vacuously satisfied when there are zero blocks or every block is
     whitespace-only — nothing violates "every non-empty block is cited"
     if there are no non-empty blocks. Without this explicit guard, a
     genuinely empty model response would produce `sentence=""`,
     `citations=()`, sail past the per-block check, pass `is_clean("")`
     (trivially `True`), and return `SynthesisResult(sentence="",
     citations=())` — an accepted, empty explanation, which is *worse*
     than today's behavior (today it correctly retries and gives up). This
     guard must stay, not just be replaced by the per-block one.
   - Reject (continue to retry) if any block whose `text.strip()` is
     non-empty has an empty `citations` tuple.
   - Reject if any citation anywhere fails
     `document_text[c.start_char:c.end_char] == c.cited_text`.
   - Keep the existing `is_clean(sentence)` check after grounding, same
     order as today (grounding is now strictly *more* checks, not a
     reordering).
   - Worth stating explicitly (falls out of the change but easy to miss):
     these checks run once per attempt inside the existing
     `for _ in range(MAX_RETRIES + 1):` loop, against a `request` rebuilt
     from the same `document_text` each time — a rejected attempt still
     costs a full API call per retry, same as today; this is not new
     caching or backoff.

**Tests — `tests/test_explanation.py`.** `_fake_response` (lines 122–134)
only builds a single text block; add a second helper,
`_fake_multi_block_response(blocks: list[tuple[str, list[tuple[str, int,
int]]]])`, building one `SimpleNamespace` content block per entry — needed
for the mixed cited/uncited case. Rewrite every existing citation fixture
(`test_generate_synthesis_accepts_a_grounded_clean_sentence` lines 199–213,
`test_generate_synthesis_rejects_a_lexicon_violation_and_falls_back_to_none`
lines 224–232, `test_generate_synthesis_retries_within_the_bound_then_gives_up`
lines 235–244) to use **real offsets computed from the real document**, not
hand-typed numbers:
```python
document_text = generate._build_document(_tie(), [_finding()])
start = document_text.index("NIO INC.")
end = start + len("NIO INC.")
```
— never assert a citation's own correctness by construction; compute it
against `_build_document`'s actual output so a later change to `recite()`'s
templated text can't silently leave a stale, no-longer-matching offset in a
fixture (`test_generate_synthesis_rejects_an_uncited_claim_and_falls_back_to_none`,
lines 216–221, needs no offset changes — it already has zero citations,
which is still correctly rejected under the new logic).

Add the three cases the strategy doc names, run each against the
**unmodified** tree first to confirm today's bug (all three currently
accepted/mis-handled) before applying the fix:
1. **Mixed cited/uncited blocks → reject.** Two blocks via
   `_fake_multi_block_response`: one with a real, correctly-offset
   citation, one with none. `generate_synthesis` must return `None`.
2. **Out-of-range/mismatched offsets → reject.** A citation whose
   `(start_char, end_char)` slice of `document_text` does not equal
   `cited_text` (e.g. an offset past `len(document_text)`, or a
   correct-length but wrong-position slice). Must return `None`.
3. **All-cited, correct offsets → accept.** Every block real-offset-cited
   against `document_text`; `is_clean` passing. Must return a
   `SynthesisResult`.
4. **All-empty/whitespace-only response → reject.** A response with zero
   text blocks, or one whitespace-only text block and no citations. Must
   return `None`, not an accepted empty `SynthesisResult` — this is the
   case the explicit `if not sentence: continue` guard above exists for;
   without it, this fixture would currently (under the buggy rewrite)
   incorrectly pass.

### 2. S14 — whole-word lexicon matching; "notably"/"importantly" without a comma

**Current state.** `_FORBIDDEN_OBSERVATION_FIELD_TOKENS` lives in
`entity_screening/common/schema.py:670–683` (imported into
`entity_screening/explanation/lexicon.py:24`), 12 tokens including `rank`,
`tier`, `score`, `risk`. `lexicon.py`'s `find_violations` (lines 68–81)
checks them at line 76–80 via `any(t in w for w in words)` — substring
containment against each tokenized word — so `"Frankfurt"` (contains
`rank`), `"frontier"` (`tier`), `"underscores"` (`score`), `"brisk"`/
`"asterisk"` (`risk`) all false-positive. Separately,
`FORBIDDEN_EXPLANATION_PHRASES` (lines 33–52) includes the literal strings
`"notably,"` (line 47) and `"importantly,"` (line 48) — comma required —
checked via plain substring-in-lowered-sentence (line 73), so `"Notably the
two records..."` (no comma) doesn't match.

**Fix.**
1. Line 76–80: change `any(t in w for w in words)` to `t in words` — `words`
   is already the tokenized set (`_tokens`, lines 64–65, splits on
   `[a-z']+`), so exact set membership *is* whole-word matching, no new
   logic needed.
2. Lines 47–48: drop the trailing comma from both `"notably,"` and
   `"importantly,"` → `"notably"` / `"importantly"`. The strategy doc names
   only `"notably,"`, but `"importantly,"` has the exact same bug shape
   (comma-anchored phrase missing the no-comma variant) — fixing both is
   the generalized version of the same fix, not scope creep; flagging it
   here rather than silently doing it.

**Tests — `tests/test_explanation.py`'s existing Lexicon section (after
line 164).** Run first against the unmodified tree to confirm today's false
positives:
- Parametrized "must stay clean": `"Frankfurt"`, `"frontier"`,
  `"underscores"`, `"brisk"`, `"asterisk"` each embedded in an otherwise
  clean sentence → `is_clean(...)` is `True`.
- Parametrized "must still be caught": `"rank"`, `"tier"`, `"score"`,
  `"risk"` as bare words in an otherwise clean sentence → `is_clean(...)`
  is `False` (proves the whole-word fix doesn't just delete the check).
- `"Notably the two records name the same institution."` → `is_clean(...)`
  is `False`.

**Explicit non-goal (per the strategy doc's Phase 2/4 boundary):** this is a
structural matching-bug fix, not lexicon recalibration. No new forbidden
words get added in this phase even if S13's real-model run below surfaces a
candidate — that recalibration is Phase 4's job, against the raw outputs
S13 makes visible, not synthetic tests.

### 3. M17 — `case_context` joins the cache key

**Current state.** `entity_screening/explanation/service.py` (87 lines).
`evidence_hash_for` (lines 27–40, already renamed from `_evidence_hash` in
Phase 1) takes only `observation`:
```python
def evidence_hash_for(observation: Finding | ConcernTie) -> str:
    payload = f"{recite(observation)}|{MODEL}|{PROMPT_VERSION}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```
`explain()` (lines 43–83) *receives* `case_context` (5th param) and passes
it into `generate_synthesis(observation, case_context, call=call)` — so the
synthesis sentence is generated from a document that includes
`case_context` — but `evidence_hash = evidence_hash_for(observation)`
(inside `explain()`) never touches it. Two cases sharing an identical
finding get the same cached sentence even if their surrounding ties differ,
because the cache key can't tell the two situations apart.

**Companion fix, not optional.** `entity_screening/api/case_routes.py`'s
Phase-1-added `_cached_explanation_or_404` (the ungated `GET` path) calls
`explanation_service.evidence_hash_for(primary)` with **no** context
argument at all — it never builds one. If `evidence_hash_for`'s formula
changes to fold in `case_context`, this function must build the *same*
context `_explain` builds (lines 507–510: everything else in the case,
minus the primary) and pass it, or the `GET` will compute a different hash
than the `POST` cached under and start 404ing on rows that are actually
cached — a regression Phase 1's own `test_get_explanation_...` tests would
not catch today since they never change context between calls.

**Fix.**
1. `evidence_hash_for(observation, case_context: tuple[Finding | ConcernTie, ...] = ())`
   — fold in the context's recitations, **sorted** before joining:
   ```python
   context_payload = "|".join(sorted(recite(o) for o in case_context))
   payload = f"{recite(observation)}|{context_payload}|{MODEL}|{PROMPT_VERSION}"
   ```
   Sorting matters: `case_context` is built from `store.load_findings`/
   `load_ties`, whose row order isn't guaranteed stable across calls (M10,
   Phase 3, not fixed here) — without sorting, the *same* logical context
   could hash differently between the call that cached a row and a later
   call that reads it, causing spurious cache misses unrelated to any real
   change. Sorting the rendered recitation strings (not the objects) is
   the simplest deterministic fix and needs no id plumbing. (Two distinct
   observations templating to identical recitation text is unlikely but
   not provably impossible — harmless either way, since `sorted()` on
   strings is stable and two identical strings sort identically regardless
   of which object produced them.)
2. `explain()`'s call site: `evidence_hash_for(observation, case_context)`.
3. `case_routes.py`'s `_cached_explanation_or_404`: build the same
   `context` list `_explain` builds (mirror lines 507–510's construction —
   consider factoring it into a shared helper both functions call, since
   B2/Phase 1 already introduced `_find_primary_or_404` for the analogous
   "shared between generate and cached-read" reason) and pass it to
   `evidence_hash_for`.

**Tests.**
1. New test in `tests/test_explanation.py`: same primary `Finding`,
   two different `case_context` lists → `evidence_hash_for` returns
   different hashes. Run against the unmodified signature first (it can't
   even take a second argument yet, so this is inherently the "red" state)
   to make the point concrete, then confirm green after.
2. New test: same primary + same context *reordered* → identical hash
   (proves the sort fix).
3. Update/extend `tests/test_api_case.py`'s explanation tests so a `GET`
   after a `POST`-generated (or demo-pre-generated) explanation still
   returns 200 with the cached row — proving the `GET`/`POST` paths agree
   on the new hash formula, not just that each compiles.

### 4. S13 — make the real-model test non-tautological, against the real demo case

**Current state.** `tests/test_explanation_real_model.py` (147 lines).
`pytestmark` skip-guards on `ANTHROPIC_API_KEY` (lines 44–47) — kept as is,
same precedent as `test_topic_similarity_real_model.py`. The one test
(`test_real_model_synthesis_is_grounded_and_lexicon_clean`, lines 134–147)
calls `generate.generate_synthesis(_real_tie(), [_real_finding()])` against
two **hand-built, synthetic** fixtures (lines 50–131), and asserts
`result.citations` and `lexicon.is_clean(result.sentence)` — exactly the
two conditions `generate_synthesis` already guarantees before returning
non-`None` (doubly so after B1 above tightens that guarantee further). It
returns early with no assertion at all when `result is None`. No raw output
is ever printed or logged. It cannot fail on model behavior — only on an
unhandled exception (bad model id, no key, network error).

**Fix.** Replace the synthetic fixtures with the real demo case's real
findings/ties (same pattern this project already uses in
`tests/test_case_lifecycle.py`'s `_demo_conn` helper — reuse the shape, not
the fixture, since this file needs the raw `Finding`/`ConcernTie` objects,
not a live DB connection to keep open):
```python
def _real_demo_observations(tmp_path):
    db_path = tmp_path / "case.duckdb"
    conn = storage.connect(db_path)
    demo.build_demo_case(conn)
    conn.close()
    reconcile_case(
        demo.DEMO_CASE_ID, db_path=db_path, runs_dir=tmp_path / "runs",
        works_fixture=demo.load_demo_works_fixture(),
        gleif_lei_file=demo.DEMO_GLEIF_LEI_FILE,
        gleif_relationships_file=demo.DEMO_GLEIF_RELATIONSHIPS_FILE,
    )
    conn = storage.connect(db_path)
    findings = case_store.load_findings(conn, demo.DEMO_CASE_ID)
    ties = case_store.load_ties(conn, demo.DEMO_CASE_ID)
    conn.close()
    return findings, ties
```
Select the primary by a stable attribute, not list position (findings/ties
row order isn't guaranteed — same M10 caveat as above):
`primary = next(t for t in ties if t.tie_kind == TieKind.DECLARED_EMPLOYER_ULTIMATE_PARENT)`
— the demo's one ownership tie, its headline case.

Rewrite the test to compute its own assertions from the **raw** response,
independently of `generate_synthesis`'s internal gate (using the same
building blocks B1 restructures — `_build_document`, `_build_request`,
`_default_anthropic_call`, `_extract` — called directly, once, not through
the retry loop):
```python
document_text = generate._build_document(primary, context)
raw_response = generate._default_anthropic_call(generate._build_request(document_text))
blocks = generate._extract(raw_response)

total = sum(1 for text, _ in blocks if text.strip())
uncited = sum(1 for text, cites in blocks if text.strip() and not cites)
sentence = " ".join(t.strip() for t, _ in blocks if t.strip())
print(f"\n[Epic J calibration] sentence: {sentence!r}")
print(f"[Epic J calibration] blocks={total} uncited={uncited}")
for text, cites in blocks:
    for c in cites:
        matched = document_text[c.start_char:c.end_char] == c.cited_text
        print(f"[Epic J calibration] citation {c.cited_text!r} "
              f"offset={c.start_char}:{c.end_char} matches={matched}")

assert total > 0, "model returned no text content"
assert uncited == 0, f"{uncited}/{total} block(s) had no citation at all"
for text, cites in blocks:
    for c in cites:
        assert document_text[c.start_char:c.end_char] == c.cited_text

result = generate.generate_synthesis(primary, context)
print(f"[Epic J calibration] generate_synthesis verdict: "
      f"{'accepted' if result else 'rejected -- recitation-only ships'}")
```
The `uncited == 0` bar is not an invented tolerance — it's the same
grounding invariant B1 makes `generate_synthesis` enforce, restated here
and computed independently from the raw response rather than trusting the
function's own boolean, which is exactly what S13 asks for. **This project
has no `ANTHROPIC_API_KEY` available in this environment either** — this
test cannot be run for real as part of this plan's own verification; it
will run for real the first time CI's `llm-explanation-real-model` job
executes with the secret configured (or whenever Mike runs it locally with
a key). Its own docstring already says the SDK-shape assumptions in
`_build_request` are unverified against a live account (generate.py's
module docstring, lines 10–19) — this test is exactly where that gets
checked, same as it always was; only its *fixtures and assertions* change
here.

Also add a `print` of `document_text` itself on the first run (or at least
on failure, via `pytest`'s default failure capture) so a human reading a
failed CI run sees the actual document the model was given, not just the
verdict.

**Two live calls per run, deliberately.** The snippet above calls
`_default_anthropic_call` once directly (for the raw-output diagnostics and
independently-computed grounding invariant) and `generate_synthesis` again
separately (for the retry-wrapped public function's own verdict) — two
billed API calls per test run, not one. Intentional: the two calls test
different things (the raw invariant vs. the production entry point), and
this file's own module docstring already flags "this job spends real money
on a live external call every time it runs" as the reason its CI trigger
is narrower than the free VSS real-model job's every-push trigger — this
just means that reasoning covers two calls, not one, per run.

**Cheap fix while this file is open anyway.** The module docstring (line
10ish) currently says the dedicated CI job lives "in
`.github/workflows/ci.yml`" — it doesn't; it's the separate
`llm-explanation-real-model.yml` file (see M20 below), and that file's own
comment already explains why it's split out (path filters are
workflow-scoped). Pre-existing, harmless, unrelated to S13's actual fix —
correct the one sentence while rewriting this file's body regardless.

### 5. M20 — CI path filter + a visible skip, not a silent green

**Current state.** `.github/workflows/llm-explanation-real-model.yml` (61
lines). `paths:` (lines 22–24, duplicated at 28–30) lists only
`entity_screening/explanation/**`, the test file itself, and the workflow
file — omits `entity_screening/common/schema.py` (the forbidden-token list
the lexicon imports), `entity_screening/case/demo.py` and the demo fixtures
(what the model is shown, after S13's rewrite above), and `requirements.txt`
(the `anthropic` SDK version). The weekly cron (line 35) is the only thing
that would catch a change to any of those today. When
`secrets.ANTHROPIC_API_KEY` is unset, the pytest step (line 60, run with
`-v`) does print a `SKIPPED (...)` line in the raw log and the job still
exits 0 — so it's not silent at the log-text level, but the GitHub run/PR
check is a plain green success with no annotation anywhere more visible,
indistinguishable from "ran and passed" unless someone opens the raw log.

**Fix.**
1. Extend both `paths:` lists (lines 22–24 and 28–30) with:
   `entity_screening/common/schema.py`, `entity_screening/case/demo.py`,
   `tests/fixtures/demo_case/**`, `requirements.txt`.
2. Add a step after the pytest run that posts a visible warning annotation
   when the secret was absent, so a skip shows up in the GitHub Actions UI
   (run summary, PR checks tab) without failing the job — an unset secret
   on a portfolio project is an expected, legitimate state, not a build
   failure:
   ```yaml
   - name: Flag if the calibration test was skipped (no ANTHROPIC_API_KEY)
     if: always()
     run: |
       if [ -z "${{ secrets.ANTHROPIC_API_KEY }}" ]; then
         echo "::warning::Epic J real-model calibration test skipped -- ANTHROPIC_API_KEY is not set as a repo secret. This run verified nothing about grounding behavior."
       fi
   ```

**Verification.** No test exercises a GitHub Actions workflow file
directly; verify by inspection (the `paths:` YAML lists are correct, the
new step's shell logic is correct) and, since this doesn't run locally,
note in the implementation note that the annotation's actual appearance in
the Actions UI should be spot-checked on the next push that touches this
workflow file.

### 6. S17 — correct `README.md`'s stale Epic J status

**Current state.** `README.md:92–94` still says: *"Epic J (LLM-based
evidence-grounded explanations) remains a deliberately deferred, V3-adjacent
follow-up per `docs/requirements.md` Section 9a — not part of any
currently-scheduled phase."* `docs/requirements.md` (Section 9a, lines
187–192) and `docs/architecture.md` (line 11, plus a module-table entry at
line 209) are **already correct** — both say Epic J was built 2026-09-15
per `docs/plans/2026-09-15-epic-j-evidence-grounded-explanation.md`. Only
`README.md` needs the edit.

**Fix.** Replace the `README.md:92–94` sentence with built-status language
consistent with the other two documents, e.g.: *"Epic J (LLM-based
evidence-grounded explanations, built 2026-09-15) adds one citation-grounded,
lexicon-checked synthesis sentence per case-worksheet finding/tie —
everything else in an explanation stays fully templated."*

---

## Cross-cutting

**Failing test first for every item.** B1's three new fixtures, S14's five
new parametrized cases, and M17's two new hash tests all get run against
the unmodified tree first to confirm they fail/misbehave the way the review
describes, before the corresponding fix lands — same discipline as Phase 1.

**Full suite green, `cli validate` passes**, before this phase is done.

**Deploy is still part of the phase**, per the strategy doc's rule, even
though the public box (no `ANTHROPIC_API_KEY`) shows no visible change:
`git pull` + restart per the runbook, then confirm `/health` and both demo
cases still load. This phase's real value only shows up the next time a key
is configured somewhere — the point of doing it now is that that future
deployment doesn't have to also fix this gate under pressure.

**What this phase deliberately does not do.** No lexicon recalibration
beyond the two structural bugs in S14 (whole-word matching, the comma
gap) — new forbidden vocabulary, if S13's real run surfaces a need for any,
is Phase 4's job, against real raw outputs, not synthetic tests, per the
strategy doc's explicit Phase 2/4 boundary.

**Docs.** Per this project's standing practice, copy this plan verbatim into
`docs/plans/2026-09-16-phase-2-epic-j-grounding-gate.md` and add it to
`docs/plans/README.md`'s index as part of implementing it, with a dated
implementation note appended afterward (not a rewrite) — same pattern as
Phase 1's plan file.

## Verification summary (binding acceptance criteria)

- [ ] Mixed cited/uncited fixture → `generate_synthesis` returns `None`
      (fails on the unmodified tree first).
- [ ] Offset-mismatch fixture → `generate_synthesis` returns `None` (fails
      on the unmodified tree first).
- [ ] All-cited, correctly-offset fixture → `generate_synthesis` returns a
      `SynthesisResult`.
- [ ] All-empty/whitespace-only response → `generate_synthesis` returns
      `None`, never `SynthesisResult(sentence="", citations=())`.
- [ ] Every existing `generate_synthesis` test still passes under real,
      computed offsets (no fixture asserts its own correctness by
      construction).
- [ ] "Frankfurt"/"frontier"/"underscores"/"brisk"/"asterisk" → `is_clean`
      `True`; bare "rank"/"tier"/"score"/"risk" → `is_clean` `False`;
      "Notably the two records..." (no comma) → `is_clean` `False`.
- [ ] `evidence_hash_for` differs when `case_context` differs for the same
      primary observation, and is stable under context reordering.
- [ ] The `GET`/`POST` explanation routes still agree on what's cached
      after the hash-formula change (existing Phase 1 API tests still pass,
      extended if needed).
- [ ] `tests/test_explanation_real_model.py` runs against the real demo
      case's real findings/ties, prints the raw sentence/citations/verdict,
      and its assertions are computed independently of
      `generate_synthesis`'s own gate — deferred to the first real run with
      a live key for actual pass/fail against model behavior.
- [ ] CI path filter covers `common/schema.py`, `case/demo.py`, demo
      fixtures, `requirements.txt`; a skipped run posts a visible `::warning::`
      annotation.
- [ ] `README.md` no longer calls Epic J deferred.
- [ ] Full suite green; `cli validate` passes.
- [ ] Deployed and confirmed (`/health`, both demo cases load) — no visible
      change expected on the keyless public box.

---

## Implementation note (2026-09-16)

All six items landed, in the order above, each with its test written and
run against the unmodified tree first (all four B1 fixtures, all three
S14 cases, and all three M17 hash tests confirmed red for the expected
reason before the fix). Full suite: 384 passed, 1 skipped (the real-model
test, no `ANTHROPIC_API_KEY` in this environment; the pre-existing
git-checkout-dependent test), `cli validate` passes.

**One gap found and closed that wasn't in the plan text: a required
seventh change, `DEMO_FIXTURE_VERSION` bump.** M17 changes
`evidence_hash_for`'s formula to fold in `case_context`. On the live
deployed instance, the demo case's explanations were pre-generated and
cached under the *old*, context-blind hash (Phase 1's B2 work). Without a
fixture-version bump, `_ensure_demo_case_exists` sees the version already
matches and does nothing on the next deploy — so every existing cached
demo explanation would silently orphan (the new hash never matches the
old one), and anonymous visitors would start getting 404 → "enter the
action secret" on "Explain this match" instead of the cached row, a
regression of Phase 1's own B2 fix. Bumped `DEMO_FIXTURE_VERSION` from 5
to 6 in `entity_screening/case/demo.py` so the self-heal rebuilds and
regenerates on the next deploy — needs no live key, since demo
regeneration uses `_demo_no_synthesis_call` (the deterministic,
no-network fixture callable), same as every prior fixture bump. This is
the predictable consequence of the same principle B2's own design note
already named ("a prompt/model bump correctly makes the `GET` 404 rather
than serve a stale row") — just triggered by a cache-key formula change
instead of a `PROMPT_VERSION` bump, and needing the same fixture-rebuild
remedy a schema change would.

Not done as part of this phase, by design: the actual deploy (the box has
no `ANTHROPIC_API_KEY`, so no visible behavior change is expected beyond
the demo case rebuilding once under the new fixture version) and the real
run of `tests/test_explanation_real_model.py` against a live key — both
need the actual deploy step and, for the latter, either a local run with
a key or CI's `llm-explanation-real-model` job with the secret configured.

**Post-review fold-in (2026-09-16, before commit).** `_ensure_demo_case_exists`
(the build-time explanation pre-generation loop) had its own, third,
hand-inlined copy of the exact "everything else in the case" logic
`_case_context_for` now names and shares between `_explain` and
`_cached_explanation_or_404`. Harmless today only because
`evidence_hash_for` sorts recitations before joining (so all three
constructions hash identically regardless of the duplication), but a
future change to either `_case_context_for` call site (e.g. filtering
something out) could silently diverge from what the demo-build path
constructs -- exactly the class of bug M17 exists to prevent, just moved
one level up. Folded `_ensure_demo_case_exists`'s loop onto
`_case_context_for` too, so there is now exactly one place that decides
what "the rest of the case" means. No test changed behavior (confirmed:
full suite still 384 passed, 1 skipped, `cli validate` passes) --
`_case_context_for`'s output is byte-identical to the prior inline
construction, this is a pure de-duplication.
