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
| 2026-09-01 | [Section 117 foreign gift & contract disclosure cross-check](2026-09-01-section-117-foreign-gift-disclosure-cross-check.md) | Built |
| 2026-09-01 | [V3 — OpenAlex bibliometric affiliation layer](2026-09-01-v3-openalex-bibliometric-affiliation-layer.md) | Built |
| 2026-09-01 | [DuckDB VSS semantic topic-similarity layer](2026-09-01-vss-topic-similarity-layer.md) | Built |
| 2026-09-02 | [Section 9 deployment -- Lightsail via Terraform](2026-09-02-lightsail-deployment.md) | Built -- live at mikejennings.dev/monops |
| 2026-09-02 | [Remediation pass -- findings from the 2026-09-02 codebase evaluation](2026-09-02-remediation-pass.md) | Built |

**Known gap in this log:** the V2/Epic C plan (GLEIF ownership graph + foreign-control
flagging, built in commit `3c07677`) was approved via plan mode but never copied here —
an oversight in applying this practice, not a deliberate omission. Its content isn't
recoverable verbatim at this point; if it's ever worth backfilling, it would have to be
reconstructed from `docs/architecture.md`, `docs/data_sources.md`'s GLEIF entry, and
`git log`/`git show 3c07677`, not from a source-of-truth plan file.

Smaller, single-file changes that "wrap existing code" rather than reshape it (CI,
Dockerfiles, the DoD 1260H list wiring, the `git_commit` containerization fix) were
implemented directly without a plan-mode review cycle, per instruction, and so have
no corresponding file here — see their commit messages for the equivalent reasoning.
