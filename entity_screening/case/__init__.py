"""Case model for Use Case 01 -- HB 127 researcher screening.

The unit of work is a *case*: one subject, one triggering event, one
deadline, one file. See docs/use-case-01-hb127-researcher-screening.md for
the specification and docs/plans/2026-09-06-use-case-01-implementation.md for
the plan. The engine (resolution, screening, ownership, bibliometric) is
reused unchanged; what lives here is the case lifecycle, the reconciliation
worksheet, adjudication, and the investigative-file export.
"""
