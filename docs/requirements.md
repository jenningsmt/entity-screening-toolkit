# Entity & Research-Affiliation Screening Toolkit — Draft Requirements

**Status:** Draft for review
**Author:** Mike Jennings
**Date:** August 31, 2026
**Working title only** — name to be replaced before this goes public; kept descriptive for now, consistent with the existing repo naming pattern (`ed-sector-surveyor`, `ed-colony-scout`, etc.)
**Related:** builds on `ai-assisted-dev-expansion-opportunities.md` (Opportunity 1) in this same folder — that document has the full dataset rationale; this one turns it into a spec.

## 1. Background & Purpose

A public, non-classified, AI-assisted-development portfolio project that reproduces — at hobby scale, against open data — the core capability behind FinchAI's ARGUS Organizational Due Diligence module, Palantir- and Microsoft-style threat/risk screening, and the bibliometric affiliation-matching work named as a preferred qualification in the FinchAI posting. Built the same way the four Elite Dangerous tools were: Python, AI-assisted ("vibe coding") development with Claude, tested, packaged, and documented for public release.

This is explicitly a learning and portfolio exercise, not a production compliance product and not an investigative tool making real accusations. Every design decision below should be read with that framing: it needs to demonstrate the tradecraft and the engineering discipline, not stand in for a real screening system.

## 2. Goals

- Demonstrate entity resolution across multiple heterogeneous, real, open datasets — not a single clean list.
- Produce confidence-scored, evidence-traceable output an auditor could follow back to source records, mirroring the "explainable, traceable to source evidence, defensible to a customer compliance office" bar named in the FinchAI posting.
- Cover foreign-ownership/affiliation screening specifically (not just sanctions-list matching), including the bibliometric/co-authorship layer.
- Bake "potential match, not confirmed" framing into the data model and output itself, not just the README — treating every hit as a candidate pending human review.
- Produce a project that needs no explanation of relevance to due-diligence, research-security, or trust-and-safety roles — the translation work the ED tools currently require of a reader is done for them.

## 3. Non-Goals (out of scope for this project)

- Not a production compliance tool, not legal or investigative advice, not a system that asserts confirmed findings.
- Not covering secrecy-jurisdiction ownership (BVI/Cayman/Panama-style structures) — that's a different question from general foreign-ownership screening and is intentionally excluded; OpenOwnership/ICIJ are the tools for that question if it's ever taken up separately.
- Not attempting to scrape or reproduce ASPI's paywalled China Defence Universities Tracker data.
- No real-time monitoring or alerting in V1 — batch, run-on-demand only.
- No handling of genuinely sensitive/non-public data of any kind.

## 4. Users

Primary user is Mike, running it against real public data as a hands-on exercise. Secondary audience is anyone evaluating it as a portfolio piece — a recruiter, hiring manager, or GitHub visitor — so usability, documentation, and a clean demo path matter even though there's no real end-user support burden.

## 5. Data Sources

This is the full candidate stack discussed; the phased roadmap in Section 9 sequences which of these are actually built first. Not every source below ships in V1.

| Dataset | Role | Access | Format | Cadence | Known limitation |
|---|---|---|---|---|---|
| NSF Award Search | Entities/PIs to screen | Public API | JSON | Batch pull | PI name variants, public awards only |
| Section 117 Foreign Gift & Contract dashboard | Foreign funding disclosure records | Bulk download | CSV | Dept-published, periodic | Self-reported; coverage gaps possible |
| OpenSanctions (consolidated) | Entity-of-concern / restricted-party list (OFAC SDN, BIS Entity List, PEPs) | Bulk download / API | JSON/CSV | Regularly updated | Aggregation quality varies by upstream source |
| GLEIF Golden Copy (Level 1 + 2) | Corporate parent/subsidiary chain, jurisdiction | Bulk download | CSV/XML | Periodic snapshot | LEI registration is voluntary — coverage incomplete |
| SEC EDGAR (Exhibit 21, Schedules 13D/13G/13F) | Subsidiary lists, beneficial-ownership stakes | Bulk / API | Unstructured HTML (Ex. 21) / structured (13D-F) | Continuous filings | Exhibit 21 needs custom parsing, inconsistent formatting |
| DoD Section 1260H list | Entity-of-concern (Chinese military-linked companies) | Federal Register notice | PDF/list | ~Annual | Not machine-native |
| USDA AFIDA annual reports | Foreign agricultural land ownership | Report download | PDF/CSV (varies by year) | Annual | Structure/granularity varies year to year |
| BEA FDIUS data | Aggregate foreign direct investment by country/industry | Bulk download | CSV/Excel | Periodic | Aggregate only — benchmarking, not entity-level matching |
| OpenAlex bulk snapshot | Bibliometric graph: works, authors, institutions, co-authorship, citations | Bulk snapshot (S3, CC0) | JSONL | Periodic snapshot release | OpenAlex's own acknowledged affiliation-matching error rate |
| "Seven Sons of National Defence" (curated seed list) | Small free entities-of-concern seed for Chinese defense-linked universities | Manual/curated, static | Static list | N/A | Narrow — 7 institutions vs. ASPI's 180+ |

## 6. Functional Requirements

Written as epics with representative user stories and acceptance criteria — intentionally a representative slice per epic rather than an exhaustive backlog, to be expanded during actual grooming. This structure itself is deliberate practice: it mirrors "write clear epics, user stories, and acceptance criteria in Jira," a required qualification on the FinchAI posting.

### Epic A — Data Ingestion & Normalization

*As a builder, I want each data source ingested into a common internal schema, so that downstream matching logic doesn't need to know the quirks of each source format.*

- Acceptance: each source has a documented extraction script that streams (not loads-to-memory) large files where applicable, following the pattern already proven in `ed-sector-surveyor`.
- Acceptance: each ingested record retains its source dataset name, retrieval date, and source-record identifier, so every downstream fact is traceable back to where it came from.
- Acceptance: ingestion failures (malformed records, schema drift) are logged, not silently dropped.

### Epic B — Entity Resolution & Alias Matching

*As an analyst, I want candidate name matches across datasets even when spelling, formatting, or transliteration differs, so that a real match isn't missed because of surface-level string differences.*

- Acceptance: fuzzy name matching handles at minimum: abbreviation/acronym variants, **diacritic/accent-folding variants** (e.g. "Société Générale" vs "Societe Generale"), and common corporate-suffix normalization (Inc./LLC/Ltd., etc.). Narrowed from "transliteration variants" as of the 2026-09-02 remediation pass: `resolution/normalize.py:transliterate` only folds Unicode combining marks, which covers the accent case above and nothing a sanctions screener would actually call transliteration (Cyrillic, pinyin, or any other real script conversion). Real transliteration is a real gap, honestly out of scope for the current build rather than half-implemented — `unidecode`/`nomenklatura` are the named V4 path if it's ever taken up (see `docs/methodology.md`'s known limitations).
- Acceptance: every match returns a similarity/confidence score, never a bare boolean.
- Acceptance: a documented test set of "known-difficult" name pairs (true positives that look different, true negatives that look similar) exists and is checked on every run — mirroring FinchAI's own QA language ("known-difficult entities").

### Epic C — Ownership & Affiliation Graph

*As an analyst, I want to see an entity's corporate parent/subsidiary chain, so that a screening hit on a subsidiary surfaces the parent relationship instead of stopping at the subsidiary.*

- Acceptance: GLEIF Level 2 relationship data is used to build a traversable parent/subsidiary graph.
- Acceptance: the system can flag "this entity's ultimate parent is registered in a different country than the entity itself" using GLEIF Level 1 + 2 data together.
- Acceptance: graph traversal depth and direction (ultimate parent vs. direct parent) are both queryable, not collapsed into a single value.

### Epic D — Entity-of-Concern Screening

*As an analyst, I want resolved entities checked against multiple entity-of-concern lists, so that a match against any one list doesn't get missed because only one list was checked.*

- Acceptance: screening runs against OpenSanctions' consolidated list, DoD's Section 1260H list, and the Seven Sons seed list, each tagged with which list produced the hit.
- Acceptance: every hit records match confidence and the specific evidence (matched name variant, matched field) that produced it.
- Acceptance: no output ever states a match as confirmed — output schema itself only supports "candidate match" as a status, never "confirmed."

### Epic E — Bibliometric Affiliation Layer

*As an analyst, I want a researcher's co-authorship and institutional-affiliation history checked against flagged institutions, so that connections an institution's own disclosures don't mention can still surface for review.*

- Acceptance: PI names from NSF award data are resolved to OpenAlex author records (with a documented disambiguation confidence score, not an assumed 1:1 match).
- Acceptance: co-authorship and affiliation history for a resolved author is checked against the entity-of-concern list from Epic D.
- Acceptance: every result surfaces OpenAlex's own stated match-precision caveat inline, not buried in documentation — e.g., a persistent disclaimer alongside every bibliometric result, not just a one-time README note.

### Epic F — Scoring & Explainability

*As an analyst, I want a transparent, adjustable scoring model, so I can see exactly which factors drove a given entity's overall risk score and change the weighting if I disagree with it.*

- Acceptance: scoring weights are user-editable (mirroring the transparent, user-customizable scoring already built in `ed-colony-scout`).
- Acceptance: every score decomposes into its contributing factors on demand — no opaque single number without a breakdown available.

### Epic G — Output & Reporting

*As an analyst, I want a exportable report of candidate matches with their evidence trail, so I can review findings outside the tool itself.*

- Acceptance: CSV/Excel export of all candidate matches, confidence scores, contributing evidence, and source citations (mirroring the per-leg export pattern already built in `ed-expedition-ledger`).
- Acceptance: a companion methodology document ships alongside any published results, declaring data snapshot dates, matching thresholds, and known limitations explicitly (mirroring the reproducibility methodology docs already written for `ring-density-monitor`).

### Epic H — Testing & Validation

*As a builder, I want automated tests and a known-difficult-entity regression set, so that a change to matching logic can't silently regress accuracy.*

- Acceptance: pytest suite with unit tests per matching/scoring component.
- Acceptance: a fixture-based "known-difficult entity" regression set (per Epic B) runs on every change.
- Acceptance: a `--validate` or equivalent CLI mode exists for structural sanity checks, consistent with the pattern already used in `ed-expedition-ledger`.

### Epic I — Packaging & Documentation

*As a public repository visitor, I want clear documentation of what this is (and isn't), so I don't mistake a portfolio exercise for a production compliance tool.*

- Acceptance: README leads with the non-goals in Section 3 above, prominently, before any feature description.
- Acceptance: every third-party dataset's license/attribution terms are documented (OpenSanctions, GLEIF, OpenAlex's CC0, U.S. government works, etc.).
- Acceptance: architecture documentation follows the standard already set by the four ED repos (clear pipeline-stage breakdown, no unexplained magic).

## 7. Technology Stack (resolves two open questions from the original draft)

**Core language stays Python.** The instinct to move beyond the ED tools' stack is right, but the fix isn't the language — Python is the industry-standard tool for exactly this problem domain. OpenSanctions itself is built on Python (their own dedupe library, `nomenklatura`/Follow the Money); Splink, the well-regarded open-source Bayesian record-linkage library used by the UK Ministry of Justice and others, is Python. Moving the core engine to another language would trade away that ecosystem for no real benefit, and would read as a worse signal to the exact audience (FinchAI, Palantir, compliance-tech) who'd expect Python fluency for this class of work, not a rewrite in Go or Java.

What should change is everything downstream of "Python": the storage/query layer and the UI layer are where the ED tools' stack genuinely doesn't fit this project.

- **Storage/query layer: DuckDB (plus Parquet for large ingested sources), not plain SQLite.** SQLite is fine through V1's scale, but GLEIF and especially OpenAlex are large, join-heavy, analytical workloads — exactly DuckDB's purpose. It's still an embedded, single-file, no-server database (same operational simplicity as SQLite), but columnar and dramatically faster for the aggregate/join patterns this project needs. It also reads Parquet directly, which is the right storage format for the larger normalized datasets (smaller footprint than CSV/JSON, standard in modern data engineering). This resolves the "graph storage" open question from the original draft for the ownership chain (Epic C): parent/subsidiary traversal is a SQL join pattern DuckDB handles natively — no separate graph database needed there.
- **Matching library: `rapidfuzz` as the baseline, `Splink` as a credible stretch for V2/V3.** Splink is real production tooling (built on DuckDB, which pairs directly with the storage choice above) rather than a toy library, and naming it specifically is a stronger signal than a hand-rolled matcher.
- **Graph work for the bibliometric layer (Epic E) stays targeted, not bulk in-memory.** OpenAlex's co-authorship graph is far too large to load into NetworkX wholesale (see storage estimates below) — the right pattern is filtering in DuckDB/SQL down to the neighborhood around a specific flagged entity or PI, then materializing only that small subgraph in NetworkX for scoring or visualization.
- **UI layer: Streamlit, replacing Tkinter.** This is the change that actually matters for "beyond Python and tkinter," and it's driven by the portfolio-access question below as much as by the UI itself — Tkinter is desktop-only and invisible to someone browsing GitHub. Streamlit gets a working review UI (a scored, filterable, explainable table with adjustable weights) with a fraction of the boilerplate a React/FastAPI build would need, and deploys directly to a public URL for free. A FastAPI-plus-web-frontend build is a legitimate stretch if there's ever appetite to demonstrate a more conventional service architecture, but it's more engineering than this project needs to make its point.

## 8. Storage Estimates

Figures below are a mix of confirmed source figures (checked directly against each provider's documentation as of this writing) and reasoned estimates where the provider doesn't publish an exact number — flagged accordingly. Treat these as planning figures, not guarantees; verify against the live download pages before committing disk space.

| Phase | Added data | Estimated footprint | Confidence |
|---|---|---|---|
| V1 | NSF Award Search (JSON, scoped to a reasonable date range) | Well under 1 GB raw | Estimate |
| V1 | OpenSanctions Default — `targets.simple.csv` (434 MB) or `targets.nested.json` (3.64 GB), not the full 8.8 GB statements file, which is more granularity than this project needs | 0.4–3.6 GB raw, confirmed | **Confirmed** (checked against OpenSanctions' own dataset page) |
| **V1 total** | | **roughly 1–5 GB raw downloads; working DuckDB file likely well under that after normalization** | |
| V2 | GLEIF Level 1 + Level 2 concatenated files (~2.5–3M LEI records combined) | Roughly 0.5–1.5 GB as CSV | Estimate — GLEIF doesn't publish a fixed size and it grows over time; check at download time |
| V2 | Section 117 disclosure data | Under 100 MB | Estimate |
| **V2 cumulative** | | **roughly 2–8 GB raw** | |
| V3 | OpenAlex — **full bulk snapshot** | **660+ GB** | **Confirmed** (OpenAlex's own download documentation) — impractical for this project, see recommendation below |
| V3 | OpenAlex — **targeted API approach (recommended instead)** | Likely low single-digit GB: institutions + a bounded set of author records and their co-authorship/affiliation history for the specific PIs surfaced by NSF award data, not the full 260M+-work corpus | Estimate, but directionally solid given per-author record sizes |
| **V3 cumulative (recommended path)** | | **roughly 5–15 GB raw across the whole project** | |

The OpenAlex number is the one worth flagging clearly: the full snapshot is documented at over 660 GB, which rules out bulk ingestion for a hobby project on ordinary hardware. The actual V3 workflow (per Epic E) only needs specific PIs' authorship and affiliation history, not the entire scholarly graph — so the free daily API allowance (or the bulk snapshot filtered to just the `institutions` and a bounded `authors` slice, both far smaller than `works`) is the right access pattern, not a full snapshot download. This changes the recommendation in the original Epic E acceptance criteria from "bulk snapshot" to "targeted API/subset" — worth updating there too.

**Local dev environment constraint (confirmed):** development happens on a G: drive with 305 GB free, shared with other dev work rather than dedicated solely to this project. Against the recommended-path totals above (roughly 5–15 GB raw across all three phases, even generously doubled or tripled for scratch space, intermediate exports, and the Python environment itself), 305 GB leaves a wide margin — this is not a binding constraint under the plan as scoped. It's worth stating explicitly for one reason: it's also the guardrail behind the "targeted API, not full snapshot" decision for OpenAlex two paragraphs up. That decision was made on engineering-fit grounds (660+ GB doesn't belong in a hobby pipeline regardless of available disk), and the 305 GB figure confirms it's also the practically correct call for this specific machine — reverting to a full-snapshot approach at any point would consume roughly two-thirds of all free space on a drive doing other work, not just this project's.

## 9. Deployment & Portfolio Access

Unlike the four ED tools, everything this project touches is public, open data — there's no "no network calls" privacy requirement driving a desktop-only design here, which opens up a hosted option that's actually the better choice for the stated goal (a recruiter or hiring manager evaluating it with zero friction).

**Decision: self-hosted on AWS Lightsail rather than Streamlit Community Cloud**, on the strength of a bounded 6–12 month hosting window where the modest cost is acceptable. This doesn't change the application stack — Streamlit over DuckDB/Parquet still stands, and Streamlit runs behind nginx on a plain Linux box exactly as well as it runs on the managed platform. What changes is who owns the hosting, and it's worth being precise about what's gained and what's now Mike's responsibility rather than a platform's.

- **Recommended bundle: the $12/month tier** (2 GB RAM, up to 2 vCPUs, 60 GB SSD, 3 TB data transfer, current Lightsail pricing). That comfortably exceeds Streamlit Community Cloud's own free-tier ceiling (2.7 GB RAM max) but as dedicated capacity rather than a shared, throttled allocation — and 60 GB SSD is well beyond what a size-capped demo dataset needs. Total cost: roughly **$72 for six months or $144 for twelve** — in line with "minimal/acceptable." The $7/month tier (1 GB RAM, 40 GB SSD) is a viable cheaper fallback if the demo dataset stays small, but 2 GB is the safer choice once pandas/DuckDB are holding a working dataset in memory alongside the Streamlit runtime itself.
- **What's gained beyond cost:** no cold-start/sleep behavior (a genuine UX improvement over the free managed tier), no shared-tenant throttling, and — the most useful upgrade for a portfolio piece specifically — the ability to attach a **real custom domain** (a cheap domain registration, roughly $10–15/year, pointed at the instance's static IP). A URL like `entityscreen.<name>.dev` reads substantially better to an evaluator than a platform-branded subdomain, and Lightsail's static IP + DNS pointing is straightforward.
- **What's now owned rather than managed:** this is a real public-facing server for the hosting window, which means: an nginx reverse proxy in front of Streamlit's default port, a systemd unit (`Restart=always`) so the app recovers from a crash without manual intervention, TLS via Certbot/Let's Encrypt (free, but a one-time setup step plus an auto-renewal cron to leave in place), basic firewall hardening (Lightsail's built-in firewall panel makes opening only 80/443 straightforward), and periodic OS patching for the life of the instance. None of this is heavy for a single-purpose demo host, and setting it up is itself a small, legitimate, resume-relevant skill demonstration (basic Linux server administration and deployment) — but it's a different responsibility profile than a managed platform silently absorbing all of that, and worth being clear-eyed about rather than glossing over.
- **Hosting term: 6 months, with an explicit decision point rather than an automatic renewal.** Lightsail bills monthly with no fixed-term contract, so "6 months with an option to renew for 6 more" doesn't require any special plan — it's just the default monthly billing, left running. That cuts the other way from how it might sound, though: because there's no built-in end date, the instance renews *by default* by doing nothing, and it's the deliberate stop-or-continue decision that has to be scheduled, not the renewal itself.
  - Initial commitment: 6 months at the $12/month bundle = **$72**.
  - At the 6-month mark, an active decision: renew for another 6 months (**$144 total for the year**) if the demo is still earning its keep — still job-searching, being referenced in interviews, or otherwise getting used — or stop and delete the instance if not, leaving the GitHub repo (which has no hosting cost or end date) as the permanent record.
  - Set a calendar reminder roughly 2 weeks before the 6-month mark, not exactly on it — that leaves room to actually make the decision and act on it before the next monthly charge lands, rather than discovering the choice needs making the day it's due.
  - Set an AWS Budget alert (free) at the $72 initial ceiling as a backstop, and reset it to $144 if the renewal decision is "yes" — so an overlooked decision shows up as a cost notification rather than a silent, indefinite charge.
- **The demo still ships a pre-built, size-capped dataset, not the live full pipeline** — that guidance doesn't change with the hosting decision. 60 GB of SSD is generous relative to the storage estimates in Section 8, but the point of a curated demo slice (recent NSF awards, the OpenSanctions targets file, a bounded set of pre-resolved OpenAlex lookups) rather than the full multi-source pipeline running live still stands; the GitHub repo remains where the real, full pipeline lives and runs.
- **A short recorded demo (GIF or 60–90 second video) at the top of the README** is still worth having — a self-hosted instance removes the free-tier cold-start quirk, but a recording is cheap insurance against the instance being paused, mid-patch, or simply retired after the planned hosting window ends while the GitHub repo (and README) live on indefinitely.
- The GitHub repo itself, following the documentation standard already set by the four ED repos (architecture breakdown, methodology doc, explicit non-goals up front per Epic I), remains the primary artifact — the hosted demo is a convenience layer on top of it, not a replacement for it, and especially so here since the hosted instance has a planned end date and the repo doesn't.

## 9a. Adjustments Following FinchAI/ARGUS Research (added while still in V1 — see `finchai-argus-tech-research.md`)

Reading FinchAI's own open technical postings (not just the Product Analyst one) surfaced enough real signal about their actual stack and ARGUS's own architecture to justify a few changes, made now specifically because V1 isn't far enough along for them to be costly. Each is defended on its own engineering merits, not adopted just because FinchAI does it — see the "deliberately not adopted" list at the end for the ones that didn't clear that bar.

**Architecture change — add a FastAPI layer under Streamlit.** Confirmed: FinchAI's own data/visualization platform (very likely ARGUS or a close sibling) is built on Python/FastAPI with a separate frontend, and "API design"/"REST API interactions"/"microservices" appear across multiple of their postings. Streamlit remains the demo UI, but it should be a thin consumer of a REST API sitting over the `entity_screening` engine package, not the entire application. This is better architecture regardless of FinchAI, and it keeps the door open to a real frontend later without rework.

**New epic — Epic J: Evidence-Grounded Explanation Generation (V3-adjacent).** This is the one substantive gap the research surfaced: the project as scoped is pure structured matching (fuzzy names, confidence scores), while ARGUS's own stated differentiator, per NSF's program materials, is a RAG pipeline and "AI agents" layered on top of the entity knowledge base — and the AI/ML Engineer posting is built entirely around that (embedding generation, retrieval, prompt assembly, LLM integration).

- *As an analyst, I want a natural-language explanation of why a candidate match was flagged, grounded strictly in its retrieved evidence, so I can understand a result without reading raw scoring fields.*
- Acceptance: the explanation generator is only given the specific evidence records (matched name variant, source dataset, contributing score factors) already produced by Epics D/F as its context — it is never allowed to assert anything beyond what that evidence supports. This is a real RAG constraint, not decoration, and it's the same "transparent, trustworthy" principle FinchAI states as its own differentiator, not just a stack imitation.
- Sequencing: proposed for V3 alongside or after the bibliometric layer, not V1 — but flagged now because it changes a design decision that's cheap now and expensive later (below).

**Schema discipline, effective immediately (affects Epics A and D, no new scope):** evidence records produced by ingestion and screening should be structured, source-cited, and self-contained from V1 onward — clean enough to hand directly to an LLM as retrieval context in Epic J without restructuring. This costs nothing extra now; it would cost real rework if evidence records were designed ad hoc in V1/V2 and only made LLM-ready when Epic J actually starts.

**Bibliometric layer addition — DuckDB's vector-similarity-search (VSS) extension for Epic E.** Semantic matching over OpenAlex paper abstracts/titles, not just exact or fuzzy name matching, is a genuinely better fit for that specific dataset (unstructured text) than name-matching alone — and it's a real, defensible way to gain vector-search experience (named as a preferred skill twice across FinchAI's postings) without abandoning the embedded, no-server DuckDB architecture already chosen for everything else.

**Deployment change — provision Lightsail via Terraform, ideally CDKTF (Python bindings).** FinchAI's Full Stack Developer posting names "CDKTF/terraform" directly. This doesn't change the hosting decision (Lightsail, $12/month, 6-month term — all still stand), only how the instance gets stood up: infrastructure-as-code instead of manual console setup, and CDKTF specifically keeps the whole project in Python rather than introducing HCL as a second language.

**Testing/packaging made explicit, not just implicit (Epics H and I):** CI/CD (GitHub Actions running the pytest suite on push) and a Dockerfile for the API layer should be treated as acceptance criteria now rather than assumed later — both already worked well in `ed-colony-scout`'s CI setup, and both are named directly in FinchAI's Software Engineer posting.

**Deliberately not adopted, so it reads as a decision rather than an oversight:**
- **AWS GovCloud** — exists to handle classified/export-controlled workloads; pure cost and friction for an open-data hobby project with no payoff.
- **Formal RMF/ATO accreditation** — a real DoD/IC compliance process named in the Software Architect posting, entirely irrelevant without an actual government customer.
- **A full Vue.js frontend** — real engineering scope for uncertain benefit right now; the FastAPI layer above preserves the option without requiring it today.
- **Stating the FinchAI connection in the public README.** Making good architecture decisions that happen to overlap with what was learned here is legitimate engineering judgment; writing "this mirrors FinchAI's job postings" into the repo itself would read as reverse-engineering the interview rather than genuine engineering interest. The "why" belongs in a cover letter or an interview conversation, not baked into the public artifact.

## 9b. Implementation Update (September 2026)

Section 9 above was written before two real decisions were finalized:

- **Domain registered:** `mikejennings.dev`.
- **Project named:** Monops (the "working title" framing throughout this
  document and the README is now stale as of this addendum).
- **Path, not subdomain:** the demo lives at `mikejennings.dev/monops`
  rather than the `entityscreen.<name>.dev`-style subdomain Section 9
  originally suggested. Nothing else is hosted at the apex domain yet, which
  is what makes this workable -- nginx on the one Lightsail instance serves
  a placeholder at `/` and reverse-proxies `/monops` to the app, leaving
  room to put a real portfolio site at the apex later without touching the
  app's own routing.
- **Infrastructure code lives in `infra/`, as plain Terraform (HCL), not
  CDKTF.** Section 9a specified CDKTF (Python bindings); that was corrected
  the same day after discovering HashiCorp archived CDKTF on December 10,
  2025 (no further maintenance, official guidance to migrate to plain
  Terraform/HCL) -- see `docs/plans/2026-09-02-lightsail-deployment.md`'s
  correction note for the full story, and `docs/deployment-runbook.md` for
  the actual step-by-step commands (`terraform init/plan/apply`, not
  `cdktf deploy`). This addendum records the decisions; it doesn't restate
  Section 9's reasoning, which still stands.

## 10. Non-Functional Requirements

- **Explainability first:** every score must be traceable to underlying evidence records — no black-box outputs.
- **Confidence over booleans:** no component of the system may output a bare true/false match; everything is a scored candidate.
- **Language discipline:** "candidate," "potential," and "unconfirmed" are enforced in the data schema and output templates, not left to documentation to clarify.
- **Reproducibility:** every run records the exact dataset snapshot version/date used, so a result can be traced to the data as it existed at that time (mirroring `ring-density-monitor`'s reproducibility discipline).
- **Batch-first, not live-dependent:** the system operates against downloaded snapshots rather than continuous live API dependency, both for reproducibility and to avoid the OpenAlex API's usage-based pricing entirely.
- **Scale:** streaming ingestion patterns (as used in `ed-sector-surveyor`'s 108GB-dump handling) are required for any source in the millions-of-records range (OpenAlex, GLEIF, OpenSanctions).
- **License compliance:** attribution and license terms tracked per source and surfaced in output, not just in a README.

## 11. Open Questions / Risks

- **Scope risk:** this spans nine candidate datasets — meaningfully larger than any single ED tool. The phased roadmap below exists specifically to manage that; resist the urge to build all nine before shipping anything.
- ~~**Architecture shape**~~ — resolved in Section 7: Streamlit UI over a DuckDB/Parquet backend.
- ~~**Graph storage**~~ — resolved in Section 7: DuckDB/SQL for ownership-chain joins, NetworkX only for small materialized neighborhoods around flagged entities.
- **Exhibit 21 parsing effort:** may need to scope to a sample set of companies for V1 rather than the full EDGAR corpus, given the unstructured-HTML parsing effort involved.
- **Public framing:** whether this gets a LinkedIn-post treatment like the TAMU draft did for the ED work is worth deciding before publication, not after — it affects how the non-goals and disclaimers need to read.
- **Legal/reputational care:** any public writeup involving real named entities needs the disclaimer language finalized and reviewed before publishing, not drafted after the fact.

## 12. Proposed Phased Roadmap

**V1 — Minimum viable screening loop**
NSF award data (entities to screen) + OpenSanctions (entity-of-concern list) + fuzzy name/alias resolution (Epic B) + confidence scoring (Epic F) + CSV export (Epic G) + core test suite (Epic H). This alone is a complete, demoable due-diligence loop and the right point to get real feedback before extending further.

**V2 — Ownership and disclosure layer**
Add GLEIF ownership graph (Epic C) + Section 117 foreign-funding cross-check + foreign-control flagging (parent jurisdiction ≠ entity jurisdiction).

**V3 — Bibliometric layer**
Add OpenAlex co-authorship/affiliation matching (Epic E) + the Seven Sons / BIS-listed-university entity-of-concern seed. Sequenced last deliberately: it's the most differentiated and interesting piece, but also the one with the most data-acquisition and disambiguation risk, so it benefits from the groundwork in V1/V2 being solid first.

**Stretch / not currently scheduled**
SEC Exhibit 21 and 13D/13G/13F parsing, USDA AFIDA and BEA FDIUS benchmarking layers, and the OpenOwnership/ICIJ secrecy-jurisdiction question if it's ever taken up as its own separate effort.

## 13. Sources Referenced

- [FinchAI Product Analyst job description — ARGUS platform](.) (saved locally; not web-hosted)
- [OpenSanctions](https://www.opensanctions.org/) / [GitHub](https://github.com/opensanctions/opensanctions)
- [GLEIF Golden Copy / Concatenated Files](https://www.gleif.org/en/lei-data/gleif-golden-copy/download-the-golden-copy) / [Level 2 "Who Owns Whom"](https://www.gleif.org/en/lei-data/access-and-use-lei-data/level-2-data-who-owns-whom)
- [Section 117 Foreign Gift and Contract Public Transparency Dashboard](https://www.foreignfundinghighered.gov/downloads)
- [DoD Section 1260H list — Federal Register notice](https://www.federalregister.gov/documents/2025/01/07/2025-00070/notice-of-availability-of-designation-of-chinese-military-companies)
- [USDA AFIDA annual reports](https://www.fsa.usda.gov/resources/economic-policy-analysis/afida/annual-reports)
- [BEA Direct Investment by Country and Industry](https://www.bea.gov/data/intl-trade-investment/direct-investment-country-and-industry)
- [OpenAlex](https://openalex.org/) / [affiliation-error caveat, OpenAlex's own blog](https://blog.openalex.org/when-affiliation-errors-become-a-research-security-problem/)
- [ASPI China Defence Universities Tracker](https://unitracker.aspi.org.au/) (structured data paywalled — excluded from this project; noted for completeness)
- [OpenOwnership Register](https://register.openownership.org/download) and [ICIJ Offshore Leaks](https://offshoreleaks.icij.org/pages/database) (relevant only if the secrecy-jurisdiction question is ever taken up separately)
- `ai-assisted-dev-expansion-opportunities.md` (this project folder) — originating brainstorm and full rationale for each choice above
