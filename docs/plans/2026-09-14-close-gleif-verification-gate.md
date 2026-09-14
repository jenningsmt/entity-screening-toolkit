# Close the GLEIF real-data verification gate (hybrid fallback)

*Plan as approved via Claude Code plan mode, 2026-09-14. Historical record — read
`git log` for what actually shipped.*

---

## Context

`docs/plans/2026-09-06-use-case-01-implementation.md` (§4.9, §5 item 10, §9) made a
real GLEIF chain terminating at a real DoD Section 1260H entity a **binding check
before the relevant commits merge**. It was never met — the demo's headline ownership
finding (`tests/fixtures/demo_case/gleif_lei.csv` / `gleif_relationships.csv`) was a
fully fabricated three-node chain (`SYNTH...`-prefixed LEIs); only the ultimate
parent's *name string* happened to coincide with a real 1260H entity
("Aviation Industry Corporation of China Ltd."), not its LEI or the edges connecting
it to the fictional subsidiary.

That Sept 6 plan pre-specified two possible resolutions: use a fully-real subsidiary
name if one exists, **or its documented fallback** — *"a clearly-labeled synthetic
GLEIF fixture row for the subsidiary only, whose `IS_DIRECTLY_CONSOLIDATED_BY` edge
points at a real parent LEI genuinely on 1260H."* **This plan implements the
fallback, by deliberate choice**, not because a fully-real chain doesn't exist (it
does — see below) but because naming a specific real company as the fictional
subject's declared employer was judged unnecessary exposure for no added
verification value. The parent/concern-list side gets full real-data verification
either way.

## Real-data verification (done, not hypothetical)

- Downloaded the real GLEIF Golden Copy (Sept 14, 2026 snapshot) from
  `goldencopy.gleif.org` — the exact host/endpoint `entity_screening/ownership/ingest.py`
  already documents as correct. Level 1: 3,429,553 rows. Level 2 (ACTIVE
  `IS_DIRECTLY_CONSOLIDATED_BY`/`IS_ULTIMATELY_CONSOLIDATED_BY` only): 259,543 rows.
- Loaded through the project's own unmodified `ownership/ingest.py:load_gleif_level1/2`.
- Scored every real ACTIVE GLEIF parent-side entity's `legal_name` against all 214
  real DoD 1260H entities/aliases with the project's own matcher
  (`resolution/matcher.py:score_pair`). 8 real GLEIF entities matched a real 1260H
  entity at confidence 1.0: Baidu, Alibaba, China National Chemical, CNOOC, China
  Mobile, China Communications Construction, and NIO — plus one genuine
  false-positive collision worth recording separately: the real, unrelated
  US-listed "CoStar Group, Inc." vs. 1260H's "Costar Group Co., Ltd.," also 1.0
  (same class of risk already documented for Apple Inc./Apple Ltd. in
  `docs/data_sources.md`).
- Confirmed a fully-real subsidiary→parent chain was also available (NIO Inc. →
  its real Hong Kong subsidiary NIO Nextev Limited, `549300M7QP1IAPEG1K62` — GLEIF
  publishes both the `IS_DIRECTLY_CONSOLIDATED_BY` and `IS_ULTIMATELY_CONSOLIDATED_BY`
  edge directly between the two, no branching, no truncation) — not used, per the
  scope decision above.
- Ran the actual, unmodified production code end-to-end
  (`reconciliation/discover.py:tie_from_ownership`) against the real parent row plus
  the real bundled DoD 1260H list. Confirmed exactly one `ConcernTie`,
  `concern_entity_name="NIO INC."`, confidence 1.0.
- Independently re-verified by Mike directly against GLEIF's own search UI (not
  just this session's extraction): `549300M7QP1IAPEG1K62` = NIO Nextev Limited,
  Hong Kong, ACTIVE; `549300JBU4TV5OCKJV96` = NIO INC., Cayman Islands, ACTIVE
  (previous legal name "NextCar Inc."). Both confirmed real, current, and ACTIVE.

Real column values for the parent row, pulled directly from the downloaded file:

| LEI | legal_name | legal_jurisdiction | hq_country | entity_status | entity_category |
|---|---|---|---|---|---|
| `549300JBU4TV5OCKJV96` | NIO INC. | KY | CN | ACTIVE | GENERAL |

1260H entry matched: `id=1260h-0204, clean_name="NIO, Inc."`.

## Scope of changes

**Fixture shape:** the chain became 2 nodes, not 3 — the existing fabricated
subsidiary row stayed as-is (no fabricated intermediate holding company; the
pre-approved fallback text says "the subsidiary *only*"), with its edge repointed
directly at the real NIO Inc. row.

1. `tests/fixtures/demo_case/gleif_lei.csv` — 2 rows: the existing fabricated
   subsidiary row, unchanged, plus the real `549300JBU4TV5OCKJV96,NIO INC.,KY,CN,ACTIVE,GENERAL`
   row. The fabricated intermediate `SYNTH...HOLD` row was dropped.
2. `tests/fixtures/demo_case/gleif_relationships.csv` — 2 edges (both
   `IS_DIRECTLY_CONSOLIDATED_BY` and `IS_ULTIMATELY_CONSOLIDATED_BY`, `ACTIVE`) from
   the fabricated subsidiary LEI directly to the real NIO Inc. LEI — matching the
   real data's own shape for a single-hop relationship.
3. `tests/fixtures/demo_case/declaration.json` — **not touched.** Employer
   `institution_name` and `country` stayed exactly as they were.
4. `tests/fixtures/demo_case/gleif.NOTICE.md` — rewritten as a hybrid provenance
   note documenting which row is real and which is fabricated, and why.
5. `entity_screening/case/demo.py` — updated the fixture comment block; bumped
   `DEMO_FIXTURE_VERSION` 2 → 3 (with a history comment, matching the existing v2
   annotation style) so any deployed persistent data volume rebuilds the demo case
   with the new parent-row data on next access.
6. `entity_screening/case/export.py` — rewrote `PROVENANCE_NOTICE` to accurately
   state the ownership edge and the ultimate parent's own GLEIF/1260H record are
   real, while the subsidiary/employer identity remains a fabricated fixture. This
   was the highest-value fix in the plan: it's the text every downloaded
   investigative file carries, and the old wording ("any corporate ownership chain
   shown here... is itself a fabricated fixture") would have become false.
7. Tests updated: `tests/test_demo_case.py:60`; `tests/test_reconciliation.py`
   at the `concern_entity_name` assertions (former lines 210, 283), the
   "parent is itself declared" test's second `DeclaredAffiliation` (former line
   267), and the "both at once" test's synthetic OpenAlex works fixture
   `display_name` plus its downstream `avic_findings` filter variable (former
   lines 311-312, 331) — all renamed from "Aviation Industry Corporation of China
   Ltd." to "NIO INC.". `tests/test_reconciliation.py`'s `declared_employer_name`
   assertion (former line 247) was deliberately left unchanged — the employer
   identity never moved.
8. `docs/use-case-01-hb127-researcher-screening.md` §10 — replaced the "As built"
   paragraph describing the whole chain as fabricated with one describing the
   hybrid shape, and closed the binding-check reference.
9. `docs/data_sources.md` — GLEIF/Use-Case-01 section: recorded the real-data
   verification pass (figures, the 8 real matches found, the decision to use the
   fallback, and the CoStar/Costar false-positive collision as a documented
   "known-difficult" case).

## Deliberately not touched

- `docs/plans/2026-09-06-use-case-01-implementation.md` and
  `docs/plans/2026-09-06-concern-ties-as-a-distinct-observation.md` — historical
  plan records; this new plan is the place closure is recorded instead, per
  `docs/plans/README.md`'s own stated discipline.
- `docs/2026-09-09-repository-archaeology-report.md` — a dated audit snapshot.
- `docs/architecture.md` / `docs/methodology.md` — describe GLEIF/Epic C
  generically; nothing there was inaccurate.
- `entity_screening/ownership/ingest.py`, `match.py`, `graph.py`,
  `reconciliation/discover.py` — no code changes. Fixture-data-only change; this
  existing code passed end-to-end, unmodified, against the real data above.

## Verification

1. `pytest -q` — 277 passed.
2. `python -m entity_screening.cli validate` — passed.
3. Ran the demo case end-to-end (reconcile → worksheet → dismiss/certify findings →
   escalate the tie → adjudicate → export JSON) via the same production service
   functions `tests/test_output_contract.py` exercises. Confirmed: exactly one
   `ConcernTie`, `concern_entity_name="NIO INC."`, confidence 1.0, real 1260H
   evidence (`entry_id=1260h-0204`); the exported `PROVENANCE_NOTICE` text
   correctly distinguishes the fabricated subsidiary from the real parent; no
   leftover fabricated LEIs (`SYNTH...HOLD`/`SYNTH...AVIC`) anywhere in the export.
4. `docker` CI job's corpus-path parity assertion (`entities_count==2,
   hits_count==1`) is untouched by this change (exercises the batch path only).
5. The live Lightsail instance's persistent volume will pick up the new fixture +
   bumped `DEMO_FIXTURE_VERSION` automatically via the existing self-healing
   rebuild logic on its next redeploy — not part of this change; worth confirming
   once live.
