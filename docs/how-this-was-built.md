# How This Was Built

**Purpose:** A running record of *how the direction happened* on this project — where an AI collaborator's first pass needed correcting, where domain knowledge changed a technical decision, how ambiguity got resolved, and how output got validated before it was trusted. It exists because the interesting part of building software this way is the judgment, and judgment doesn't survive in a commit history.

It's kept as raw material for a longer methodology write-up on how an experienced analyst without a formal software-engineering background directs an LLM to ship tested, packaged, documented software — but it stands on its own as the record of what actually happened on this repo, in order, as it happened.

**What gets logged:** not a feature changelog — `git log` already covers what changed. This covers why the direction was what it was. A session that produced no code but changed a decision is worth an entry; a session that produced a lot of code and no judgment calls may not be.

**Editorial policy:** entries are kept unedited, including the ones that aren't flattering — the misread requirement, the spec that drifted out of sync with what the builder was actually given, the review that had the right evidence in hand and filed it under the wrong heading, the fortnight spent building carefully in a direction that turned out to answer the wrong question. Those are the entries that make the rest of it credible. An entry that would be uncomfortable to publish is a signal that it matters, not a reason to soften it. Nothing here has been improved after the fact to read better in hindsight.

**Working agreement (added after Phase 0, revised Phase 5):** planning, requirements, research and review happen in a Claude.ai Cowork session; iterative build work — writing code, running tests, running the app — happens in Claude Code in VS Code, native on Windows. Claude Code stages, commits and pushes to GitHub, by convention confirming before a push rather than pushing unprompted. The Cowork session then reads the pushed history and the code itself directly, via the device bridge, and carries out a top-level review as a redundancy layer. Handoff prompts to Claude Code point at `docs/requirements.md`'s epics, stories and acceptance criteria, or at an approved plan in `docs/plans/`, rather than being freehand-written each time. Entries in this log are written on the Cowork side, from the pushed history rather than from a recap.

**Why the work is split across two AI sessions, beyond tooling:** the obvious reason is capability — Claude Code has persistent processes and native OS access the device bridge genuinely lacks. That's real, and it isn't the main reason. The main reason is that the two sessions hold different vantage points, and the difference is deliberate. Claude Code is deep in the build: it knows the code intimately and, precisely because of that, can lose sight of the larger objective. The Cowork session holds the requirements, the reasoning behind them and the project's purpose, and is frequently adversarial toward what was built — reviewing it rather than defending it. Both perspectives are valuable and neither is sufficient alone. It's a small-scale imitation of something a traditional software team gets structurally for free: separation of roles and responsibilities, and the checks and balances that follow from the person who built a thing not being the only person who assesses it.

**Entry template** (for consistency across sessions, not a rigid form):

```
### [Date] — [Session focus, one line]

- **Prompt / goal:** what was actually asked for
- **First pass:** what Claude proposed or did initially
- **Redirect / correction:** what Mike caught, corrected, or decided differently, and why
- **Resolution:** where it landed
- **Why it matters for the write-up:** the methodology point this illustrates, if any
```

---

## Phase 0 — Discovery & Requirements (August 31, 2026)

Before any code, this phase is itself worth logging: the process of turning a vague, externally-prompted idea into a scoped requirements document is exactly the "direct an AI collaborator through ambiguity" story the methodology piece needs, and it happened entirely in conversation.

### Scoping the actual opportunity

- **Prompt / goal:** a colleague's repeated suggestion to monetize the Elite Dangerous dev work, mentioned alongside an unrelated aside about a security-tooling side project of their own.
- **First pass:** Claude researched Mike's public background and GitHub repos and proposed six opportunities, including taking the security-tooling angle seriously as one option among them.
- **Redirect / correction:** Mike clarified the security-tooling mention was context, not interest — he had no intention of pursuing it.
- **Resolution:** the brainstorm doc's treatment of that option stood as an honest "here's why it's not a great fit anyway" analysis, which turned out to be moot once Mike's actual disinterest was stated directly, but confirmed the analysis wasn't just told what he wanted to hear.
- **Why it matters for the write-up:** a useful example of scope correction — reading intent from what's said isn't a substitute for the person stating it directly, and a good collaborator (human or AI) should still produce an honest independent assessment rather than only validating the frame it's handed.

### Dataset selection as iterative correction, not one-shot generation

- **Prompt / goal:** pick a concrete opportunity (entity resolution / due-diligence screening) and identify real, obtainable open datasets to build it from.
- **First pass:** Claude proposed OpenSanctions as the anchor dataset.
- **Redirect / correction:** Mike asked what else belonged in the stack — surfacing that "entity resolution" needs more than one list. Claude added GLEIF for ownership-chain data and, in the process of verifying it, caught and corrected an outdated assumption about OpenCorporates (once free and open, now largely paywalled) before it became a load-bearing recommendation.
- **Resolution:** GLEIF replaced OpenCorporates as the free ownership-graph source.
- **Why it matters for the write-up:** verification caught a stale assumption *before* it shipped in a spec, not after — a concrete instance of the "when to trust it, when to check it" judgment call the write-up needs to describe, not just assert.

### A misread worth keeping, not editing out

- **Prompt / goal:** Mike raised adding offshore ownership tracking to the dataset stack.
- **First pass:** Claude read "offshore" in the tax-haven-secrecy-jurisdiction sense and built out a detailed BVI/Cayman/ICIJ-leaks section on that basis.
- **Redirect / correction:** Mike corrected the interpretation directly — he meant foreign (person, corporate, or government) ownership generally, not secrecy jurisdictions specifically.
- **Resolution:** the doc section was rewritten around FOCI/NSPM-33-relevant sources (Section 117 disclosure data, DoD's 1260H list, GLEIF cross-jurisdiction flagging, USDA AFIDA, BEA FDIUS) — a reframing that turned out to fit Mike's actual job-search targets *better* than the original misreading did.
- **Why it matters for the write-up:** the clearest single moment in this log so far for the methodology piece — a genuine misunderstanding, caught and corrected in one exchange, that led to a stronger result than the first draft would have. Worth keeping in the write-up precisely because it's not flattering to get wrong; that's what makes it credible as a description of how the collaboration actually works rather than how it ideally would.

### Domain expertise steering a technical addition

- **Prompt / goal:** none given directly — Mike volunteered OpenAlex as an addition, based on his own professional judgment that co-authorship/citation data could surface non-obvious ties to Military-Civil Fusion-linked institutions.
- **First pass:** Claude researched OpenAlex's access model and found a real, decision-relevant complication — its REST API had moved to a usage-based pricing model in February 2026 — while confirming the bulk snapshot remained free.
- **Redirect / correction:** none needed from Mike here; the check surfaced its own correction (bulk snapshot, not live API, is the right access pattern) before it reached the requirements doc.
- **Resolution:** OpenAlex added to the stack via bulk snapshot access, with the pricing change noted rather than glossed over.
- **Why it matters for the write-up:** the idea came from Mike's domain judgment, not from Claude — a reminder that the write-up's "how to direct an AI collaborator" framing should give equal weight to *what the human brings that the AI can't originate on its own*, not just how the human corrects the AI's output.

### An engineering decision reversed by verification, not assumption

- **Prompt / goal:** develop storage estimates for the requirements doc across V1/V2/V3.
- **First pass:** the original Epic E acceptance criteria (written earlier in the same session) called for ingesting OpenAlex's bulk snapshot.
- **Redirect / correction:** checking the actual documented snapshot size (660+ GB) revealed that plan was impractical for a hobby project — a fact discovered while *estimating storage*, not while designing the feature, and one that fed back to change an earlier decision rather than being treated as someone else's problem.
- **Resolution:** Epic E's approach changed from "bulk snapshot" to "targeted API lookups scoped to specific PIs," cutting the V3 storage footprint from hundreds of GB to single digits.
- **Why it matters for the write-up:** a good example of a spec correcting itself under new information mid-process — the requirements doc isn't a one-pass artifact, and later sections (storage estimates) legitimately overrode an earlier section's decision (Epic E) once a concrete number made the original plan's cost visible.

### Practical constraints treated as first-class requirements, not afterthoughts

- **Prompt / goal:** a sequence of concrete planning questions — hosting platform (Streamlit Community Cloud vs. AWS Lightsail), hosting term (6 months with a renewal option), and local disk budget (305 GB free on the dev drive).
- **First pass / resolution:** each was treated as a real requirements-doc input rather than a side conversation — the hosting decision changed a whole section of the doc (with real, verified AWS Lightsail pricing rather than a rounded guess), the term decision produced an explicit decision-point-not-automatic-renewal plan with a concrete reminder date, and the disk-space question was tied back explicitly to the earlier OpenAlex sizing decision as a guardrail confirmation.
- **Why it matters for the write-up:** operational/logistics questions (hosting cost, timelines, disk space) got the same documentation discipline as technical ones, rather than being treated as outside the spec's scope — arguably the most "product-analyst" habit demonstrated in this whole phase, and the one most directly transferable to the kind of role this project is meant to demonstrate readiness for.

---

## Phase 0b — Course Correction Mid-V1, From External Research (August 31, 2026)

### Letting real-world research change an in-progress spec, and knowing where to stop

- **Prompt / goal:** Mike gathered the full set of a target employer's open technical job postings — not just the analyst role he had applied to — and asked whether this project should change in light of what they revealed about that company's real platform architecture, while explicitly noting V1 wasn't far enough along to make changes costly.
- **First pass:** research surfaced concrete, confirmed technical facts (FastAPI/Vue.js/Terraform-CDKTF/AWS stack on their data-visualization platform; a RAG pipeline with Postgres/vector-database usage; RMF/ATO and GovCloud as real but narrow compliance/infra concerns) rather than the earlier session's inference-only picture.
- **Redirect / correction:** the interesting judgment call wasn't "adopt everything they use" — it was separating what's genuinely good engineering (a FastAPI layer under the Streamlit UI, Terraform-provisioned hosting, CI/CD made explicit) from what's real but irrelevant to this project's actual context (AWS GovCloud and RMF/ATO exist to handle classified/export-controlled workloads a hobby project doesn't have) and from what's outright bad practice regardless of the goal (baking "built to match your job posting" into a public README, which reads as reverse-engineering an interview rather than genuine engineering interest).
- **Resolution:** requirements doc updated with a new epic (evidence-grounded LLM explanations, a real RAG pattern addressing the actual gap between the project's pure structured-matching design and that platform's stated RAG/AI-agent differentiator), a schema-discipline note that costs nothing now but would cost rework later, and an explicit "deliberately not adopted" list so the omissions read as decisions rather than oversights.
- **Why it matters for the write-up:** this is arguably the clearest example yet of the human supplying judgment an AI collaborator shouldn't be trusted to supply unprompted — matching a target company's stack is easy to overdo, and the discipline of asking "does this clear the bar on its own engineering merits, or am I just imitating it" is exactly the kind of filter a good collaborator should apply out loud rather than silently defer to the human on. It's also a good example of *when* to revise a spec: the fix was cheap specifically because it happened before V1 shipped, not after.

## Phase 1 — V1 Build, Verification, and a Process Gap Caught Late (September 1, 2026)

### Verifying a completion report instead of accepting it

- **Prompt / goal:** Claude Code reported V1 "built and verified end-to-end" (Epics A, B, D, F, G, H, I; three named bug fixes; 34 passing tests) and asked whether anything needed adjustment.
- **First pass:** rather than relaying that report back with a thumbs-up, read the actual repository directly — schema, storage, matcher, normalize, cli, manifest — and independently ran the test suite (installed dependencies fresh in an isolated shell specifically to do this, since the claim "34 tests pass" is not something a report should be trusted to self-certify).
- **Redirect / correction:** the three claimed bug fixes (acronym-matching order, UTF-8 encoding, DuckDB wiring) all held up under direct inspection, and the 34 tests were real, substantive assertions, not padding. But the review also surfaced two problems Claude Code had no way to know about.
- **Resolution:** confirmed genuine engineering quality where it existed, rather than either rubber-stamping the report or assuming a self-reported "verified end-to-end" claim needed no independent check.
- **Why it matters for the write-up:** a clean self-report from an AI collaborator is exactly the moment verification is most tempting to skip, precisely because it sounds finished. This is the concrete example of *not* skipping it.

### The stale requirements doc — a self-caught process gap, not a Claude Code failure

- **Prompt / goal:** none directly — surfaced during the verification pass above.
- **First pass:** the repo's `docs/requirements.md` had been copied in once at initial scaffold time and never re-synced after Section 9a (the FastAPI/CI-CD/Docker/Terraform decisions made mid-V1, following the external research in Phase 0b) was added to the canonical copy. Claude Code built faithfully against the document it was actually given — 220 lines instead of 246 — which is why `app.py` calls `entity_screening` directly instead of through a REST API, and why there's no CI/CD, Docker, or infra-as-code in V1.
- **Redirect / correction:** none from Mike needed here either — this was caught by diffing the two copies directly rather than assuming they matched.
- **Resolution:** synced the canonical doc into the repo, committed it as its own discrete commit (separate from the V1 build commit) so the correction is visible in the history as its own event, then re-briefed Claude Code specifically on Section 9a with a sequencing plan (plan-first for the FastAPI refactor, direct-implement for CI/CD and Docker, defer Terraform).
- **Why it matters for the write-up:** the most honest example so far of a mistake that's the human collaborator's, not the AI's — a spec that drifted out of sync with what was handed to the builder. Worth keeping in the write-up unedited for the same reason as the earlier "offshore" misread: it's not flattering, which is what makes it a credible account of the process rather than a highlight reel.

### Git hygiene as part of "done," not an afterthought

- **Prompt / goal:** none directly — also surfaced during verification.
- **First pass:** all of Claude Code's V1 work sat uncommitted in the working tree; the repo's only commit was the original scaffold.
- **Redirect / correction:** noted that `RunManifest`'s reproducibility guarantee records `git rev-parse HEAD` as part of a run's provenance, and an uncommitted working tree means that field would silently record a commit that doesn't match the code that produced the output — a correctly written mechanism undermined by a process gap around it, not a code defect.
- **Resolution:** committed the requirements-doc sync and the V1 build as two separate, logically distinct commits, added an MIT LICENSE, set up the GitHub remote (`entity-screening-toolkit`, shortened from the local folder's `-portfolio` suffix), and pushed — establishing real incremental commit history from this point forward rather than one large "finished" drop.
- **Why it matters for the write-up:** "done" for a portfolio piece isn't just working code — it's code whose own reproducibility claims are actually true, and a commit history that reads as real engineering process rather than a single opaque delivery.

---

## Phase 2 — FastAPI Refactor, Containerization, and a First Real Local Run (September 1, 2026)

### Plan-first on the risky change, direct-implement on the rest

- **Prompt / goal:** re-brief Claude Code on the corrected requirements doc (Section 9a) and get the FastAPI layer, CI, and Docker built.
- **First pass:** Claude Code proposed the FastAPI-layer refactor as a written plan before touching code, per the sequencing set in the re-brief — and caught its own reproducibility gap in that first draft (rescoring under a modified rubric could produce a downloaded file whose actual scores didn't match what its parent run's manifest claimed), fixing it before implementation rather than after review flagged it.
- **Redirect / correction:** review of the plan independently converged on the same gap, plus several smaller suggestions (an `ExportManifest` on every export, a `GET /manifest` endpoint, `dto.py` naming, sync vs. async route handling) — all adopted, verified by reading the actual diffs rather than trusting the completion report.
- **Resolution:** a seven-commit, cleanly incremental history (pipeline extraction → FastAPI layer → thin-client rewrite → Dockerfile split → CI integration job), each verified independently — 56 tests run directly, not just reported; the CI job's own internal-network check (`docker compose exec streamlit curl http://api:8000/health`) designed specifically to catch the exact stale-Dockerfile failure mode that had already shipped once.
- **Why it matters for the write-up:** the plan-first/direct-implement split by risk level worked as intended — the architecturally risky piece got caught and fixed twice (once by the builder, once by review) before it shipped, while the low-risk wrapping work didn't need that overhead.

### Docker Desktop, installed and actually used — not just described

- **Prompt / goal:** get the containerized stack running on Mike's own machine, not just verified in CI.
- **First pass:** walked through Docker Desktop installation on Windows 11 (WSL2 backend, PATH-refresh troubleshooting when a new terminal window didn't pick up the updated PATH), then `docker compose up --build` for the first time.
- **Redirect / correction:** none needed — this was Mike executing the walkthrough directly and reporting back real terminal output and screenshots at each step, not a correction so much as first-hand verification replacing secondhand trust.
- **Resolution:** a clean build, both containers healthy, a real screening run through the container split, matched against real OpenSanctions data (Zhongxing Telecommunication Equipment Corporation / ZTE) via the browser UI.
- **Why it matters for the write-up:** the gap between "Claude Code says it built the containers" and "I ran the containers on my own machine and watched them work" is exactly the distinction the verification habit in this whole project has been built around — this is the first time that gap closed all the way to a screenshot.

### A gap that only running the thing could have surfaced

- **Prompt / goal:** none directly — surfaced from reading Mike's own screenshot of the running app's "Run provenance" panel.
- **First pass:** `RunManifest.git_commit` read `null` for the Docker-run instance, despite the same field correctly capturing a real commit hash for every locally-run (non-containerized) instance.
- **Redirect / correction:** traced to `.dockerignore` excluding `.git` from the build context — `_git_commit()`'s subprocess call correctly fails and falls back to `None` inside the container, exactly as written, because the assumption it was written under (a `.git` directory reachable at runtime) stopped holding once the code moved into a container.
- **Resolution:** not yet fixed — recommended build-time commit-stamping (a Docker build arg baked into an image env var, checked before falling back to shelling out to `git`) rather than the naive fix of un-ignoring `.git`, which would ship the whole repo history into a runtime image just to read one hash.
- **Why it matters for the write-up:** neither reading the code nor watching the test suite pass would have caught this — it only exists at the intersection of two individually reasonable decisions (exclude `.git` from Docker images; read the git commit for reproducibility) that quietly conflict only in one specific runtime environment. A strong argument for why "I ran it myself and looked at the output" stays a distinct verification step, not a formality once tests are green.

---

## Phase 3 — V2, V3, the VSS Layer, and Deployment (September 1–2, 2026)

**A note on this phase, which is itself the first entry:** this section was written retrospectively on September 3, reconstructed from the git history, plan documents and code docstrings rather than from the sessions as they happened. That's a gap in the practice this log exists to demonstrate — the working agreement says a build-log entry gets written *after* a Claude Code session by reading the resulting history, and for roughly thirty commits across two days that didn't happen. The reconstruction is accurate about *what was decided* because this project documents its own reasoning unusually well in docstrings and `docs/plans/`; it is thin about *how* each decision got made, which is exactly the material the methodology write-up needs and the part that doesn't survive in artifacts. Same class of failure as the stale requirements doc in Phase 1: a process that works when followed, not followed.

### Real data changing a design constant, not a docstring

- **Prompt / goal:** build Epic E's bibliometric cross-check and verify it against live OpenAlex data.
- **First pass:** the cross-check reused the project-wide 0.80 screening threshold, on the reasonable assumption that one threshold should govern all fuzzy matching.
- **Redirect / correction:** live verification found a real false positive — a PI's real co-authors at the legitimate, non-military **Chinese Academy of Sciences** fuzzy-matched the bundled DoD 1260H list's **Chinese Academy of Ordnance Science** at 0.8387, comfortably clearing 0.80, and recurring 27 times across that PI's real papers. Not a hypothetical; a confirmed wrong answer at real scale.
- **Resolution:** the bibliometric stage got its own higher threshold (0.90), justified in the module docstring on a specific ground rather than a general one: this stage checks every co-author's institution across every paper, so it carries a volume-multiplication precision risk that screening one entity's own name once does not.
- **Why it matters for the write-up:** the correction came from running the thing against real data, not from reading the code — and it produced a *differentiated* design (two thresholds with distinct rationales) rather than a global tuning nudge. Uniformity is the easy default; the harder and better answer was that these two stages have genuinely different failure economics.

### A finding recorded and not actioned

- **Prompt / goal:** none directly — surfaced twice.
- **First pass:** `ingestion/nsf.py`'s live-fetch URL pointed at `api.research.gov`, a hostname that no longer resolves in DNS at all. This was discovered on September 1 while verifying a *different* feature (the Section 117 cross-check) against real data, written into that feature's plan document, and left unfixed.
- **Redirect / correction:** it stayed broken for a day, invisible because the application only ever exercised the local-file path. It was fixed on September 2, during unrelated work on the demo dataset.
- **Resolution:** endpoint corrected to `api.nsf.gov`, confirmed live, with the whole account written into `docs/data_sources.md`.
- **Why it matters for the write-up:** documenting a defect is not the same as tracking it. This project has excellent facilities for recording what it learns — plan docs, docstrings, a data-sources file — and no facility at all for making sure a recorded defect gets picked up. A finding written into a plan document for feature A is, in practice, invisible to the session that builds feature B.

### Deciding not to build something

- **Prompt / goal:** Epic D names three concern lists: OpenSanctions, DoD 1260H, and the "Seven Sons of National Defence" seed list. The obvious reading is that three lists means three implementations.
- **First pass:** the plan anticipated a dedicated `SevenSonsList` class and a curated data file, mirroring the `DoD1260HList` that had been built for the same reason.
- **Redirect / correction:** grepping the real 455MB OpenSanctions file first showed all seven universities already present as standalone, well-aliased entries, several explicitly citing NDAA Section 1286 as their designation basis. Building a dedicated list would have duplicated coverage that already existed.
- **Resolution:** no new code. A regression *test* was written instead, proving the existing `OpenSanctionsList` catches all seven by common name and by real acronym alias, with the contingency documented plainly: this coverage depends on OpenSanctions continuing to carry those designations, and unlike DoD 1260H's bundled snapshot there is no independent fallback if that changes.
- **Why it matters for the write-up:** the acceptance criterion was satisfied by demonstrating existing coverage rather than by adding a component. Checking the real data before implementing turned a feature into a test — and the discipline that made it defensible was writing down what the decision *depends on*, so a future failure of that assumption is a known risk rather than a surprise.

---

## Phase 4 — An Independent Review of the Finished Build (September 2–3, 2026)

### Commissioning a review of your own project, and what it takes to be worth anything

- **Prompt / goal:** with V1 through V3 plus the VSS layer built, tested and deployed, an end-to-end examination of the codebase against `docs/requirements.md`.
- **First pass:** the obvious shape for such a review is reading the code and reporting impressions. That produces plausible-sounding findings that are frequently wrong, because a reviewer reasoning from code alone infers behavior instead of observing it.
- **Redirect / correction:** the review was run as an empirical exercise instead — every module read in full, the test suite executed, and every behavioral claim reproduced with a probe script written against the real modules before being written down. Several plausible-looking suspicions did not survive that step and were dropped; others turned out worse than the reading suggested.
- **Resolution:** nine findings, each with quoted observed output. Four genuine defects, three acceptance-criteria gaps. Two examples of the difference empiricism made: acronym matching was *implemented correctly and unreachable*, because the blocking step that precedes it filters on a name prefix an acronym never shares — visible only by running a pair through `screen_entity` rather than through `score_pair`. And re-running topic-similarity enrichment turned out not merely to duplicate rows but to **silently produce zero flags**, because a duplicated embedding becomes its own runner-up and collapses the margin rule to nothing. Reading the code would have caught the duplication; only running it twice caught the inverted result.
- **Why it matters for the write-up:** "have the AI review the code" is nearly worthless advice on its own. The value is entirely in the standard applied — reproduce or don't claim it — and that standard is set by the human, not volunteered by the tool. It is the Phase 1 "verify the completion report" habit turned on a finished codebase rather than a single session's output.

### Choosing a different model for the review than for the build

- **Prompt / goal:** run the independent evaluation of the finished codebase against `docs/requirements.md`.
- **First pass:** the build work to this point had run on Sonnet 5 (high effort), which is the right fit for that job — high-volume, iterative implementation against approved plans, where the task is bounded and the acceptance criteria are already written down.
- **Redirect / correction:** Mike deliberately switched the reviewing session to Opus 5 (high effort) for the evaluation, on the reasoning that a whole-codebase review is a different *kind* of task from implementing against a spec. It has to hold roughly 8,500 lines of code and a 270-line requirements document in view simultaneously, notice cross-cutting patterns that no single file exhibits, and resist the plausible-but-wrong conclusions that reading code without running it invites.
- **Resolution:** the review produced nine defects and acceptance-criteria gaps, including four that share one structural shape — a guarantee lost at a boundary — which was only visible *across* findings, not within any one of them.
- **Why it matters for the write-up:** worth two caveats that keep it honest. This is n=1 with no control: no equivalent review was run on the other model, so the result is not evidence the switch was necessary, only that it was made deliberately and the output held up. And more pointedly — the higher-capability model produced a rigorous nine-finding review entirely *inside* the frame of the requirements document and never questioned the frame. Capability bought depth within the spec and nothing whatsoever against a wrong spec, which is the same wall the two-session separation hit, reached along a different axis. So the transferable point isn't "use the strongest model available." It's that model selection is a real design decision with a real cost, worth making per task type rather than once per project — and that scaling it up doesn't substitute for someone asking whether the target is the right one.

### A pattern in the findings that mattered more than the findings

- **Prompt / goal:** none directly — emerged from assembling the nine findings.
- **First pass:** the findings read as nine unrelated problems.
- **Redirect / correction:** four of them share one shape — a guarantee made carefully in one layer and quietly lost at a boundary. The acronym scorer, lost at the blocking step. `matched_field`, lost at the DTO. The OpenAlex precision caveat, lost outside Streamlit. The ownership chain's branch structure, lost in a flattened tuple. In each case the implementing layer was written thoughtfully; nothing checked that the guarantee survived to the edge.
- **Resolution:** the remediation plan added two test files written at the *outermost* seam — an output-contract test asserting against the parsed CSV row and the API JSON rather than the objects that build them, and an idempotency test running each enrichment step twice. Those two files would have caught four of the nine findings, and they exist to prevent the class rather than the instances.
- **Why it matters for the write-up:** a suite of 167 tests missed all four, because every one of them tested the function that implements a guarantee rather than the boundary that delivers it. Test *placement* is a design decision, and it is one an AI collaborator will mirror from the existing suite's habits rather than question unprompted.

### Verifying the fix before writing the plan, not after

- **Prompt / goal:** turn the nine findings into a remediation plan Claude Code could execute.
- **First pass:** a plan describing what to change is the normal deliverable.
- **Redirect / correction:** the two structurally non-obvious fixes — the acronym-blocking change and the branching/cycle-safe graph traversal — were prototyped against the real modules *before* the plan was written, and the observed output pasted into it. The acronym prototype confirmed all six acronym cases pass in both directions, all four true negatives still reject, and the candidate-set size was unchanged on a 20,000-entry stress test. The traversal prototype confirmed the path-accumulator CTE returns distinct real chains and terminates on a cycle.
- **Resolution:** the plan says "verified — implement as specified" on those two, and Claude Code implemented them without redesigning.
- **Why it matters for the write-up:** a handoff document containing a *checked* design costs one extra step from the author and removes an entire round of the builder re-deriving, second-guessing, or quietly substituting a different approach. The same argument as writing acceptance criteria instead of freehand prompts, applied one level down.

### Re-scoping around an external constraint rather than waiting it out

- **Prompt / goal:** eleven of thirteen workstreams were built; the remaining two were blocked because OpenAlex had rate-limited the build machine for an entire session.
- **First pass:** the plan's own dependency note said the security lockdown required a pre-computed demo run, which required a live bibliometric enrichment, which OpenAlex was refusing.
- **Redirect / correction:** testing the assumption showed the dependency's *literal* precondition still held — a screening-only run against the real 3,007-row OpenSanctions subset still yields zero direct matches, structurally — but its *purpose* was already satisfied. The dependency had been written to prevent an anonymous visitor seeing a blank page, and an earlier workstream had removed that failure mode by another route. Meanwhile the deployed site was still serving pre-remediation code with a live security exposure, so waiting on a third-party rate limit had a real cost and no benefit.
- **Resolution:** the demo run was re-scoped to screening-only and built to self-heal lazily on first request — which incidentally dodged a problem the literal approach would have hit, since the `./data` bind mount would have shadowed anything baked into the image at that path. Both remaining workstreams shipped.
- **Why it matters for the write-up:** a dependency in a plan is a claim about *why*, not just *what*. Re-reading the reason rather than obeying the arrow unblocked two days of work — and the point generalizes: a plan written by an AI collaborator (or handed to one) will be followed literally unless someone asks what it was protecting against.

---

## Phase 5 — Discovering the Project Was Built in the Wrong Direction (September 3, 2026)

### The requirements document had epics, user stories and acceptance criteria, and no user

- **Prompt / goal:** none — Mike stopped the engineering work mid-stream and raised, unprompted, that the project had been over-focused on getting the engineering right and under-focused on who would actually use it and what they needed to accomplish. He offered two concrete grounds: that NSPM-33 places screening responsibility at the institution level, so a university research-security analyst would never be pulling all NSF awards looking for conflicts; and that state legislation requires DS-160 data on visiting scholars to reach research-security teams, implying a workflow that starts from a person rather than from a corpus.
- **First pass:** nothing in fourteen prior sessions had raised this. The requirements document is genuinely well-formed — nine epics, user stories in "As an analyst, I want..." form, testable acceptance criteria — and every review to date, including the independent evaluation in Phase 4, had graded conformance to it and found the work strong.
- **Redirect / correction:** the epics were written from the **dataset** side, not the need side. The stack was chosen first (NSF awards, OpenSanctions, GLEIF, OpenAlex), and the user stories were composed afterward to justify what that stack could do. Section 4 "Users" names *"Mike, running it against real public data as a hands-on exercise"* and *"anyone evaluating it as a portfolio piece."* That is an audience, not a user with a job to be done. The "analyst" in every user story was never characterized: no persona, no workflow, no decision being supported, no regulatory driver. The apparatus of user-centred requirements was present; the user was not.
- **Resolution:** verification confirmed the substance of both claims. NSPM-33 places responsibility on institutions above roughly $50M in federal S&E support — and its implementation guidance states that a program with policy documents and *"no evidence any of the four processes has actually been used by a real case is not 'operational.'"* The regulator's own unit of evidence is a case. Monops has no concept of one. The application is **corpus-in, ranked-list-out**; the work is **subject-in, dossier-out**. Concretely absent from the schema: a subject of inquiry (`ResolvedEntity` is an organization derived from an award record, but both regimes make the *person* the subject), a case, a disposition, and a record of who reviewed what and when.
- **Why it matters for the write-up:** this is the most important entry in this log, and the least flattering. Every verification discipline the project built — tests, CI, live smoke tests, an independent nine-finding code review — validates **conformance to the specification**. None of them can detect a wrong specification, because all of them take it as ground truth. The project got the engineering right and the question wrong, and got the engineering right *so thoroughly* that the wrongness of the question stayed invisible for two weeks. Any honest methodology write-up about directing an AI collaborator has to say that the collaborator will optimize hard against whatever target it is given and will not, on its own, ask whether the target is the right one.

### The signal was in hand and mis-scoped, by the reviewer as much as anyone

- **Prompt / goal:** none — visible in hindsight across Phases 3 and 4.
- **First pass:** the demo produces zero findings. That was noticed repeatedly, diagnosed structurally and correctly (NSF only funds US-based recipients, so direct name matches against a sanctions or Chinese-military list are always zero — confirmed empirically by querying the live NSF API for `awardeeCountryCode=CN` and getting `totalCount: 0`), and treated as an unfortunate fact to explain to the visitor.
- **Redirect / correction:** the independent evaluation had this evidence in hand and filed it as Finding 8, *"the deployed demo shows nothing"* — a **presentation** problem — recommending cosmetic remedies: default a filter to unchecked, add an explainer panel, curate a bigger fixture. Three of the thirteen remediation workstreams then went into making a corpus-shaped demo presentable. The stronger reading was available and not taken: a screening tool whose central use case *structurally cannot produce a hit* is aimed at a question no analyst would ask. The zero was not a data problem or a presentation problem. It was a requirements signal.
- **Resolution:** the reframe came from Mike's domain knowledge, not from any review. The same origination pattern as Phase 0's OpenAlex addition — the human supplying something the AI collaborator did not and would not have produced on its own.
- **Why it matters for the write-up:** the failure mode worth describing isn't that a signal was missed. It's that a strong signal was *correctly observed, correctly explained, and assigned to the wrong category* — and that the independent reviewer brought in specifically to catch things did exactly the same thing, at length, with evidence. An AI collaborator asked to evaluate against a specification will produce a rigorous evaluation against that specification. Choosing what to evaluate against is upstream of anything it can help with.

### Verification improving the human's contribution, not just the AI's

- **Prompt / goal:** confirm the regulatory grounds for the reframe before building on them.
- **First pass:** Mike cited "Texas HB 27" as requiring DS-160 data be provided to university research-security teams, hedged appropriately as something he thought was true.
- **Redirect / correction:** HB 27 is a high-school personal-financial-literacy bill. The relevant statute is **HB 127** (89th Legislature, passed and in effect) — and it is considerably more useful than the remembered version. It requires institutions to obtain *"a copy of the person's passport and nonimmigrant visa application most recently submitted to the United States Department of State"*; it covers not only foreign nationals but anyone affiliated with a foreign institution or employed in a foreign-adversary country for at least a year, including U.S. citizens; it requires a **research security office** to *"review the materials... take reasonable steps to verify the information... and take any other action the office considers appropriate"*; and it is enforced by withholding state appropriations until a board certifies compliance.
- **Resolution:** the reframe now rests on the operative statutory text, which supplies a defined subject, defined inputs, a defined actor, and a defined output — close to a functional specification. It also turns the project's hardest technical problem inside out: a DS-160 carries declared prior employers, education and affiliations, so PI disambiguation stops being a guess from a bare name and becomes a **cross-check of a record against a declaration**, which is also the actual compliance question.
- **Why it matters for the write-up:** the mirror image of Phase 0's "offshore" misread. There, the AI misunderstood and the human corrected it. Here the human's recall was wrong and verification corrected it — and in both cases the checked version was better than either party's first draft. The write-up should present verification as a discipline applied to *every* input regardless of source, not as quality control aimed at the AI's output. A remembered bill number is exactly as much of an unverified claim as a generated one.

### What the wrong direction actually cost, stated precisely

- **Prompt / goal:** none — worth recording while the answer is still known rather than reconstructed later.
- **First pass:** the intuitive reading of "built in the wrong direction" is that the work is wasted.
- **Redirect / correction:** most of it isn't, and the reason is architectural. `pipeline.py` as a shared orchestration layer, a real API boundary, and a UI that is a thin HTTP client mean the entry point and the output shape can change without touching the engine. Entity resolution, the concern-list registry, the ownership graph, the bibliometric layer, scoring, the evidence trail and the manifests are all precisely what a case-based tool needs underneath. The re-scope is a UI plus a thin case model, not a rewrite.
- **Resolution:** the genuinely sunk cost is small and nameable: roughly three of thirteen remediation workstreams spent on making a corpus-shaped demo presentable (the curated OpenSanctions subset, the default-visible results table, the pre-computed demo run), plus the framing effort in the requirements document itself. Everything else — idempotency, provenance, attribution, output contracts, the security lockdown — is orthogonal to the entry point and survives intact.
- **Why it matters for the write-up:** this is the practical argument for the engineering discipline the rest of this log documents, and it lands better than the usual abstract case. Clean layering is normally justified as making future features cheaper. Its real payoff here was making a **wrong direction cheap to correct** — which is a more honest description of what software work is actually like, and a better reason to care about it.

---

### What the two-session separation caught, and what it didn't

- **Prompt / goal:** none — a retrospective assessment of the project's own working method, prompted by revising the working agreement in the header of this document.
- **First pass:** the split between a building session and a reviewing session is described in this log as a working arrangement, and its results are visible throughout: Phase 1's stale requirements doc and uncommitted working tree, Phase 2's `git_commit`-in-Docker gap, Phase 4's nine reproduced findings — several of which the builder had no way to see, because they were only visible from outside the code or only at real data scale.
- **Redirect / correction:** it did not, on its own, escape the frame of the specification. Phase 5's wrong-direction problem sat in plain sight of the reviewing session for a fortnight. The decisive evidence — a screening tool whose central use case structurally cannot produce a hit — was not merely available but had been observed, explained correctly, written up at length, and filed under the wrong heading as a presentation problem.
- **Resolution:** the separation is worth keeping and worth describing accurately. It makes the build materially more robust against error *within* the spec. It is not a substitute for someone asking whether the spec is aimed at the right thing, and the log should not imply otherwise.
- **Why it matters for the write-up:** two qualifications belong with any recommendation of this pattern. First, a second AI perspective is only worth anything if it is held to a standard — Phase 4 worked because the rule was *reproduce a claim or don't make it*, not because a second session existed. An adversarial reviewer without that standard produces confident agreement, which is worse than no reviewer at all, because it feels like verification. Second, both vantage points sit inside the requirements document. Structuring two AI sessions to check each other buys real redundancy against building the thing wrong, and none whatsoever against building the wrong thing.

---

## Phase 6 — [Not yet started]

*Next entries begin with the user/workflow definition work: personas, the job to be done, and the decision being supported, grounded in the HB 127 and NSPM-33 operative text rather than in assumptions — written before any interface work, deliberately reversing the order this project took the first time.*
