# Epic J — Evidence-grounded explanation generation

*Plan as approved via Claude Code plan mode, 2026-09-15. Historical record — read
`git log` for what actually shipped, and the Implementation note at the end of this
file for one deviation worth flagging rather than silently absorbing.*

---

## Context

`docs/requirements.md` §9a named Epic J at V1 time specifically so evidence records
would be built LLM-ready from the start — and they are: `test_evidence_is_self_contained_
without_a_further_join` has enforced this since V3. Four observation types now share
the exact shape Epic J was scoped against (confidence-scored, evidence-carrying,
`MatchStatus`-typed, never a bare boolean): `ScreeningHit` (batch pipeline),
`ConcernTie` and `Finding` (the HB127/COI case worksheet), and RPS's `ScreeningMatch`
(`rps_schema.py`'s own docstring: "Same shape as `common.schema.ScreeningHit`/
`ConcernTie`'s evidence"). This plan builds the explanation generator against that
shared shape.

**The design tension this plan exists to resolve, stated first.** Every boundary this
project enforces elsewhere is enforced in the type system — `Subject.synthetic`
rejects `False` in `__post_init__`, `_OBSERVATION_GRAPH_ALLOWED_FIELDS` is checked by
`cli.py validate`, `ConcernTie` simply has no field that could hold "would prevent."
Those work because the forbidden thing is an enumerable slot. Free text has no slots —
"this appears serious" isn't a forbidden field, it's a forbidden *shape of sentence*,
and natural language has no closed vocabulary of those. A prompt instruction alone
("state facts only") is a request, not a guarantee, and would be the one mechanism in
this codebase weaker than everything else in it. This plan's binding design position,
worked out with the user before any code was written:

1. **Most of an explanation is templated recitation, not generation.** A fixed
   narrative skeleton per `FactualBasis`/`TieKind`/list-hit shape (all already closed
   enums) states what was found, what was declared, what kind of gap it is, and any
   prior adjudication history — filled from evidence fields, never composed freely.
2. **Exactly one generative step is allowed**: a short synthesis sentence connecting
   multiple findings/ties into a "here's the pattern" reading — the one thing a
   template genuinely can't do, and the actual reason Epic J calls for an LLM at all
   rather than a template engine. (Too tight and there's no real Epic J left to build;
   too loose and it breaks the one discipline this codebase has held everywhere else —
   this is a calibration dial, not just a risk dial, and the plan lands deliberately
   on the tight side of it.)
3. **That one sentence is verified two ways, mechanically, before it is ever stored or
   shown** — not documented as a hope, enforced as a gate an ungrounded or
   evaluative output cannot pass:
   - **Grounding**: every named entity, date, or figure the sentence states must
     resolve back to the evidence payload it was given (below: enforced via Claude's
     native document-citation feature, not a hand-rolled string search).
   - **Lexicon**: the sentence must contain none of a forbidden-vocabulary list —
     the prose-appropriate extension of `_FORBIDDEN_OBSERVATION_FIELD_TOKENS`
     (`common/schema.py:670`), which already bans "severity/risk/priority/tier/
     disqualif..." as *field names* but can't catch "concerning," "suspicious,"
     "clearly indicates," or a judgment-laden "should"/"warrants" applied to the
     person, since those are prose, not field names.
   A sentence that fails either check is regenerated (bounded retries) or dropped —
   the explanation ships with recitation only. This mirrors "unrepresentable, not
   merely discouraged" applied to generated text: a non-conforming synthesis sentence
   is never persisted, not persisted-with-a-warning-flag.
4. **Named residual risk, not claimed away**: even a citation-clean, lexicon-clean
   sentence can still editorialize through *emphasis* — always leading with the most
   damning fact, or omitting an exculpatory one that was in the evidence. Neither
   check catches this mechanically. Documented as an open gap in the new design doc,
   the same way the gubernatorial-designation path and OFAC-embargoed-country
   screening are documented gaps elsewhere, not glossed over.
5. **A second, sharper risk specific to this domain**: the evidence handed to the
   model is adversarial-context data by construction — sanctioned-entity names,
   foreign-adversary-list entries, a subject's own self-reported declaration fields
   that they may have incentive to misrepresent. A looser generative step reading
   that text is exposed to a crafted string nudging the narrative's framing — the
   RAG-equivalent of prompt injection. The tight skeleton is close to immune (there's
   nowhere for injected text to redirect generation into; it lands in a slot as a
   literal string); the one generative step is the actual exposure surface and gets
   its own mitigation (below).

## Real-data research done before designing this

- **Evidence shapes, confirmed against the actual code, not assumed** — re-grepped
  fresh rather than trusted from memory, since step 6 (landed earlier this session)
  added `CaseKind` and expanded `Case`'s docstring earlier in `common/schema.py`,
  shifting every class below it down by ~34 lines from where an earlier read in this
  same conversation had them: `Finding` (`common/schema.py:452-476`), `ConcernTie`
  (`:490-525`), `ScreeningHit` (`:53-73`, unaffected — precedes the step-6 edit),
  RPS `ScreeningMatch` (`screening/rps_schema.py:113-128`, unaffected — different
  file). All four are
  confidence-scored, evidence-carrying, closed-enum-classified (`FactualBasis`,
  `TieKind`, list-hit `matched_field`), and self-contained per the existing
  `test_evidence_is_self_contained_without_a_further_join` bar. No new evidence
  plumbing needed — this was the whole point of doing that work in V1/V3.
- **Claude API guidance consulted (`claude-api` skill) for the actual mechanism**:
  - `citations: {enabled: true}` on a `document` content block is a *native*
    grounding mechanism: the response splits into text blocks, and cited blocks carry
    a `citations` array with `cited_text` and a character location back into the
    document Claude was given. This is a stronger, Anthropic-verified version of "the
    model self-reports which evidence key it used" — the location is computed by the
    API against the literal document text, not claimed by the model. **This plan
    formats the evidence payload as the cited `document`, and requires every
    synthesis-sentence claim to carry a citation resolving into it.**
    (Note: `citations` and `output_config.format`/structured-output are mutually
    incompatible on the same request — confirmed via the skill's docs — so the
    templated-recitation half of the output is built entirely in Python from typed
    fields, never asked of the model at all; only the one synthesis sentence goes to
    Claude, and it goes through the citation-enabled path, not structured output.)
  - **Model choice, reasoned explicitly rather than defaulted**: this is a short,
    structured-context, low-creativity, analyst-triggered (not high-volume batch)
    generation task — one sentence, from a small typed evidence set, on demand. The
    skill's own guidance is that classification/short-structured-generation workloads
    "do well" below the top tier. Recommending **Claude Sonnet 5** (`claude-sonnet-5`,
    $2/$10 per MTok) over Opus 5: this task doesn't call for Opus-tier open-ended
    reasoning, cost-consciousness is itself already a stated design value in this
    project (`docs/requirements.md` §9a's Lightsail choice, "$12/month... deliberately
    not adopted" list), and the tight-skeleton design means Sonnet's job is narrow —
    phrase one sentence, cite it correctly — not carry the whole explanation's
    reasoning load. Documented here as a deliberate, reasoned choice, not a silent
    downgrade.
  - **Prompt-injection-via-evidence mitigation**: keep the evidence payload inside the
    `document` content block (data), never string-concatenated into `system` or an
    instruction-bearing part of the user turn. The system prompt explicitly states
    that the document's content is data to cite, never instructions to follow. The
    citation mechanism itself is a second, structural mitigation — a citation must
    resolve to literal document text, so even a successfully-injected instruction
    inside the evidence can, at most, get quoted back as a citation-flagged excerpt
    (which the lexicon/entity-grounding check would then also have to pass) — it
    cannot cause the model to silently comply with it, since the "one thing the model
    is allowed to do" is narrowly cite-and-connect, not follow arbitrary instructions
    found in its context.
- **Honest limitation, stated rather than glossed**: no `ANTHROPIC_API_KEY` was
  available in this planning environment, so the forbidden-lexicon seed list below is
  drafted from first-hand knowledge of how models in this family phrase
  evidence-based claims when unconstrained (hedged judgment language: "notably,"
  "of particular concern," "raises questions about," "strongly suggests"), not from
  a live call's actual output. **A real-model calibration pass against the live API is
  the first implementation step** (below), not something resolved during planning —
  named explicitly rather than presented as already validated.
- **That calibration pass needs a real regression guard, not a one-time manual
  check** — this project already tried "manual" once and explicitly rejected it:
  `tests/test_topic_similarity_real_model.py`'s own docstring says a bare skip-guard
  "would let this regression guard go quietly unexercised... forever, which defeats
  its whole purpose," which is exactly why it's paired with a dedicated
  `vss-real-model` CI job (`.github/workflows/ci.yml:38-56`) — "a package deal, not
  alternatives." This plan adopts that same structure — a
  `pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), ...)`-guarded test
  paired with a dedicated CI job — rather than a one-off manual pass with nothing to
  re-trigger it. One deliberate deviation from the VSS job's own trigger, reasoned
  explicitly rather than copied blind: VSS's job runs on every push because it
  downloads a free, deterministic local model — no marginal cost per run. This job
  spends real money on a live external call every time it runs, so it's scoped to
  only fire on changes to `explanation/` (a GitHub Actions `paths:` filter) plus a
  weekly scheduled run as a backstop against silent model-behavior drift with no
  code change at all — bounding cost without falling back to "manual," and without
  losing the "something re-triggers this when `model`/`prompt_version` changes"
  property the plan's earlier draft was missing.

## Scope decision

Build the mechanism generically against the shared evidence shape (one module, not
four parallel ones), but wire the API/UI to `ConcernTie` and `Finding` first — the
HB127/COI case worksheet is this project's most polished, most-demoed analyst surface,
and requirements.md's own job story ("a natural-language explanation of why a
candidate match was flagged") describes exactly this moment. RPS's `ScreeningMatch`
and the batch pipeline's `ScreeningHit` are deferred, but only as UI/route wiring —
the generation/verification core takes any of the four unmodified, the same "no new
matching logic" position steps 5/6 established for their own reused mechanisms.

## Design

**1. New module `entity_screening/explanation/`** (mirrors `screening/`'s
self-contained-module precedent, not `common/schema.py` — this is a new capability
layer, not a new observation type in the existing fact/judgment graph):
- `explanation/schema.py`: `MatchExplanation` — `explanation_id`, `observation_kind`
  (`"finding" | "concern_tie"`), `observation_id`, `case_id`, `recitation: str`
  (fully templated, built in Python, never sent to the model), `synthesis_sentence:
  str | None` (`None` when no synthesis cleared verification — recitation-only is a
  valid, complete output, not a failure state), `citations: tuple[Citation, ...]`,
  `evidence_hash: str`, `model: str`, `prompt_version: str`, `generated_at: str`,
  `synthetic: bool`. `synthetic` is propagated from the case/subject exactly like
  `export.py`'s `PROVENANCE_NOTICE` — a free-text paragraph about a fabricated demo
  subject needs this marker *more*, not less, than the JSON export does (use-case-01
  §10's "no fabricated publications attached to a real name" concern is sharper in
  prose than in a JSON blob). No severity/risk/disposition field — same allowlist
  discipline, a `_EXPLANATION_ALLOWED_FIELDS` frozenset checked by `cli.py validate`
  alongside `_OBSERVATION_GRAPH_ALLOWED_FIELDS`.
- `explanation/skeletons.py`: one recitation template per `FactualBasis` member and
  per `TieKind` member (six total today), each a pure function
  `(Finding | ConcernTie) -> str` — plain Python string building from typed fields,
  no LLM call. This is most of an explanation's value and is airtight by construction.
- `explanation/lexicon.py`: `FORBIDDEN_EXPLANATION_TOKENS` — extends
  `_FORBIDDEN_OBSERVATION_FIELD_TOKENS`'s existing tuple with prose-appropriate
  entries (seeded from the calibration pass below, not guessed alone):
  `"concerning"`, `"suspicious"`, `"alarming"`, `"clearly indicates"`, `"strongly
  suggests"`, `"likely indicates"`, `"significant"` (in an evaluative, not
  count/measurement, sense — flagged for the calibration pass to confirm), and
  judgment modals (`"should"`, `"warrants"`) when the sentence's subject is the
  person rather than a procedural next step. `is_clean(sentence: str) -> bool` (or
  equivalent) — deterministic, no model call, unit-testable directly.
- `explanation/generate.py`: `generate_synthesis(evidence_document: str, claims:
  ..., *, call: Callable = _default_anthropic_call) -> SynthesisResult | None`. The
  `call` parameter is the injectable-callable pattern this codebase already uses
  everywhere for external services (`fetch=` in `discover_from_publications`,
  `works_fixture` in `reconcile_case`) — tests inject a fixture callable and never
  hit a live model; only the dedicated CI-gated real-model test (§ Tests below)
  hits the real API.
  Builds the request per the research above: evidence as a `citations`-enabled
  `document` block, system prompt stating the document is data-to-cite-not-
  instructions-to-follow, model `claude-sonnet-5`. Runs the citation-grounding check
  (every claim resolves into the document) and the lexicon check; on failure, retries
  bounded times, then returns `None` (recitation-only ships).
- `explanation/service.py`: `explain(conn, observation_kind, observation_id) ->
  MatchExplanation`. Computes `evidence_hash`; if a `MatchExplanation` already exists
  for this exact `(observation_id, evidence_hash)`, returns the cached one — no new
  call. This is the cost/idempotency control (mirrors `_ensure_demo_case_exists`'s
  fixture-version-gated idempotency): a re-run of reconciliation naturally
  invalidates old explanations for free, since `finding_id`/`tie_id` are regenerated
  (`uuid4`) on every reconciliation run — no separate staleness check needed, the
  existing current-state-per-case design already does this.

**2. Persistence**: new `explanations` table (`common/storage.py` `SCHEMA_DDL`,
following the existing DDL pattern), `case/store.py`-style save/load functions keyed
by `(observation_kind, observation_id)`.

**3. API**: `entity_screening/api/case_routes.py` — `POST /cases/{case_id}/findings/
{finding_id}/explanation` and the `ties/{tie_id}` equivalent, gated behind
`require_action_secret` (the same gate mutating actions already use) even though this
is logically a read — because unlike every other GET route here, this one triggers a
real, costed external API call, and the public demo must not let an anonymous visitor
trigger unbounded live calls. For the bundled demo cases specifically
(`demo`/`demo-coi`), the explanation is generated once during the existing demo-build
step (`case/demo.py`'s `build_demo_case`/`build_demo_coi_case`) using the same
fixture-injection pattern the rest of the demo already uses (no live call on any
visitor's click — mirrors "the public demo deliberately doesn't [query live]... the
action controls are locked behind a secret," `pages/0_HB127_Case_Worksheet.py`'s own
explainer text).

**4. UI**: an "Explain this match" expander per worksheet row in
`pages/0_HB127_Case_Worksheet.py`, rendering the recitation and (if present) the
synthesis sentence with its cited spans visually marked — showing the citation
grounding to the analyst is itself part of the "transparent, trustworthy" bar
`docs/requirements.md` §9a's Epic J acceptance criterion states.

## New doc

`docs/plans/<date>-epic-j-evidence-grounded-explanation.md` per this project's
standing practice (not a new `use-case-0X` doc — Epic J is a cross-cutting technical
capability layered on existing use cases, not new statutory/regulatory scope). Content:
this plan, the fact/judgment design position above (§ Context), and the residual
emphasis-framing risk named as an open gap rather than solved.

## Tests

- `explanation/lexicon.py`: unit tests asserting the seed forbidden-token list is
  rejected and a hand-written clean sentence passes — same shape as
  `test_finding_has_no_disposition_or_evidence_field`.
- `explanation/skeletons.py`: one test per `FactualBasis`/`TieKind` member asserting
  the rendered recitation contains the evidence's actual field values and none of the
  forbidden lexicon.
- `explanation/generate.py`: injectable-`call` tests — a fixture callable returning a
  citation-clean response (accepted), one returning an uncited claim (rejected,
  falls back to recitation-only), one returning a lexicon-violating sentence
  (rejected). No live network call in the automated suite.
- `explanation/service.py`: idempotency test — two `explain()` calls for the same
  `(observation_id, evidence_hash)` return the cached row, asserted via the injectable
  `call`'s call count (mirrors the existing OpenAlex-shared-lookup test pattern,
  `docs/plans/2026-09-01-v3-openalex-bibliometric-affiliation-layer.md`'s Finding 1).
- **`tests/test_explanation_real_model.py`** — the real-model regression guard, per
  the research section above: `pytest.mark.skipif`'d on a missing
  `ANTHROPIC_API_KEY` (so the base `test` CI job, which has no key, skips it rather
  than failing), generating a real explanation for the actual demo case's findings/
  ties and asserting the citation-grounding and lexicon checks both pass against the
  real, uncontrolled model output — not a fixture. Paired with a new
  `llm-explanation-real-model` job in `.github/workflows/ci.yml` (mirroring
  `vss-real-model`'s structure exactly, `ci.yml:38-56`) that has `ANTHROPIC_API_KEY`
  configured as a repo secret and actually runs it, triggered on `paths:
  ["entity_screening/explanation/**"]` plus a weekly `schedule:` cron — so a change
  to the prompt/model, or silent model-behavior drift with no code change at all,
  both still get caught, without paying for a live call on every unrelated push.
  The first real run of this test, during implementation, is also the calibration
  pass that finalizes the lexicon seed list against real output rather than the
  first-hand-knowledge draft above.

## Verification

1. `pytest` (full suite) — new tests pass, nothing regresses.
2. `cli.py validate` — confirms `_EXPLANATION_ALLOWED_FIELDS` guard is wired and
   passes.
3. Run `test_explanation_real_model.py` locally with a real `ANTHROPIC_API_KEY` set
   (the same test the new `llm-explanation-real-model` CI job runs); inspect the
   stored `MatchExplanation` rows for correct citation resolution and a clean
   lexicon check against real, uncontrolled output.
4. Load the HB127 worksheet, expand "Explain this match" on a demo finding and a
   demo concern tie; confirm the recitation and synthesis sentence render, citations
   are visually marked, and the synthetic-data marker is present.

---

## Implementation note

**The real-model CI job landed in its own workflow file, not inside `ci.yml` as this
plan's Tests section said.** GitHub Actions path filters (`paths:`) are a trigger on
the whole *workflow*'s `on:` block, not a per-job setting — a job added to `ci.yml`
would still run on every push regardless of what changed, defeating the entire reason
this plan scoped the trigger down from `vss-real-model`'s every-push default. Real
constraint discovered during implementation, not anticipated during planning; the
substance (skip-guard test + dedicated job, `paths:` filter on `entity_screening/
explanation/` + a weekly `schedule:` cron) is exactly as planned —
`.github/workflows/llm-explanation-real-model.yml` is a separate file for a
mechanical reason, not a scope change.

**Explanations for the bundled demo cases are pre-generated at demo-build time using
a fixture callable that always returns no citation** (`case_routes.py:
_demo_no_synthesis_call`), not a hand-written "sample" LLM sentence. Considered and
rejected: fabricating a plausible-looking canned synthesis sentence for the public
demo. That would mean shipping fake generated text labeled as if it came from a real
model call — a strictly worse choice than recitation-only for a project whose whole
ethos is not passing off fabricated content as genuine (use-case-01 §10's "never a
fabricated publication attached to a real name," extended here to "never a fabricated
model output presented as a real one"). The demo therefore demonstrates the
recitation half of Epic J fully and honestly, and the synthesis half only for a
deployment with a real `ANTHROPIC_API_KEY` configured against a non-demo case.
