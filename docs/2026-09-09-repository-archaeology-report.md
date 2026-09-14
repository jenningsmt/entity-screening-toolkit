# Entity Screening Toolkit — Repository Archaeology and Development-Process Retrospective

## Executive Findings

1. **Documented fact:** The project is now **Monops**, a publicly deployed portfolio demonstration, not a completed production screening system. It evolved from corpus-wide organizational matching into a synthetic-person case worksheet with reconciliation, analyst actions and investigative-file exports. The foreign-adversary-country ingester, further use cases and other promised work remain outstanding.
2. **Reasonable reconstruction:** This is substantially more mature than Colony Scout in requirements traceability, explicit review, provenance, integration testing and operational learning. It is not uniformly more disciplined than EDMFI, and the repository cannot establish “most mature” or “most complex” across Mike's entire development history.
3. **Documented fact:** The initial implementation plan explicitly inspected Colony Scout, Ring Density Monitor and Sector Surveyor, named reusable practices, and rejected overstated inheritance claims. It identified ingestion error reporting, per-record provenance and ingestion tests as new standards rather than pretending the predecessor already supplied them.
4. **Documented fact:** A formal specification preceded code, but a stale copy reached the builder. Later, the specification itself proved aimed at an insufficiently defined user. Strong engineering verification did not prevent a product-direction error.
5. **Documented fact as recorded process:** Work was deliberately split between Claude.ai Cowork for planning/research/review and Claude Code in VS Code on Windows for implementation. The build log describes Mike selecting a different model for whole-codebase review. This is direct human-directed role separation, not evidence of a continuing OpenClaw/Hugh/Dave autonomous workflow.
6. **Documented fact:** Verification became broader and more empirical: fixture tests, real-data calibration, API/export contracts, repeat-enrichment checks, Docker networking and commit-provenance assertions, and a separate real-model CI job. This audit passed structural validation plus **277 tests** across two invocations.
7. **Documented fact:** The strongest failures are not hypothetical: acronym matching worked only below a blocking layer; repeat topic enrichment erased flags; an ownership traversal fabricated a path by flattening branches; a public demo exposed inappropriate inputs/actions; a rate limiter broke first-time visitors; and a synthetic ownership chain lost its synthetic label in exported files.
8. **Reasonable reconstruction:** The central weakness shifted from writing code to preserving guarantees across boundaries: planning-to-builder, algorithm-to-pipeline, model-to-export, development-to-container, configuration-to-live deployment, and specification-to-real user.
9. **Documented fact:** Formality did not guarantee follow-through. A required real-GLEIF verification is still pending despite the slice shipping; one approved plan was lost; logging fell behind; and manual live-server fixes were absent from infrastructure code until September 7.
10. **Documented fact:** The project's own retrospective contains chronology conflicts and stale statements. It must be treated as evidence to interrogate, not as the final historical account.

## Evidence Base and Limitations

**Audit date:** September 9, 2026.  
**Repository:** `G:\entity-screening-toolkit-portfolio`.  
**HEAD:** `170992ffd3fb8794a09cee9f261a0e022e8bf157`.  
**Remote configured:** `https://github.com/jenningsmt/entity-screening-toolkit.git`.

Evidence classifications:

- **Documented fact:** directly observable in Git, code, tests or documents. Where an event is only narrated, “documented fact” establishes that the repository records it; it does not independently authenticate the entire narration.
- **Reasonable reconstruction:** an interpretation supported by several artifacts.
- **My later recollection/interpretation:** Mike's retrospective description, including his hope that this is his most mature project.
- **Open question:** an unresolved issue material to the history.

The audit inspected the 92-commit HEAD history, available refs, initial and superseded architecture, implementation and review documents, build log, principal pipeline/schema/storage/case modules, ingestion/matching/ownership/bibliometric code, tests and fixtures, CI, Docker and deployment configuration, and selected significant diffs. It did not read every line of all 160 tracked files. There are 16,266 tracked Python lines: 10,235 outside tests and 6,031 in tests. Forty test modules contain 250 test functions; parametrization produces more executed tests.

The Git repository is not shallow. Retained development refs are master and origin/master; there are no release tags or merge commits in the inspected development history. A `refs/codex/turn-diffs/...` capture is session tooling, not evidence that Codex built Monops. No retained AGENTS.md or CLAUDE.md operating contract was found in the target checkout.

Comparison uses this project's explicit predecessor analysis, the prior Colony Scout archaeology, and targeted checks of EDMFI guardrails, Colony Scout's rubric and Ring Density Monitor provenance patterns. It is not a fresh exhaustive audit of every predecessor.

No remote fetch, deployment, public-site mutation, cloud operation, external API run or installer/container rebuild was performed. Live-site observations below come from dated repository artifacts. Statutory and third-party-service statements are reported as historical design inputs; this report does not independently determine current law, service pricing, sanctions status or legal applicability.

Important conflicts and qualifications:

- Git begins **August 31, 2026**. The September 3 build log says the wrong direction lasted “two weeks” or a “fortnight.” That duration is unsupported by the preserved chronology and conflicts with its own Phase 0 date.
- The deployment plan describes December 10, 2025 to September 2026 as “three months.” Its own dates imply roughly nine months. The recorded CDKTF correction remains useful evidence; the elapsed-time statement is not reliable.
- The September 2 evaluation reports **157 passed, 1 skipped, 7 failed** in its sandbox, while referring to **167 passing** on Mike's machine. These are different reported outcomes and do not arithmetically reconcile without further environment/collection evidence.
- `docs/how-this-was-built.md` ends with “Phase 7 — [Not yet started]” even though September 6 implementation is committed. Some earlier entries deliberately retain “not yet fixed” status after later fixes. These are historical snapshots, not current status.
- The build log was first committed September 3; Phase 3 explicitly acknowledges retrospective reconstruction. It is not a verbatim transcript or independently timestamped diary.

The working tree was initially clean under `git status --short`, subject to warnings about an inaccessible existing pytest cache and user Git ignore file. Tests disabled bytecode and pytest-cache writes and used an isolated temporary directory. Only this report is authorized as a repository change.

## What the Project Is

**Documented fact:** Monops is an AI-assisted learning and portfolio project demonstrating entity resolution, organizational due diligence, public-record affiliation analysis and a researcher-review workflow. Its original motivation was professional relevance beyond Elite Dangerous tooling, including comparison with capabilities described in research-security platform job postings.

The first specification chose open datasets, confidence-based matching, source-traceable evidence, adjustable scoring and phased delivery. Initially the “user” was Mike experimenting with data and a recruiter/hiring-manager/GitHub visitor evaluating the project.

The current visitor-facing workflow begins with a synthetic subject and declaration. It discovers public-record affiliations, compares them with declared affiliations and their scope, surfaces discrepancies and concern ties separately, records analyst actions and reasoning, and exports an investigative file. The batch NSF-derived screening pipeline remains callable but is no longer the UI's primary workflow.

Current major capabilities include:

- NSF, OpenSanctions, DoD 1260H and Section 117 ingestion.
- Normalized-name, alias, acronym and fuzzy matching.
- GLEIF LEI resolution and ownership traversal.
- OpenAlex institution/author resolution and bibliometric checks.
- Optional embedding-based topic similarity, explicitly outside scored screening.
- Batch scoring with editable weights and evidence breakdowns.
- Case intake, declaration scope, reconciliation, two observation types, controlled action reasons, adjudication, certification and reopening.
- JSON/Excel investigative files, redaction defaults and synthetic-data notices.
- FastAPI, Streamlit, Docker Compose and Terraform-based hosting.

**Documented fact:** README explicitly calls it a public, non-classified portfolio project and excludes production compliance/investigative use. The synthetic case demonstration is deployed according to repository accounts. This supports **deployed demonstration, active development**, not “completed production application.”

**Open question:** There is no evidence of institutional adoption, professional analyst acceptance testing or completed production-readiness review.

## Relationship to EDMFI / Predecessor Work

### Explicit methodological inheritance

**Documented fact:** `docs/plans/2026-08-31-v1-minimum-viable-screening-loop.md` records inspection of three siblings before planning:

| Predecessor | Practice explicitly adopted/adapted | Important qualification |
|---|---|---|
| ED Colony Scout | Frozen dataclass scoring rubric, stock defaults, dictionary overrides, factor breakdowns, argparse and flat repository layout | Streamlit/FastAPI replace Tkinter; matching/scoring semantics are newly implemented |
| Ring Density Monitor | Run provenance, parameters, commit identity, snapshot counts/dates, deterministic ordering and pytest layout | Monops initially stores manifests as files rather than copying the provenance database |
| Sector Surveyor | Bounded ingestion of large sources and separation of ingestion from analysis | Plan explicitly finds silent parse-error skipping, absent per-record provenance and absent ingestion tests in the inspected predecessor |

The plan describes the latter deficiencies as **new bars this project sets for itself**, not inherited strengths. `common/manifest.py` independently states that its file-based run manifests mirror Ring Density Monitor's provenance-table pattern.

This is unusually strong evidence of deliberate learning: source inspection informs the requirements rather than similarities being inferred afterward.

### What is not established

**Open question:** No direct transfer of Elite Dangerous analytical algorithms, ring-density constants, sigma normalization, sector coordinates or inherited game fixtures was identified. No copied-module migration comparable to Colony Scout's identical extractors was established.

**Reasonable reconstruction:** EDMFI's influence is principally mediated through later tools and shared engineering principles: evidence traceability, deterministic computation, uncertainty discipline and separation of responsibilities.

The initial plan specifically identifies DuckDB instead of SQLite, Streamlit instead of Tkinter, and pytest rather than Colony Scout's unittest. Those are deliberate adaptations, not accidental divergence.

The requirements also overstate one predecessor comparison: Section 9a says CI and Docker already worked in Colony Scout. Colony Scout supplies CI and Windows packaging evidence, but its inspected history does not supply Docker packaging. That sentence should not be reused as proof of inherited Docker experience.

## Chronological Development Timeline

Dates below distinguish commit history from retrospectively dated documents. Initial UTC timestamps are normalized to America/Chicago where useful. Full hashes appear in the evidence table.

| Date | Commit(s) | Milestone |
|---|---|---|
| Aug 31, 12:51 CDT | `42a4436` | Scaffold: 220-line requirements document, README, package skeleton and dependencies; no implementation tests |
| Aug 31, 19:24–19:28 CDT | `e86fc56`, `f40f313` | Stale requirements synchronized, then V1 committed: 34 reported tests, batch pipeline, Streamlit, CSV/Excel and run provenance |
| Aug 31, 19:39–19:40 | `f3cc81e`, `61862c0`, `627eb1a` | Self-contained evidence, CI and first Dockerfile |
| Aug 31, 20:05–20:36 | `936ed43`, `211ff29`, `63630dd`, `62cd825` | Shared pipeline, FastAPI, thin UI client, multi-run key correction, two-container replacement |
| Aug 31, 20:50–21:30 | `edc8b9f`, `c5a22b1` | Compose integration CI; build-time commit identity corrects null provenance inside containers |
| Sept 1, morning | `0593ddb`, `401eb72`, `3c07677`, `533b340` | DoD registry, approved-plan archive, GLEIF ownership and repository line-ending policy |
| Sept 1, 12:09–12:32 | `c8a3664` through `5380658` | Section 117 plan, real-schema ingestion, normalization, cross-check and real-data verification |
| Sept 1, 13:04–13:33 | `8254109` through `33af483` | OpenAlex layer, author ambiguity handling, Seven Sons coverage test, integrations and real-data false-positive correction |
| Sept 1, 15:53–17:34 | `ed06852` through `822789e` | Optional VSS layer; corpus-specific rankings; dedicated real-model CI job prevents permanent silent skipping |
| Sept 1, 19:32–21:59 | `3be4c7e`, `7c0a524`, `98b26f8`, `861834f` | Terraform hosting and provider lock; real bootstrap-shell and HTTPS redirect corrections |
| Sept 2, 07:01 | `6797fd1` | Documentation states Monops is live on Lightsail |
| Sept 2, 10:29 | `40ca51b` | Real NSF demo dataset; dead endpoint and OpenAlex rate-limit fixes |
| Sept 2, 14:59 | `7c94f23` | Independent codebase evaluation and remediation plan committed |
| Sept 2, 15:06–16:12 | `a35b578` through `66e0689` | Producer-scoped replacement, acronym blocking, attribution/caveats, DTO/export fields, scoring differentiation, graph correction, boundary/idempotency tests and fetch-once/capped works |
| Sept 2, 17:17–19:24 | `5842b8c` through `26586fc` | Demo presentation/data, self-healing screening-only run, action gating, path allowlist, rate limiting and noindex |
| Sept 3, 13:25 | `4980dab`, `b50b6ca` | Public build log and README link; log records product-direction reappraisal |
| Sept 6, 06:49 | `6313004`, `4e5242f`, `13491b4` | Specific researcher-screening use case, requirements reframe and Phase 6 record |
| Sept 6, 08:12–09:37 | `1583c39` through `4e2483d` | Approved implementation plan; case storage/guards, reconciliation, ownership composition, actions/adjudication, export, API and worksheet |
| Sept 6, 09:53 | `821ba2e`, `cb0b123` | Synthetic marker restored to exported files; specification corrected to admit fabricated ownership chain |
| Sept 6, 15:09–19:42 | `844e1b4`, `db94882`, `9a34b68`, `cdce8d6`, `c24238d` | First exported worksheet triggers split between discrepancy Findings and ConcernTies |
| Sept 7, 09:19 | `583a510` | Three live-server fixes finally folded into bootstrap/runbook: cold-cache breakage, missing action secret and TLS configuration clobber |
| Sept 7, 09:28–21:34 | branding/theme commits; `170992f` | Logo, pinned Streamlit theme/version, visitor explanation and case subject line; current HEAD |

The visible project spans approximately one week, not two weeks. The first V1 commit bundles 2,018 insertions across 34 files. Later commits become more incremental, though not uniformly small.

No release-candidate or public-release tags exist. V1/V2/V3 are roadmap milestones, not verified semantic-version release artifacts. The first deployment occurred by the September 1 corrective deployment commits and is explicitly documented September 2; an exact hosting start timestamp was not independently obtained.

## Architecture and Major Capabilities

### Batch engine and service boundary

**Documented fact:** The central architecture is:

`Streamlit → FastAPI → shared pipeline → matching/enrichment/storage/export`

The CLI calls the same pipeline directly. DuckDB supplies embedded analytical storage; source-specific ingesters normalize records into canonical dataclasses. HTTP DTOs are separated from internal models.

`run_screening` writes the canonical baseline scores. `rescore_run` recomputes under a supplied rubric without intentionally replacing baseline score rows. Each export gets an ExportManifest identifying its actual rubric rather than falsely inheriting the original run's rubric.

Ownership, bibliometric and topic enrichment are separate, re-runnable operations. Raw OpenAlex works are persisted once per author/run and reused by topic analysis. Producer tags distinguish direct-name, Section 117 and bibliometric hits, preserving both lifecycle and meaning.

### Analytical methods

- Name normalization, suffix removal, accent folding, acronym generation and RapidFuzz comparisons.
- Name/acronym-prefix blocking for large concern lists.
- Two-stage institution/funder comparisons for Section 117.
- LEI matching followed by SQL ownership traversal with separate paths, depth limits and cycle handling.
- OpenAlex institution-scoped author resolution with shared-ORCID grouping and retained ambiguous candidates.
- Bibliometric institution matching with a separate 0.90 threshold after a live false positive.
- Pinned BAAI/bge-small-en-v1.5 embeddings and independent DoD/CET corpus rankings; provisional top-versus-runner-up margin rather than an absolute cutoff.
- Case reconciliation with a separate 0.90 threshold, declaration-source scope and a near-match band.

“Confidence” is a matching score, not demonstrated probabilistic calibration. Bibliometric author uncertainty remains in evidence rather than being mathematically incorporated into the headline institution-match score.

### Case workflow

`Subject + Declaration → discovery/reconciliation → worksheet → analyst actions → adjudication/certification → export`

Findings describe declaration discrepancies. ConcernTies describe connections to concern-listed entities. Their reason vocabularies differ; both must be actioned before the worksheet can advance. Case states and append-only adjudication records support reopening without overwriting earlier analyst conclusions.

The synthetic demo currently contains **two discrepancies and one concern tie**. Its ownership links are fabricated; the matched concern-list entry is real reference data according to the bundled snapshot.

### Persistence and deployment

DuckDB stores source records, analytical results, current case observations and analyst-action history. JSON manifests cover runs, exports, GLEIF, bibliometrics, topic similarity, reconciliation and investigative files.

Migration behavior includes producer-column addition/backfill, ownership-table reconstruction to remove an incompatible primary key, explicit-column compatibility with old Finding tables, and versioned self-healing demo fixtures. This is concrete migration work, though not a general versioned migration framework.

Docker separates API and UI. Production adds loopback bindings, nginx, systemd, Certbot and Terraform-managed Lightsail resources. Deployment remains operator-driven.

**Limitations:** Filesystem manifests use direct writes, and reviewed delete/insert and table-reconstruction sequences do not themselves show full crash-atomic workflows. Snapshot metadata is not a universal content-addressed archive. Most Python dependencies are unpinned. These constrain reproducibility and recovery claims.

## Development Methodology

**Documented fact as process account:** The build log describes a working agreement:

- Cowork holds requirements, research, plans and top-level review.
- Claude Code implements, runs tests/applications and handles Git from VS Code on Windows.
- Handoffs reference acceptance criteria or approved plans.
- Review reads pushed code/history rather than accepting a builder recap.
- Mike directs scope, supplies domain knowledge and participates in local/deployment verification.

The log says pushes are confirmed by convention. Git proves committed changes, not the individual approval interactions.

**Documented fact:** Plans precede many later feature commits. The first two plans were archived retrospectively on September 1; V1's file explicitly says it was reconstructed from an approval transcript after the original plan file was overwritten. The GLEIF plan was never preserved.

This is not evidence of universal test-first implementation. V1 tests and code land together. Many later commits contain both. Tests are present from the first substantial implementation, materially earlier than Colony Scout's release-stage suite.

The September 2 review imposes a stronger standard: behavioral findings must be reproduced. Its recorded probes distinguish hypothetical defects from observed ones. The remediation plan even prototypes two non-obvious fixes before handing them to the builder.

**Reasonable reconstruction:** The process becomes more deliberate and inspectable, with meaningful pushback and role separation. It remains dependent on Mike and the reviewing session remembering to maintain the process; there is no tracked mechanism guaranteeing that every known issue, plan or acceptance condition receives closure.

## Requirements and Planning

**Documented fact:** Requirements precede code and contain goals, non-goals, users, datasets, epics, user stories, acceptance criteria, storage/hosting estimates and a phased roadmap. That is stronger up-front structure than Colony Scout's post-feature README.

It nonetheless failed in two different ways:

1. **Synchronization:** The canonical document grew from 220 to 246 lines while the builder retained the earlier copy. The missing REST/API/CI/container requirements were an input-delivery failure, not evidence that the builder ignored its instructions.
2. **Problem definition:** The original users were an experimenter and portfolio audience. Analyst-shaped stories were written around selected datasets without a sufficiently specific institutional workflow.

The build log assigns the reframe to Mike's domain knowledge: start with a person, a declaration, a research-security office and a concrete decision process. September 6 implements that change in both requirements and code.

The specific use case creates testable constraints: declaration scope, separate observation and judgment records, reasons for every action, controlled closure, evidence export and synthetic-only demo declarations. A subsequent real walkthrough reveals that two legally distinct questions should not share one observation type.

**Reasonable reconstruction:** Requirements became more effective when they were allowed to contradict the chosen stack and output shape. The prior scoring engine was no longer automatically the right user-facing answer.

However, requirements remain layered rather than fully reconciled. The document retains a draft/working-title header, historical API-versus-snapshot assumptions and older technology guesses alongside addenda. Historical preservation is useful; deciding which section is currently authoritative requires care.

The use-case plan explicitly calls a real GLEIF chain check **binding before relevant commits merge**. The shipped fixture notice and corrected spec say that check is still pending. This is an observable gap between the strength of the gate's language and its enforcement.

## Testing, Validation, and Trust

### Present verification

**Documented fact, this audit:**

- Structural validation passed.
- **274 tests passed in 74.75 seconds** with the real-model module excluded.
- **3 real-model tests passed in 20.53 seconds**, with Hugging Face/Transformers offline mode enabled.
- Total: **277 passed**, across two invocations; not one uninterrupted all-suite run.

The initial attempt hit permissions on an existing pytest temporary directory. A fresh temporary base resolved that environment issue. No dependencies were installed or repository code changed. Docker/cloud/browser checks were not rerun.

### Evolution

Function counts below were derived from historical Python ASTs; they are not historical pytest execution totals.

| Milestone | Test functions | Execution evidence |
|---|---:|---|
| Initial scaffold `42a4436` | 0 | No suite |
| V1 `f40f313` | 27 | Commit and build log report 34 passing tests |
| API/thin-client `63630dd` | 49 | Build log reports independent 56-test verification |
| GLEIF `3c07677` | 93 | Historical source count |
| Section 117 docs `3191e6d` | 112 | Historical source count |
| Bibliometric correction `33af483` | 140 | Historical source count |
| Separate real-model CI `822789e` | 157 | Historical source count |
| Review baseline `40ca51b` | 160 | Report references 167 locally passing; its own sandbox reports 157/1/7 |
| Security remediation `26586fc` | 196 | Historical source count |
| Initial case slice `4e2483d` | 234 | Historical source count |
| ConcernTie/current HEAD | 250 | This audit: 277 executed cases pass |

### What constitutes proof

The suite includes pure-function tests, DuckDB integration, FastAPI TestClient routes, export parsing, repeat-run behavior, case lifecycle/closure, synthetic/redaction rules, and real-model checks. HTTP fetch injection and fake embedding vectors make most tests repeatable without live services.

Real-data evidence is separate: institution-name pairs, author-identity ties, real concern-list subsets, Section 117 workbook structure, GLEIF data limitations and targeted live OpenAlex findings are documented. These are valuable observations, not a statistically representative accuracy benchmark.

CI has three jobs: base validation/tests, real-model regression, and Docker Compose integration. The Docker job verifies the UI container can reach the API by service name, runs a screening request with expected counts, and checks the manifest's Git SHA. It is substantially stronger than checking that containers start.

### Where tests were insufficient

The empirical review found guarantees lost beyond tested units. New `test_output_contract.py` and `test_idempotency.py` move checks to parsed exports/API responses and repeated enrichment.

That lesson did not generalize automatically: the synthetic-data marker later disappeared at the export boundary despite the existing output-contract file. Its assertions covered other promises, not that one.

Further limits:

- No browser automation exercises nginx/Certbot, cold-cache static assets or the current full visitor workflow.
- No automated fresh-Lightsail rebuild demonstrates current bootstrap correctness.
- Topic calibration is explicitly provisional: two positive/two negative design examples plus limited real null-result validation.
- Reconciliation calibration is documented but small.
- Required real ownership-chain verification remains pending.
- Passing schema checks proves allowed field shapes, not truth or legal adequacy of every field value.

## Significant Failures and Corrections

### 1. Correct implementation, stale instructions

**Documented fact:** `e86fc56` and `f40f313` explicitly record V1 being built against the stale 220-line spec. Missing Section 9a requirements required API/container/CI follow-up work.

**Trigger → correction:** independent repository/canonical comparison → separate spec-sync commit → specific rebrief → planned API refactor.

The build log calls this a human-side handoff/process failure. Git supports the stale-input mechanism; it cannot independently assign every action among Mike and the two sessions.

### 2. Reproducibility failed at two boundaries

**Documented fact:** Rescoring could produce exports inconsistent with the run's original rubric. `936ed43` introduces the RunManifest/ExportManifest distinction and pure rescoring.

Separately, a local screenshot reportedly exposed null Git provenance in Docker because .git was excluded. `c5a22b1` adds build-time commit stamping and a Compose wrapper; CI checks the generated manifest.

These are durable corrections, not just explanations of a limitation.

### 3. A real-data precision error multiplied 27 times

**Documented fact as recorded live result:** A Chinese Academy of Sciences institution name matched Chinese Academy of Ordnance Science at **0.8387**, generating **27** bibliometric false positives. `33af483` raises that stage's threshold from 0.80 to 0.90 and adds regression protection.

**Reasonable reconstruction:** The important learning is differentiated error cost: checking many co-author institutions multiplies opportunities for a false match. One uniform threshold was not justified merely because code was shared.

### 4. The scorer worked, but the application could not reach it

**Documented fact:** The September 2 review probes show acronym pairs scoring 0.90 directly but producing zero hits through `screen_entity`. Prefix blocking discarded them before scoring.

**Correction:** `8ffa248` adds acronym blocking keys and end-to-end regression coverage. Existing Seven Sons tests had passed because the real dataset supplied both names and aliases; that was dataset assistance, not proof the general path worked.

### 5. Repeat enrichment silently changed meaning

**Documented fact:** Repeated embeddings created duplicate winners/runner-ups, reduced ranking margin to zero and replaced previously non-empty flags with none. Bibliometric hits also accumulated on repeated calls.

**Correction:** `a35b578` adds producer-aware replacement and related lifecycle fixes; `240a850` adds cross-enrichment idempotency checks, including preservation of other producers' rows.

The result was a class-level test, though equal-input reruns do not prove all changed-input or crash-recovery behavior.

### 6. Ownership evidence described a path that did not exist

**Documented fact:** The evaluation's branching fixture produced one flattened tuple combining different branches and an arbitrarily selected ultimate parent. A cycle produced a repeated chain.

**Correction:** `466bcd6` introduces separate paths/cycle handling and multiple-parent output, with storage migration and tests. This directly addresses the project's evidence-traceability promise.

### 7. A public deployment crossed the wrong trust boundary

**Documented fact as contemporaneous review:** The API's local-user assumptions were already warned about in source, but the public Streamlit UI forwarded unrestricted file paths and allowed costly live enrichments. The review recorded **405 run directories**, not 405 users; automatic runs and development activity prevent that interpretation.

**Correction:** `26586fc` adds server-side path validation, an action secret, rate limiting and indexing controls. A self-healing precomputed demo avoids fresh work for every visitor.

**Important continuation:** September 7 reveals the bootstrap did not actually supply the secret to systemd/Compose. With an empty secret, the intended gate failed open. Controls written in application code were insufficient without deployment wiring.

### 8. Synthetic data became an apparently real exported allegation

**Documented fact:** The initial case export omitted any synthetic marker while naming a real concern-listed ultimate parent connected by fabricated ownership edges.

**Correction:** `821ba2e` adds a JSON provenance block and an XLSX first-sheet notice, with assertions in export/demo tests. `cb0b123` separately corrects the spec's claim that the ownership chain was real.

This is the clearest example of a previously identified failure pattern recurring after a supposed general remedy. The marker now travels with the artifact; the required real-chain check remains undone.

### 9. The first worksheet exposed a wrong observation type

**Documented fact:** The first deployed case export classified an ownership concern as outside declaration scope, allowing it to be dismissed with the category meant for irrelevant disclosure gaps.

**Correction:** Mike's analyst decision, recorded in the plan, requires two distinct types. `9a34b68` implements Finding versus ConcernTie, separate reason vocabularies, explicit joins and a closure rule spanning both.

The original slice deliberately tested two discovery paths together. This was an acknowledged design risk surfaced early, although the observation had already reached a deployed walkthrough.

### 10. The maintainer's warm browser concealed a broken public site

**Documented fact as September 7 commit account:** A friend opening the README link encountered failures loading frontend chunks. A rate limit with burst 20 rejected a roughly 150-chunk cold load; logs recorded 128 rejected requests matching browser errors.

**Correction:** `583a510` exempts static assets and increases burst capacity. The same commit records a September 6 outage after copying an HTTP-only nginx template over Certbot-managed TLS configuration, plus recovery instructions and the missing-secret fix.

These fixes had been made manually on the live instance before being committed. The commit explicitly says a fresh infrastructure rebuild was not performed to verify all corrections.

## Git, Documentation, and Release Discipline

**Documented fact:** The history contains 92 commits, with 77 Claude Sonnet 5 co-author trailers. Human author names vary between Mike Jennings and jenningsmt using the same email. Missing trailers are not evidence that the remaining commits were unaided.

Commit messages are unusually explanatory: epics, acceptance criteria, observed bugs, exact consequences, test evidence and deviations from plans. Plans and specs often land separately before implementation; documentation sweeps follow feature work.

This is not uniformly atomic history. V1 is a large bundled drop. The ConcernTie refactor combines six planned commits because independently green boundaries were judged impractical: **22 files, 1,424 insertions and 372 deletions**. The deviation is explicit, which is better evidence than claiming every plan was followed literally.

No tagged releases, installer release series, retained feature branches, merge/PR review trail or automatic deployment pipeline is evident. CI runs on push/PR; deployment uses Terraform and operator-run SSH/Git/Compose/systemd steps. “CI/CD” in the documents should not be read as fully automated continuous deployment.

Reproducibility has improved through recorded parameters, raw data, per-artifact manifests, model revision pinning, a Terraform provider lock and build-time SHA injection. Its limits include:

- Mostly unpinned Python dependencies; Streamlit alone is pinned to 1.63.0 after reading the running image.
- Rebuilds from mutable package sources and branch state.
- No universal dataset/file checksums in the generic DatasetSnapshot.
- Git SHA alone does not identify uncommitted source changes.
- Direct manifest writes and incomplete transaction boundaries.
- Live-server drift and unverified fresh bootstrap.

**Documentation as memory:** Requirements, plans, methodology, data-source notes, a reproduced evaluation, a deployment runbook and the build log serve distinct purposes. User guidance is present, but development-control and rationale documents dominate.

Plan preservation is intentional: historical “not yet built” text remains while the index records current status. Yet one GLEIF plan was lost, the first plan reconstructed, logging fell behind, and a known dead NSF endpoint was recorded without being fixed until unrelated work the next day. The repository itself recognizes that **documenting a defect is not tracking its closure**.

## Human-AI Division of Labor

**Documented fact as repository account:**

| Role | Recorded contribution |
|---|---|
| Mike | Opportunity/scope choices; correction of “offshore” meaning; OpenAlex suggestion; practical storage/hosting limits; local execution/screenshots; CDKTF objection; model selection; analyst/use-case reframe; decision to separate concern ties |
| Cowork session | Requirements, research, plan review, pushed-code inspection, empirical evaluation and build-log writing |
| Claude Code | Implementation, tests, application execution, plan proposals, Git commits/pushes and implementation documentation |
| External visitor | A friend’s fresh-browser visit reveals cold-cache deployment breakage |

The build log describes Sonnet 5/high effort for implementation and a deliberate Opus 5/high-effort review. Those are recorded model-use claims, not independently authenticated telemetry. The log itself correctly says n=1 with no control cannot establish that the model switch caused better findings.

The record attributes errors to both sides: AI misread “offshore,” stale tool research survived early review, Mike misremembered HB 127 as HB 27, and the specification/hand-off process failed. The broader dataset-first framing was collaboratively produced; a blame allocation more precise than the artifacts support would be invented.

**Reasonable reconstruction:** Mike acts increasingly as product owner, domain reviewer, task/router and acceptance authority rather than merely requesting features. AI takes substantial responsibility for research, planning, implementation and review, but does not independently escape the specification's assumptions.

No project artifact establishes OpenClaw/Hugh/Dave execution or autonomous backlog selection. Role separation survives in a different, human-directed arrangement. Direct influence from that experiment is an open question.

## Practices Retained from EDMFI

| Practice | Assessment |
|---|---|
| Trust and uncertainty as architectural concerns | **Documented continuity:** EDMFI guardrails forbid misleading certainty; Monops uses candidate-only match vocabulary and separates observations from analyst decisions |
| Deterministic, inspectable analysis | **Documented continuity, explicit sibling inheritance:** repeatable scoring, manifests and traceable source evidence |
| Separation of responsibilities | **Reasonable reconstruction:** application layering plus builder/reviewer separation resembles earlier engineering aims, without proving direct OpenClaw transfer |
| Regression protection | **Documented continuity:** known-defect tests and explicit validation gates |
| Architectural reasoning preserved | **Documented continuity:** code maps, rationale and requirements precede risky changes |
| Human escalation on domain choices | **Documented process account:** major questions return to Mike, especially meaning, product scope and legal interpretation |

EDMFI-specific journal authority, game-state ownership and event replay were not relevant requirements for an open-data portfolio service. Their absence is not devolution.

## Practices Strengthened or Newly Introduced

**Documented fact:**

- Pre-implementation plans explicitly test predecessor claims rather than copying their reputation.
- Source records carry dataset identity, retrieval date and record ID; ingestion errors are recorded and counted.
- Provenance is differentiated by artifact and enrichment, including exports under changed rubrics.
- A written empirical review preserves reproduced failures and rejected suspicions.
- Output contracts verify what leaves the system, not only internal objects.
- Idempotency becomes an explicit cross-stage property.
- Docker CI checks internal networking, actual outputs and commit identity.
- A dedicated heavy test job makes the real-model guard operational.
- Analyst judgments and system observations receive separate representations.
- Declaration scope, structured reasons, synthetic labels and redaction become tested output contracts.
- Operating experience is recorded in infrastructure comments and runbooks.

**Reasonable reconstruction:** These practices show materially stronger engineering than Colony Scout's smaller release-stage suite and informal requirements. They also show a more elaborate operational problem than a desktop tool.

“Newly introduced” means new in this project's observed progression or explicitly raised above its sampled predecessors; it does not establish the first occurrence anywhere in Mike's eight-month history.

## Practices Simplified, Abandoned, or Possibly Regressed

**Intentional simplifications, documented:**

- No full Vue frontend, GovCloud or formal accreditation program for this hobby scope.
- No NetworkX bibliometric graph: the real API already provides the required flat authorship data.
- No dedicated Seven Sons implementation after proving existing list coverage.
- Optional heavyweight ML dependencies, with a separate CI job.
- No persisted HNSW index; simpler direct similarity computation avoids an experimental persistence path.
- No packaged Python distribution/pyproject infrastructure where direct module execution suffices.
- Shared action secret and caller-supplied analyst identity for a synthetic single-tenant demo, rather than production identity management.
- Screening-only demo while live OpenAlex rate limits block enrichment.

**Possible regressions or missing discipline:**

- EDMFI's crash-safe persistence emphasis is not visibly applied to every manifest or multi-statement replacement operation.
- Explicit “before merge” real-data gates are not consistently enforced.
- There is no reliable issue-closure mechanism for findings parked in plans.
- Formal review does not prevent requirements-copy drift or live configuration drift.
- Public deployment occurs before all validation and hardening assumptions are checked.
- Build-log maintenance is uneven despite its stated working agreement.

No AGENTS.md does not mean there were no controls: requirements, plans, code checks and the two-session agreement carry substantial control here.

## Evidence of Development Maturity

**Reasonable reconstruction:** The strongest maturity is demonstrated by how failures change mechanisms:

- A rescoring ambiguity creates a new artifact-specific manifest.
- A container-only provenance failure becomes a container-level assertion.
- A correct isolated matcher failing in practice moves tests outward.
- Repeat-run corruption produces cross-stage idempotency checks.
- A concern tie dismissed as an irrelevant omission changes the schema and action vocabulary.
- An externally visible deployment failure changes the cold-load validation expectations.

The project also shows real restraint: refusing unnecessary components, leaving uncertain author identity explicit, keeping semantic similarity outside risk scores, and making unknown adversary-country status nullable instead of calling it clear.

Requirements increasingly reflect a user's work rather than technical capability. Architecture makes that change feasible without discarding the existing matching, ownership and evidence infrastructure.

These are concrete improvements, not evidence that all corrections were cheap or all initial decisions were good.

## Evidence of Development Devolution or Overconfidence

**Documented fact / reasonable reconstruction:** Several claims exceed the proof preserved:

1. **“Built and verified” outpaced correct user definition.** Plans and tests provided rigor inside the wrong frame.
2. **The same boundary failure recurred.** Synthetic provenance was lost after an output-contract lesson had already been formalized.
3. **Binding gates became pending follow-ups.** The real-GLEIF check was required before implementation landed but remains incomplete.
4. **Infrastructure-as-code did not equal reproducible operations.** Hand-applied server fixes were missing from the bootstrap.
5. **The reviewer overstated streaming.** The evaluation praises streaming broadly; current methodology explicitly admits `run_screening` materializes OpenSanctions records into a list immediately after its streaming ingester.
6. **Type-level claims need qualification.** Frozen dataclasses, enum constraints and field allowlists are meaningful safeguards, not a proof that arbitrary nested strings/dictionaries contain no evaluative claims. The synthetic guard verifies `synthetic=True`; it cannot independently determine whether supplied names/data are actually fabricated.
7. **Auditability is limited by identity and recovery.** Analyst actors are caller-supplied strings, and not every write sequence is crash-atomic. The code documents the authentication limitation.
8. **Chronology is rhetorically overstated.** “Fortnight” and the CDKTF elapsed-time statement should not survive into the essay as facts.

The zero-result demo also needs careful interpretation. Its selected NSF corpus produced zero direct matches and prompted a legitimate workflow question. Claims that US-based recipients make all concern-list matches categorically impossible are broader than the repository's demonstrated sample; geography alone is not a proof about all list membership.

These are grounds for qualified criticism, not a conclusion that the substantial test and review work was performative.

## Key Trigger → Process-Change Relationships

| Trigger | Diagnosis | Correction | Lasting change / limit |
|---|---|---|---|
| V1 missing architecture requirements | Builder received stale spec | Sync and specific rebrief | Approved plans/handoffs; synchronization still later drifts |
| Export scores differ from run rubric | Run provenance insufficient for each artifact | ExportManifest and pure rescoring | Artifact-specific reproducibility |
| Docker shows null SHA | Runtime cannot access excluded .git | Build-time SHA plus wrapper | Container CI checks exact SHA |
| 27 live bibliometric false positives | Shared threshold ignores volume-related precision cost | Separate 0.90 threshold | Regression case and differentiated rationale |
| Acronym scorer passes, screening fails | Blocking removes candidates | Acronym keys | Pipeline-level matching tests |
| Second enrichment yields zero flags | Duplicate embeddings defeat margin ranking | Replacement semantics | Cross-enrichment idempotency tests |
| Branching ownership becomes false path | Flattened traversal loses topology | Distinct chains/cycle handling | Evidence fidelity and migration |
| Public UI forwards unsafe local assumptions | UI is not the trust boundary | API gate/allowlist and demo reuse | Deployment still must supply configuration |
| Undefined analyst workflow | Dataset-first specification | Subject/declaration/case reframe | Specific use case; scores leave primary worksheet |
| Synthetic marker absent from download | UI warning does not travel | Export provenance block/sheet | New artifact assertions |
| Ownership concern bulk-dismissed | Two questions forced through Finding | ConcernTie split | Separate vocabulary and joint closure |
| Friend's cold browser fails | Rate limit rejects static chunks | Exempt static path; larger burst | Cold-load checks; no fresh bootstrap proof |
| Live hotfixes not in source | Manual operations drift from IaC | September 7 template/runbook reconciliation | Fresh rebuild remains unverified |

## Best Concrete Anecdotes for the Larger Essay

1. **The builder obeyed the wrong copy correctly.** The 220-versus-246-line requirements mismatch explains missing architecture without blaming code generation. The discrete sync commit preserves accountability.
2. **A screenshot disproved provenance.** Mike's running Docker instance showed null SHA despite successful native runs. The correction reached build configuration and CI.
3. **Twenty-seven wrong hits from one plausible match.** A 0.8387 institution-name match became a stage-specific precision lesson rather than a global threshold tweak.
4. **The unit test was right and the product was wrong.** Acronyms scored correctly in isolation while blocking made them unreachable. This is a precise example of test placement mattering more than test count.
5. **The second click erased the first answer.** Duplicate embeddings made the runner-up equal the winner, eliminating all margin-qualified flags. A repeat-run probe found a consequence a simple duplicate-row observation would miss.
6. **The review corrected the machinery but missed the job.** The independent review noticed zero findings and treated them as presentation debt. Mike later reframed the actual user workflow. Preserve this without the unsupported “two weeks” duration.
7. **A fictional chain escaped its demo label.** A publicly downloadable artifact connected a synthetic employer to a real listed entity without provenance. A prior boundary-testing lesson had not covered this new guarantee.
8. **The analyst dismissed the important row for a technically correct reason.** An ownership concern was outside declaration scope because the subject had declared the employer. The right correction was two observation types, not stronger wording in one table.
9. **A friend supplied the missing test environment: a fresh browser.** Warm caches concealed rate-limit breakage. Concrete browser/server counts link the report to the cause.
10. **A feature became a test instead of a class.** Real-data inspection showed Seven Sons coverage already existed. The project documented the dependency and tested it rather than duplicating a list.

## Comparison of Initial Intent to Final Product

| Initial intent | Current implementation | Assessment |
|---|---|---|
| Public-data portfolio screening engine | Deployed Monops demonstration | Delivered at portfolio scope |
| Corpus-in, ranked-list-out | Subject/declaration-in, worksheet/file-out | Major product-direction correction |
| Adjustable scores as central output | Scores retained in batch API, omitted from case observations | Domain-driven removal from primary user workflow |
| Streamlit calling engine directly | Thin HTTP client over FastAPI/shared pipeline | More reusable architecture |
| Snapshot-first operation | Live targeted OpenAlex enrichment, persisted for reuse | Explicit practical departure from original NFR |
| Broad OpenAlex bulk acquisition | Targeted author/institution lookups | Scope/cost correction recorded before expansion |
| CDKTF Python infrastructure | Plain Terraform HCL | Research correction; rejected implementation not preserved as committed source |
| One generic Finding for both paths | Findings plus ConcernTies | Export-driven schema correction |
| Synthetic person with real reference chain | Synthetic person and fabricated ownership chain; real designation | Partial delivery with explicit remaining gate |
| Future population re-screening | NSF batch pipeline remains; case-population orchestration/renaming unresolved | Retained code is not proof the new requirement is implemented |
| V3 and adjacent AI capabilities | Bibliometrics/VSS built; LLM explanation Epic J deferred | Deliberate scope boundary |
| Further institutional workflows | Country-list derivation, export-control and COI/NSPM-33 reuse outstanding | Project remains incomplete |

The case reframe reused real infrastructure, but “thin case layer” should not be mistaken for negligible scope. Current case storage alone is 777 lines, and the later observation split changes 22 files. The build log's estimate that only three remediation workstreams were sunk cost is its own reconstruction, not measured effort accounting.

## Important Open Questions

1. What dates or external work explain the build log's “fortnight” language, given an August 31 scaffold and September 3 reframe?
2. Was the required real-GLEIF chain check explicitly waived, by whom, and on what terms? Is the evidence now available outside the repository?
3. Which plans/reviews exist in Cowork or Claude Code transcripts but were never preserved, particularly GLEIF?
4. Did anyone resembling the target institutional analyst validate the workflow, or has validation so far been Mike plus AI collaborators and general visitors?
5. What practical experience from Hugh/Dave/OpenClaw motivated the two-session arrangement, if any?
6. Which acceptance decisions were Mike's direct inspection versus trust in the reviewing session's account?
7. Has a completely fresh Lightsail rebuild since September 7 verified the secret, TLS procedure, cold-cache load and deployed commit?
8. What mechanism will track unresolved binding checks, the known streaming gap and the case-population transition, so they do not remain prose?
9. What accuracy standard and representative dataset would distinguish a compelling synthetic demonstration from reliable matching/reconciliation?
10. What is the intended endpoint: maintained portfolio demonstration, richer synthetic workflow laboratory, or eventual production-oriented redesign? The evidence supports the first two much more strongly than the third.

## Detailed Evidence Table

Full hashes identify events. Package paths abbreviated as common/, screening/, ownership/, bibliometric/, reconciliation/, case/ or api/ are under entity_screening/; other paths are repository-relative. “Recorded” indicates a repository account rather than an independently repeated live observation.

| Finding | Evidence class | Date | Commit/tag | File(s) | Evidence / explanation |
|---|---|---|---|---|---|
| Requirements precede code | Documented fact | 2026-08-31 | 42a44362cd6c69aca95e21ab13b80dbb1f2a7246 | docs/requirements.md; package skeleton | 220-line spec; 14-file scaffold; no substantive implementation |
| Stale spec caused missing architecture | Documented fact | 2026-09-01 00:24:45Z | e86fc56237b8bf816ae4b436921c6bd867dc600b | docs/requirements.md | Explicit 26-line Section 9a synchronization and causal commit account |
| V1 with early tests | Documented fact | 2026-09-01 00:28:15Z | f40f31330f29e323b069a4ec45442028c153fb33 | engine; tests; app.py | 34 reported tests; 2,018 insertions; implemented against stale input |
| Self-contained evidence | Documented fact | 2026-08-31 | f3cc81e25fb00929407a57f8645519fae12697d2 | screening/screen.py; tests/test_screening.py | Evidence usable without another data join |
| CI introduced immediately after V1 | Documented fact | 2026-08-31 | 61862c04e530018dd2b28704786b26643a97e31c | .github/workflows/ci.yml | Structural validation and pytest on push/PR |
| Run/export reproducibility distinction | Documented fact | 2026-08-31 | 936ed434593f2383c21580b511959ecd47cb196a | entity_screening/pipeline.py; common/manifest.py | Export identifies actual rubric; rescoring separated from baseline persistence |
| Thin-client refactor and run-scoped key | Documented fact | 2026-08-31 | 63630ddbf0c8613d06259672981867e6341a4277 | app.py; common/storage.py | Multi-run deterministic entity IDs require compound key |
| Superseded single-container architecture | Documented fact | 2026-08-31 | 62cd8253661bc4f241d86296483e08cd17a3e9e9 | deleted Dockerfile; Dockerfile.api; Dockerfile.streamlit; compose | Two processes require two connected services |
| Compose CI checks real boundary | Documented fact | 2026-08-31 | edc8b9fb30f04154f1dc24a3583157b3f1138911 | .github/workflows/ci.yml | UI-container-to-API network check plus pipeline output |
| Null container SHA corrected | Documented fact | 2026-08-31 | c5a22b15397be86d113f4fe000d18e62fd319ac1 | common/manifest.py; Dockerfile.api; scripts/compose-up.ps1; CI | Build-time identity and exact manifest assertion |
| Approved plans brought into history | Documented fact | 2026-09-01 | 401eb72d047300b6e9e5f06bf2aacf920ecada93 | docs/plans/README.md; first two plans | Prior plans external; V1 reconstructed; GLEIF plan later acknowledged missing |
| Explicit predecessor learning | Documented fact as plan account, with source checks | 2026-09-01 archive | 401eb72d047300b6e9e5f06bf2aacf920ecada93 | docs/plans/2026-08-31-v1-minimum-viable-screening-loop.md | Rubric/provenance/streaming inheritance plus predecessor gaps |
| Ownership phase | Documented fact | 2026-09-01 | 3c076772953a9caa6372eaac418ce9d87edc38b6 | ownership/*; storage; manifests | GLEIF graph and parent-jurisdiction flags |
| Section 117 real-data validation | Recorded fact | 2026-09-01 | 53806588d93969fa0aeecffff9d1191f633d3222 | docs/data_sources.md; Section 117 plan | Workbook/name/data-quality observations |
| Retained ambiguous author identity | Documented fact | 2026-09-01 | ffa91374aa5142f21e2d45e759469d00a1feeefd | bibliometric/author_resolve.py; tests/test_author_resolve.py | Shared ORCID and remaining tie represented, not forced to one candidate |
| Feature replaced by existing-coverage test | Documented fact | 2026-09-01 | b42cce867a00adb66afb114f2ea09982ae77253c | tests/test_screening_seven_sons.py | Seven universities tested through existing OpenSanctions |
| 27 false positives change threshold | Recorded live event; code/test correction verified | 2026-09-01 | 33af4837fde1de61f61fff4437dffbd5adedc870 | bibliometric/cross_check.py; tests/test_bibliometric_cross_check.py | 0.8387 false match; 0.90 stage threshold |
| Real-model gate gets its own job | Documented fact | 2026-09-01 | 822789ed3a3f70822aaf7fd150fc36d21d71f422 | CI; tests/test_topic_similarity_real_model.py | Optional-dependency skip no longer sole CI path |
| Terraform delivery and CDKTF reversal account | Code fact plus recorded reversal | 2026-09-01 | 3be4c7ef45df2c81cb1f7ae2f2656a669d357284 | infra/*; deployment plan | HCL committed; discarded CDKTF code not recovered from Git |
| Bootstrap shell assumption failed | Recorded live event; correction verified | 2026-09-01 | 98b26f877657cd5154070ce7e9aee01117872211 | infra/user_data.sh | Explicit POSIX-compatible re-exec to bash |
| HTTPS downgrade correction | Recorded live event; correction verified | 2026-09-01 | 861834f12ca9a0bf6f1cd24798bb1d51f5fba892 | infra/nginx/monops.conf | Proxy handles trailing-slash redirect |
| NSF endpoint/rate-limit corrections | Documented fact | 2026-09-02 | 40ca51bc184fab27bd57a396c17b2a0d60e4be16 | ingestion/nsf.py; bibliometric/openalex_client.py; demo fixture/docs | Known endpoint defect repaired during demo work |
| Reproduced whole-codebase review | Documented review artifact | 2026-09-02 | 7c94f235241741fc05bcc9189d09d665a6091863 | docs/2026-09-02-codebase-evaluation.md; remediation plan | Nine findings with probe outputs; historical test outcomes qualified |
| Producer-aware rerun correction | Documented fact | 2026-09-02 | a35b578b6362f32bf57308e2a2fb659609f329ee | common/storage.py; pipeline.py | Independent producers no longer share append-only assumption |
| Acronym path fixed | Documented fact | 2026-09-02 | 8ffa2485fc0a0fa28092a4c9c45041155204ad09 | screening/lists.py; tests/test_screening.py | Blocking admits scorer's acronym candidates |
| Caveats/attribution carried with data | Documented fact | 2026-09-02 | c1ce5b4479ef862e2bcd686334ffb4bff03f96ab | common/attribution.py; evidence producers | Output consumers receive source/caveat payloads |
| Matched field/producer reach output | Documented fact | 2026-09-02 | cc1a1b5e2859181fcc9a407205022aea0cb989c0 | api/dto.py; output/export.py | Distinguishes direct from second-order evidence |
| Branch/cycle evidence corrected | Documented fact | 2026-09-02 | 466bcd6df99906945ff084579952460ee2829c8d | ownership/graph.py; flagging/storage/tests | Separate real paths; compatible storage |
| Boundary and rerun tests | Documented fact | 2026-09-02 | 240a85016056e02bd5c62d58b83a8c0f99573f74 | tests/test_output_contract.py; tests/test_idempotency.py | Parsed artifacts and repeat operations |
| Fetch-once and bounded enrichment | Documented fact | 2026-09-02 | 66e0689c096b773e9a0fbffcc9e579ab31311635 | pipeline; OpenAlex client; storage | Persist works, cap retrieval, separate timeout |
| Demo security work | Documented fact | 2026-09-02 | 26586fc89dbaebf77db367a6f70fd37635200cbc | API; compose.prod; nginx; security tests | Action gate, server allowlist and request controls |
| Two-session collaboration and product-error account | Documented process account | 2026-09-03 | 4980dab963e5b02e1013a520e2f95e70eb12e78d | docs/how-this-was-built.md | Explicit labor split, human/AI corrections and retrospective gaps |
| User/workflow reframe | Documented fact | 2026-09-06 | 63130047e180cb57c2dfd1179c612dde3c304058; 4e5242f45b7df002cda60ba0bab40b3de359769f | use-case doc; requirements §9c | Specific case-based requirements replace primary corpus workflow |
| Binding gate later deferred | Documented conflict | 2026-09-06 | 1583c39d4f982541d31be88a521f7130ef6f4b3b; b7857ff71c5891f6a155b3997bddc4691d942238 | implementation plan §2H; fixture NOTICE | Real chain required before merge; fabricated chain ships pending check |
| Fact/judgment guard in code | Documented fact | 2026-09-06 | ec237c79b4f0125338a613d46613780385e41873 | common/schema.py; cli.py; tests/test_finding_contract.py | Allowed fields and synthetic=False rejection; semantic limits remain |
| Reconciliation calibration | Documented fact as measured-pair record | 2026-09-06 | e3a61f4a3854e4239949d40c005d97a2d3040d54 | reconciliation/match.py; docs/data_sources.md | 0.90 threshold above documented 0.876 distinct pair |
| Synthetic export provenance restored | Documented fact | 2026-09-06 | 821ba2e964883fd69e0f1b8b49e5b41cc75135f1 | case/export.py; output/demo tests | JSON marker and XLSX first sheet added after review |
| Real-chain claim corrected in spec | Documented fact | 2026-09-06 | cb0b1238cf764b52efc2951d4c2338bd8b3cedff | use-case doc §10 | Explicitly distinguishes real designation from fabricated chain |
| ConcernTie correction | Documented fact | 2026-09-06 | 9a34b6889dbff7f9cb4a0c0dde3e3a1d77505292 | schema; reconciliation; case services/storage; API/tests | First export triggers two types, vocabularies and joint closure |
| Cold-cache, missing-secret and TLS drift | Recorded live events; source correction verified | 2026-09-07 | 583a5105c3cb5f7bdf10d3a5115e16452dbbae73 | infra/user_data.sh; nginx; deployment runbook | Three hand fixes incorporated; fresh rebuild explicitly not verified |
| Dependency/theme scope restrained | Documented fact | 2026-09-07 | e62da8cc13e6f7ba70001fb16e84c6967e1cef0f | requirements.txt; .streamlit/config.toml; Dockerfile.streamlit | Pin running Streamlit version; most dependency pinning remains debt |
| Current product polish | Documented fact | 2026-09-07 | 170992ffd3fb8794a09cee9f261a0e022e8bf157 | app.py | Visitor explainer and case subject line |
| Present verification | Documented fact | 2026-09-09 | HEAD 170992ffd3fb8794a09cee9f261a0e022e8bf157 | tests/*; cli validate | 274 base + 3 offline real-model tests pass |
| “Most mature/complex” | My later recollection/interpretation; qualified reconstruction | Retrospective prompt | Not established by a single commit | Prompt; comparative evidence | Stronger process dimensions demonstrated; whole-journey superlative unproved |

## Overall Interpretation

**Reasonable reconstruction:** Monops represents a substantial advance in how Mike directs and checks AI-assisted software work. Its strongest evidence is not the volume of requirements or number of tests, but the explicit inspection of predecessor practices, separation of building from reviewing, empirical review standard, artifact-level provenance, and regression checks tied to real failures.

It also demonstrates intentional simplification. Unnecessary components and infrastructure are declined, ML remains optional, the public demo is synthetic, and specialized responsibilities remain separate. These choices are generally proportionate to a portfolio demonstration.

There is real loss or inconsistency of discipline: documentation synchronization repeatedly fails, a binding real-data gate remains unmet, known defects can disappear into prose, operational fixes drift outside Git, and some structural safeguards are described more absolutely than their implementation warrants. Formal review improves correctness within a frame; it does not select the right frame.

The strongest transferred learning comes through the intermediate ED tools: reusable rubric design, provenance, deterministic analysis and large-data caution. EDMFI's trust-first principles remain recognizable, and review-role separation reappears without evidence of OpenClaw execution. Complete crash-safety, dependable lesson/issue closure and strict gate enforcement do not visibly transfer everywhere.

The human role becomes more consequential, not less. Mike supplies the domain framing, changes the question, challenges research, runs the system and chooses how to allocate AI work. AI performs much more than code generation, including planning, research, tests, review and operational documentation. The record also shows both AI perspectives sharing the specification's blind spot.

Completion must be stated narrowly. The batch milestones and synthetic case slice are built, and the hosted demonstration is supported by concrete deployment and incident records. The broader application remains unfinished. Shipping reveals things EDMFI's earlier engineering record alone could not: a correct local app can fail its first public visitor; an access-control function can be defeated by absent deployment configuration; and an exported artifact can lose a promise the screen visibly makes.

This is stronger engineering with better evidence of its own limitations, alongside a still-unfinished transition from portfolio-oriented capability building to a validated user workflow. That is a defensible historical conclusion. “Most mature,” “production-ready,” and “the AI learned to ask the right question” are not.

