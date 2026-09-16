# Implementation Plans

A log of the design/implementation plans reviewed and approved (via Claude Code's
plan mode) before each non-trivial piece of this project got built. Plans normally
live only in a local, non-project-scoped Claude Code directory
(`~/.claude/plans/<random-slug>.md`) and get silently overwritten the next time plan
mode starts a new task in the same conversation — they weren't part of the repo's own
history until this directory was added. Going forward, every approved plan gets
copied here as part of the same work that implements it.

**These are historical records, not living specs.** Each file captures the plan *as
approved*, before implementation — read `git log` / `docs/architecture.md` for what
was actually built, since implementation sometimes justifiably deviates from the plan
in small ways (documented in commit messages when it does). Don't edit a plan file
after the fact to match what shipped; if a plan meaningfully changes shape mid-build,
that's worth its own note in the file or a follow-up plan, not a silent rewrite.

## Index

| Date | Plan | Status |
|---|---|---|
| 2026-08-31 | [V1 — minimum viable screening loop](2026-08-31-v1-minimum-viable-screening-loop.md) | Built |
| 2026-08-31 | [FastAPI layer under Streamlit](2026-08-31-fastapi-layer-under-streamlit.md) | Built |
| 2026-09-01 | [V2 Epic C -- GLEIF ownership graph and foreign-control flagging](2026-09-01-v2-epic-c-gleif-ownership-graph.md) | Built (backfilled 2026-09-15 from the shipped commit -- see the file's own header for what's reconstructed vs. independently verified) |
| 2026-09-01 | [Section 117 foreign gift & contract disclosure cross-check](2026-09-01-section-117-foreign-gift-disclosure-cross-check.md) | Built |
| 2026-09-01 | [V3 — OpenAlex bibliometric affiliation layer](2026-09-01-v3-openalex-bibliometric-affiliation-layer.md) | Built |
| 2026-09-01 | [DuckDB VSS semantic topic-similarity layer](2026-09-01-vss-topic-similarity-layer.md) | Built |
| 2026-09-02 | [Section 9 deployment -- Lightsail via Terraform](2026-09-02-lightsail-deployment.md) | Built -- live at mikejennings.dev/monops |
| 2026-09-02 | [Remediation pass -- findings from the 2026-09-02 codebase evaluation](2026-09-02-remediation-pass.md) | Built |
| 2026-09-06 | [Use Case 01 -- HB 127 researcher screening: implementation](2026-09-06-use-case-01-implementation.md) | Built (the vertical slice, C1--C8; step 4 and beyond outstanding) |
| 2026-09-06 | [Concern ties as a distinct observation, not a Finding](2026-09-06-concern-ties-as-a-distinct-observation.md) | Built (C1--C8; the adversary-country list attribute stays deferred) |
| 2026-09-07 | [Pin the Streamlit app to a dark theme](2026-09-07-pin-streamlit-dark-theme.md) | Built (C1; `toolbarMode` left alone pending the post-deploy browser check) |
| 2026-09-14 | [Close the GLEIF real-data verification gate (hybrid fallback)](2026-09-14-close-gleif-verification-gate.md) | Built |
| 2026-09-14 | [Step 4 -- foreign-adversary-country list ingester](2026-09-14-foreign-adversary-list-ingester.md) | Built (DNI-ATA path only; gubernatorial path ships empty) |
| 2026-09-14 | [Step 5 -- restricted-party screening](2026-09-14-restricted-party-screening.md) | Built (OFAC-embargoed-country screening explicitly out of scope) |
| 2026-09-14 | [Streamlit UI for restricted-party screening](2026-09-14-restricted-party-screening-ui.md) | Built (a separate `pages/` view from the HB127 worksheet; also closed a data-file-allowlist gap found while building it) |
| 2026-09-14 | [Sidebar navigation -- real labels, positioned as buttons under the logo](2026-09-14-sidebar-navigation.md) | Built (migrated to `st.navigation()`; also found and fixed an `on_click`-callback `switch_page` bug during verification) |
| 2026-09-15 | [Step 6 -- annual COI/Outside-Interest disclosure reuse](2026-09-15-step-6-coi-annual-disclosure-reuse.md) | Built (narrower than the original "COI and NSPM-33" framing -- NSPM-33's own federal disclosure forms stay out of scope; `Case.declaration_id` and optional `coverage_basis` were the two real generalizations "nearly free" undersold) |
| 2026-09-15 | [Epic J -- evidence-grounded explanation generation](2026-09-15-epic-j-evidence-grounded-explanation.md) | Built (recitation is fully templated; the one allowed synthesis sentence is verified by citation grounding + a forbidden-lexicon check before it can ever be persisted; the real-model CI guard landed in its own workflow file, not inside `ci.yml` -- see the plan file's own Implementation note) |
| 2026-09-16 | [Phase 1 -- public-surface hotfix](2026-09-16-phase-1-public-surface-hotfix.md) | Built and deployed (B2-B4, S7, S8, S12, M16, S6-interim) |
| 2026-09-16 | [Phase 2 -- Epic J grounding gate](2026-09-16-phase-2-epic-j-grounding-gate.md) | Built (B1, S14, M17, S13, M20, S17; also bumped `DEMO_FIXTURE_VERSION` 5->6, required by M17 -- see the plan's Implementation note; full suite + `cli validate` green; deploy still outstanding) |

**Resolved gap in this log (2026-09-15):** the V2/Epic C plan (GLEIF ownership graph +
foreign-control flagging) was approved via plan mode but never copied here — an
oversight in applying this practice, not a deliberate omission. It's backfilled now,
above. Two corrections to what this note used to say: first, the commit was originally
cited here as `3c07677` — that hash no longer resolves (`git show`/GitHub both 404 on
it) because this repo's history was rewritten with `git-filter-repo` on 2026-09-02
(`.git/filter-repo/commit-map` records the full old-hash → new-hash mapping); the
commit survived the rewrite intact, just under a new hash,
`0f8bf276be8d6e0d44c61743b2797daa6211332b`. Second, the shipped commit's own message
turned out to be detailed enough (architecture rationale, real-data bugs found, timing
numbers) that the backfilled file below is closer to a real reconstruction than a bare
summary — what's genuinely unrecoverable is only the pre-approval plan-mode
conversation itself, not the design record.

Smaller, single-file changes that "wrap existing code" rather than reshape it (CI,
Dockerfiles, the DoD 1260H list wiring, the `git_commit` containerization fix) were
implemented directly without a plan-mode review cycle, per instruction, and so have
no corresponding file here — see their commit messages for the equivalent reasoning.
