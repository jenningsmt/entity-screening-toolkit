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

Smaller, single-file changes that "wrap existing code" rather than reshape it (CI,
Dockerfiles, the DoD 1260H list wiring, the `git_commit` containerization fix) were
implemented directly without a plan-mode review cycle, per instruction, and so have
no corresponding file here — see their commit messages for the equivalent reasoning.
