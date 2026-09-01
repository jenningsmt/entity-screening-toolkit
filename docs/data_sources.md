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

## Sources reserved for V2/V3 (not yet ingested)

Documented here for completeness so attribution terms are settled before the code
that needs them is written — GLEIF Golden Copy (CC0, per GLEIF's data policy),
Section 117 dashboard (U.S. Government work), DoD Section 1260H list (U.S. Government
work, Federal Register notice), OpenAlex (CC0), and the Seven Sons seed list
(curated/manual, cite ASPI's public reporting as the basis, not scraped tracker data).

## General policy

- Every run's manifest (`data/processed/runs/<run_id>/manifest.json`) records exactly
  which snapshot of each source was used and when — see `docs/methodology.md`.
- No dataset here is used for anything beyond the non-commercial, educational purpose
  stated in `docs/requirements.md` Section 1. Re-verify current license terms at each
  provider's own page before any other use, especially before any commercial or
  redistribution use — the summaries above are a snapshot, not a substitute for the
  source's own current terms.
