# Demo GLEIF ownership fixture — provenance

`gleif_lei.csv` and `gleif_relationships.csv` in this directory are a
**hybrid chain**: a fabricated subsidiary row connected by a fabricated edge
to a real, GLEIF-verified ultimate-parent row. This replaces an earlier
fully-fabricated three-node chain, closing the binding check in
`docs/plans/2026-09-06-use-case-01-implementation.md` §4.9/§9 via that plan's
own pre-specified fallback — see `docs/plans/2026-09-14-close-gleif-
verification-gate.md` for the full real-data verification.

| LEI | Legal name | Real? |
|---|---|---|
| `SYNTH0000000000000DEMO` | Nanjing Zhongke Robotics Co. Ltd | **fabricated** — the synthetic subject's declared employer. No real company by this name is asserted; the LEI is not a valid ISO 17442 identifier (`SYNTH…` prefix). |
| `549300JBU4TV5OCKJV96` | NIO INC. | **real** — extracted from a live GLEIF Golden Copy download (Sept 2026 snapshot, `goldencopy.gleif.org`), independently re-verified against GLEIF's own search interface: Cayman Islands, ACTIVE, previous legal name "NextCar Inc." |

The `IS_DIRECTLY_CONSOLIDATED_BY` / `IS_ULTIMATELY_CONSOLIDATED_BY` edge
between them is invented — GLEIF has no record connecting the fabricated
subsidiary to NIO Inc., because the subsidiary does not exist. What is real:
NIO Inc.'s own GLEIF record (LEI, legal name, jurisdiction, ACTIVE status) and
its designation on the DoD Section 1260H list
(`entity_screening/screening/data/dod_1260h.json`, entry `1260h-0204`,
"NIO, Inc." — a genuine, verbatim name match at confidence 1.0 against
"NIO INC."; `docs/data_sources.md`'s GLEIF entry records the full extraction).

This mirrors `tests/fixtures/demo_opensanctions_targets.NOTICE.md`'s
"indicate changes" discipline.
