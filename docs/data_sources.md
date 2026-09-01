# Data Sources: License & Attribution

Per `docs/requirements.md` Section 10 ("License compliance: attribution and license
terms tracked per source and surfaced in output, not just in a README") and Epic I.
Every exported row already carries its source dataset name via the evidence trail
(`entity_screening/output/export.py`); this document is the canonical statement of
each source's terms.

## Sources used (V1 through V3)

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

### GLEIF Golden Copy (Level 1 LEI-CDF + Level 2 RR-CDF)
- **Provider:** Global Legal Entity Identifier Foundation (GLEIF).
- **License:** CC0 1.0 Universal (public domain) — no attribution legally required,
  no commercial/redistribution restriction. Attributed anyway below as good practice.
- **Attribution:** "Data: GLEIF (gleif.org) Golden Copy files, snapshot dated in this
  run's ownership manifest (`data/processed/runs/<run_id>/ownership/manifest.json`)."
- **Where to actually download it — this matters, it's easy to get wrong:** use
  `https://goldencopy.gleif.org/api/v2/golden-copies/publishes/lei2/latest.csv` (Level 1)
  and `.../rr/latest.csv` (Level 2). GLEIF's separately-documented "Concatenated
  Files" API (`leidata.gleif.org/api/v1/concatenated-files/...`) describes itself with
  the same "LEI-CDF"/"RR-CDF" format names but actually serves **XML**, not CSV, at
  that endpoint — confirmed by downloading it during this feature's build. Only the
  Golden Copy host serves the flattened CSV `entity_screening/ownership/ingest.py`
  expects.
- **Column names — verified against a real download, not just GLEIF's docs:** GLEIF's
  own documentation describes fields as `EntityStatus`, `EntityCategory`, `StartNode`,
  `EndNode`, `RelationshipType`, `RelationshipStatus`. The real CSV nests each one
  level deeper: `Entity.EntityStatus`, `Entity.EntityCategory`,
  `Relationship.StartNode.NodeID`, `Relationship.EndNode.NodeID`,
  `Relationship.RelationshipType`, `Relationship.RelationshipStatus`. This was caught
  by downloading and inspecting the actual ~3.4M-row file, not by reading GLEIF's
  documentation.
- **Real-data performance (measured, not estimated):** loading the full Level 1 file
  (~3.4M records, ~500MB) into DuckDB took ~50s; the Level 2 file (filtered to ACTIVE
  `IS_DIRECTLY_CONSOLIDATED_BY`/`IS_ULTIMATELY_CONSOLIDATED_BY` rows) took ~3s and
  yielded ~259K rows. The SQL-blocked LEI-matching query
  (`ownership/match.py:resolve_entity_to_lei`, `block_size=3`) ran in 26–106ms per
  lookup against the full real dataset — confirming the 3-character block width
  carried over from OpenSanctions' scale is adequate at GLEIF's scale too; no widening
  needed.
- **Known limitations (observed against real data, not hypothetical):**
  - **LEI registration is voluntary — coverage is genuinely incomplete**, including
    for large, well-known companies. Toyota Motor Corporation's actual Japanese parent
    entity does not appear in GLEIF under that name at all (only subsidiaries like
    Toyota Motor Credit Corporation and Toyota Motor North America do) — a
    name-resolution query for it falls back to a much weaker, unrelated fuzzy match
    (an Indonesian joint venture, "TOYOTA-ASTRA MOTOR," at exactly the default 0.80
    threshold) rather than finding nothing, which is a real precision risk worth
    knowing about before trusting a borderline-confidence ownership match.
  - **Corporate-suffix normalization can conflate distinct real entities.** "Apple
    Inc" and the real, unrelated GLEIF-registered "Apple Ltd" both normalize to the
    same suffix-stripped string ("apple") and matched at confidence 1.0 in testing —
    the same normalization behavior that correctly merges "Acme Inc."/"Acme
    Corporation" as the same entity can incorrectly merge two different real
    companies that happen to share a base name. This is a property of
    `resolution/matcher.py`'s shared normalization (used for every source, not just
    GLEIF), surfaced concretely here because GLEIF's ~3.4M entities create far more
    opportunity for this collision than OpenSanctions or DoD 1260H's smaller lists.
    Consider a higher `threshold` for ownership-specific matching than for
    screening-list matching if this risk matters for a given use — it's the same
    user-configurable parameter either way.

### Section 117 foreign gift & contract disclosures

- **Provider:** U.S. Department of Education, under Section 117 of the Higher
  Education Act of 1965, as amended.
- **License:** U.S. Government work — not subject to copyright in the United States
  (17 U.S.C. § 105).
- **Attribution:** "Source: U.S. Department of Education, Section 117 foreign gift and
  contract disclosures (foreignfundinghighered.gov). Snapshot dated in this run's
  manifest under `section_117_foreign_funding_disclosure`."
- **Where it was verified:** the legacy bulk-download file,
  `Sec117PublicRecordsCompleteFeb2025.xlsx` at `fsapartners.ed.gov` — 117,152 rows, 18
  columns. **Known gap:** the portal relaunched in January/February 2026 with, per
  ED's own press release, "11 additional data elements"; the new dashboard is a
  JS-rendered SPA this project's tooling couldn't access directly, so this was
  verified against the legacy file, not the current post-relaunch download.
  Re-verify the current download URL and schema before trusting a fresh download —
  same category of caution as GLEIF's CSV-vs-XML trap above.
- **Self-reported; coverage gaps possible** (per `docs/requirements.md`'s data-source
  table) — only ~4.75% of real rows in the verified file name a specific foreign
  entity at all (embassies, cultural missions, sovereign funds); the rest report only
  a country, with nothing to fuzzy-match. Real institution-name matching (School Name
  vs. NSF's often-legal/governing-board awardee name) needed a dedicated
  normalization step — see `docs/methodology.md`'s known limitations.
- **Real end-to-end run against the actual current bulk file, cross-checked against
  the real bundled DoD 1260H list and a real full OpenSanctions pull (455MB,
  ~1.22M rows)** — not hypothetical: all 117,152 real rows ingest cleanly (zero
  errors); of 878 unique named foreign entities, 3 match the real DoD 1260H list
  (including "Huawei Technologies Co., Ltd." verbatim) and 164 clear the default
  0.80 threshold against real OpenSanctions entries, among them genuinely useful
  real findings (Beijing Institute of Technology, Dalian University of Technology,
  Xidian University, PetroChina, China National Offshore Oil, China Petrochemical).
  **A real precision caveat surfaced by this same run:** 43 of those 164 matches are
  against OpenSanctions `Security` (bond/ISIN) records, 20 of them a single generic
  name ("Ministry Of Finance") that many different countries' government bond
  issuers share in OpenSanctions' consolidated dataset — a real disclosure naming a
  foreign "Ministry of Finance" will candidate-match several unrelated countries'
  bond securities at confidence 1.0. This is visible and inspectable (the hit's
  evidence carries the matched entry's own `entity_type` and source fields, so a
  reviewer sees "Security"/ISIN immediately), not hidden — worth knowing before
  treating a `Ministry Of Finance`-named disclosure's hit count at face value, same
  spirit as GLEIF's documented Apple Inc./Apple Ltd. collision above.

### OpenAlex (bibliometric affiliation layer, Epic E)

- **Provider:** OpenAlex (a project of OurResearch).
- **License:** CC0 1.0 Universal (public domain) — no attribution legally required,
  attributed anyway as good practice.
- **Attribution:** "Data: OpenAlex (openalex.org), queried live via its REST API on
  the date recorded in this run's `BibliometricSnapshotManifest`
  (`data/processed/runs/<run_id>/bibliometric/manifest.json`)."
- **Access pattern (per `docs/requirements.md` Section 8):** the free, targeted REST
  API (`api.openalex.org`), not the 660+GB full bulk snapshot — confirmed live and
  via OpenAlex's own current docs that **no API key is required** for the free tier
  (100,000 credits/day, 100 req/sec; list/search calls cost 10 credits, singleton
  lookups 1). This directly contradicts a stale, incorrect claim circulating online
  (a Google Groups post) that a key became mandatory in February 2026 — verified by
  fetching OpenAlex's own current docs directly, not the secondhand claim. A
  `mailto` parameter is still sent for the "polite pool" (more consistent response
  times), configurable via `--openalex-contact-email` / the UI's contact-email field.
- **Known limitation, OpenAlex's own stated figure (surfaced inline with every
  bibliometric result in the UI, not just here):** ">98% precision and >90% recall
  for most academic institutions. But across the full corpus of all scholarly works
  in OpenAlex (500M+), that's still millions of errors." (OpenAlex's own blog).
- **Known limitation, confirmed with a real, not hypothetical, example while
  building this:** searching a real NSF PI ("Andrew Felton", Montana State
  University) — even after narrowing server-side to authors ever affiliated with
  that exact institution — returned three distinct OpenAlex author records for what
  is very likely one real person: two of the three share an identical ORCID (a
  genuine, unmerged duplicate-author-record issue in OpenAlex's own data), and the
  third has no ORCID and could be a genuinely different person. This project's
  author-disambiguation step (`entity_screening/bibliometric/author_resolve.py`)
  treats a shared ORCID as one identity and surfaces a true open tie as multiple
  candidates rather than silently guessing — but the underlying ambiguity in
  OpenAlex's own data is real, not something this project's logic invented or can
  fully resolve on its own.
- **Known limitation:** `enrich_bibliometric` only re-derives PIs from NSF award
  records that have both `piFirstName` and `piLastName` populated; records missing
  either are skipped for bibliometric purposes (they're still screened normally by
  every other epic).

### Seven Sons of National Defence

- **Provider:** no dedicated provider for this project — covered entirely via
  OpenSanctions' consolidated list (see above), which already carries all seven
  real institutions (Beihang University, Beijing Institute of Technology, Harbin
  Engineering University, Harbin Institute of Technology, Nanjing University of
  Aeronautics and Astronautics, Nanjing University of Science and Technology,
  Northwestern Polytechnical University), several explicitly citing NDAA Section
  1286 as their designation basis — confirmed by grepping the real, full
  OpenSanctions download directly, not assumed.
- **Deliberately no dedicated curated list here**, unlike DoD 1260H: DoD 1260H
  needed its own bundled snapshot because nothing else in this project's sources
  carried it; the Seven Sons don't need one because OpenSanctions already does.
  Building one anyway would duplicate coverage that already exists.
- **Known limitation — the trade-off from that choice, stated plainly:** a static,
  bundled curated file (like DoD 1260H's) can't silently lose coverage between
  updates; relying on OpenSanctions' aggregation instead means this project has no
  independent fallback if a future OpenSanctions snapshot ever drops or re-labels
  these seven designations. `tests/test_screening_seven_sons.py` is a regression
  guard against the *matching logic* breaking, not against OpenSanctions itself
  changing what it carries.

## Sources reserved for V3

None remaining — Epic E (OpenAlex) and the Seven Sons item above complete V3 per
`docs/requirements.md` Section 12's roadmap. Epic J (LLM-grounded explanations) and
DuckDB VSS semantic-abstract matching remain deliberately deferred, V3-adjacent
follow-ups, not part of any currently-scheduled phase.

## General policy

- Every run's manifest (`data/processed/runs/<run_id>/manifest.json`) records exactly
  which snapshot of each source was used and when — see `docs/methodology.md`.
- No dataset here is used for anything beyond the non-commercial, educational purpose
  stated in `docs/requirements.md` Section 1. Re-verify current license terms at each
  provider's own page before any other use, especially before any commercial or
  redistribution use — the summaries above are a snapshot, not a substitute for the
  source's own current terms.
