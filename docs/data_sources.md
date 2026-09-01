# Data Sources: License & Attribution

Per `docs/requirements.md` Section 10 ("License compliance: attribution and license
terms tracked per source and surfaced in output, not just in a README") and Epic I.
Every exported row already carries its source dataset name via the evidence trail
(`entity_screening/output/export.py`); this document is the canonical statement of
each source's terms.

## Sources used in V1

### NSF Award Search
- **Provider:** U.S. National Science Foundation, a U.S. federal agency.
- **License:** U.S. Government work — not subject to copyright in the United States
  (17 U.S.C. § 105).
- **Attribution:** "Source: NSF Award Search (research.gov), retrieved on the date
  recorded in this run's manifest."
- **Known limitation:** PI name variants; only publicly disclosed awards are included.

### OpenSanctions (consolidated `targets.simple.csv`)
- **Provider:** OpenSanctions.
- **License:** Free for non-commercial and journalistic use under OpenSanctions' own
  terms; commercial use requires a separate data license. This project is a
  non-commercial, public portfolio exercise. See
  <https://www.opensanctions.org/licensing/> for current terms before any other use.
- **Attribution:** "Data: OpenSanctions (opensanctions.org), consolidated targets
  export, retrieved on the date recorded in this run's manifest."
- **Known limitation:** aggregation quality varies by upstream source; OpenSanctions
  does not itself claim to be authoritative or complete.

### DoD Section 1260H list (Chinese military companies)
- **Provider:** U.S. Department of Defense, under Section 1260H of the William M.
  ("Mac") Thornberry National Defense Authorization Act for Fiscal Year 2021 (Public
  Law 116-283).
- **License:** U.S. Government work — not subject to copyright in the United States
  (17 U.S.C. § 105).
- **How it's ingested:** unlike NSF/OpenSanctions, this is a small (~200-entity),
  annually-updated static list whose primary source is a Federal Register PDF notice,
  not machine-native data — building streaming/PDF-parsing infrastructure for it
  wouldn't be proportional to its size (`docs/requirements.md`'s data source table
  flags it as "not machine-native" for exactly this reason). It ships as a hand-curated
  snapshot bundled with the package
  (`entity_screening/screening/data/dod_1260h.json`), compiled from OpenSanctions'
  `us_dod_chinese_milcorps` source artifact — itself compiled from DoD's official
  releases — filtered to currently-active designations and deduplicated; see that
  file's own `provenance` field for the exact compilation method and source URLs.
- **Attribution:** "Source: U.S. Department of Defense, Section 1260H list (Public Law
  116-283); compiled via OpenSanctions (opensanctions.org). Snapshot dated in this
  run's manifest under `dod_section_1260h`."
- **Known limitation:** static snapshot, not a live feed — the real list is updated
  roughly annually (and has grown substantially between updates), so this needs
  periodic manual re-curation from the same source rather than an automatic refresh.
  Being on this list is a DoD designation under Section 1260H, not a sanction, export
  control, or other legal restriction in itself.

## Sources reserved for V2/V3 (not yet ingested)

Documented here for completeness so attribution terms are settled before the code
that needs them is written — GLEIF Golden Copy (CC0, per GLEIF's data policy),
Section 117 dashboard (U.S. Government work), OpenAlex (CC0), and the Seven Sons seed
list (curated/manual, cite ASPI's public reporting as the basis, not scraped tracker
data) — sequenced into V3 alongside OpenAlex per `docs/requirements.md` Section 12.

## General policy

- Every run's manifest (`data/processed/runs/<run_id>/manifest.json`) records exactly
  which snapshot of each source was used and when — see `docs/methodology.md`.
- No dataset here is used for anything beyond the non-commercial, educational purpose
  stated in `docs/requirements.md` Section 1. Re-verify current license terms at each
  provider's own page before any other use, especially before any commercial or
  redistribution use — the summaries above are a snapshot, not a substitute for the
  source's own current terms.
