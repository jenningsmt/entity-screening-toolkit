# Demo GLEIF ownership fixture — provenance

`gleif_lei.csv` and `gleif_relationships.csv` in this directory are a
**fabricated three-node ownership chain**, not extracted from GLEIF's Golden
Copy files. They exist so the HB 127 demo case (`case_id="demo"`) can
exercise the ownership discovery path end to end without shipping GLEIF's
~525 MB bulk download.

| LEI | Legal name | Real? |
|---|---|---|
| `SYNTH0000000000000DEMO` | Nanjing Zhongke Robotics Co. Ltd | **fabricated** — the synthetic subject's declared employer |
| `SYNTH0000000000000HOLD` | Zhongke Advanced Manufacturing Holdings Co. Ltd | **fabricated** — an intermediate holding company |
| `SYNTH0000000000000AVIC` | Aviation Industry Corporation of China Ltd. | name is that of a **real** DoD Section 1260H-listed entity (alias "AVIC"); the LEI and the ownership edges to it are fabricated |

The `IS_DIRECTLY_CONSOLIDATED_BY` / `IS_ULTIMATELY_CONSOLIDATED_BY` edges are
invented. The LEIs are not valid ISO 17442 identifiers (the `SYNTH…` prefix
makes that obvious).

**What is real:** the concern-list match. `Aviation Industry Corporation of
China Ltd.` is a genuine entry on the bundled DoD Section 1260H list
(`entity_screening/screening/data/dod_1260h.json`, a real snapshot — see
`docs/data_sources.md`). So the demo's headline finding —
*"declared employer's ultimate parent appears on the DoD Section 1260H
list"* — rests on real reference data for the part that matters (the
designation); only the corporate graph that connects the synthetic employer
to it is fabricated, and labelled here.

This mirrors `tests/fixtures/demo_opensanctions_targets.NOTICE.md`'s
"indicate changes" discipline. Replacing this with a real extracted chain
(a real GLEIF subsidiary whose real ultimate parent is 1260H-listed) is the
binding real-data check in
`docs/plans/2026-09-06-use-case-01-implementation.md` §4.9 / §9, to be done
against a live GLEIF download when that access is available.
