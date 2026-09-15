# V2 Epic C — GLEIF ownership graph and foreign-control flagging

*Backfilled 2026-09-15, retroactively, per the known gap logged in this
directory's `README.md`. This is **not** a recovered plan-mode transcript —
that record was never copied here and the pre-approval design conversation
itself is genuinely gone. What follows is reconstructed from the actual
shipped commit (`git show 0f8bf276be8d6e0d44c61743b2797daa6211332b` — see the
`README.md` update alongside this file for why that hash, not the
`3c07677` originally cited, is the one that resolves) and the current
`docs/architecture.md` / `docs/data_sources.md`. Treat this the same as this
directory's other historical records for what shipped; treat anything framed
below as "the plan called for" as inferred from the commit message's own "per
the approved plan" language, not independently verified against a document
that no longer exists.*

---

## Context

Requirements.md's Epic C: a corporate parent/subsidiary ownership graph, so a
resolved entity whose ultimate parent is registered in a different
jurisdiction than the entity itself can be flagged as a foreign-control
observation. This is V2 — the commit explicitly scoped itself to Epic C only,
leaving Section 117 foreign-funding disclosure and the Seven Sons / BIS
entity-of-concern list for V3, matching the phased roadmap in
`requirements.md` §12.

Committed 2026-09-01 (Tue Sep 1 09:52:35 2026 -0500), same day as the Section
117 cross-check and the V3 OpenAlex layer — all three land within the V1→V3
push documented in `docs/plans/README.md`'s index around that date.

## Architecture, as shipped

- New `entity_screening/ownership/` package, deliberately **not** a
  `BaseIngester` subclass and not living under `ingestion/`: at ~3.4M GLEIF
  Level 1 rows, materializing individual `SourceRecord` objects the way
  NSF/OpenSanctions/1260H do would be disproportionate. `ingest.py` bulk-loads
  via DuckDB's `read_csv_auto` directly; `match.py` resolves a canonical name
  to an LEI via SQL blocking plus the existing `resolution/matcher.py` scorer
  (reused, not reimplemented); `graph.py` walks the parent/subsidiary chain
  via a recursive CTE; `flagging.py` ties the two together into a
  `ForeignControlFlag`.
- `pipeline.enrich_ownership(run_id, ...)` is a separate, explicit step from
  `run_screening`, callable independently against an existing run — GLEIF is
  a shared reference dataset, not a per-run source. It never touches
  `scored_entities`; `rescore_run` loads persisted `ownership_flags` the same
  way it already loaded `screening_hits`.
- A new `GleifSnapshotManifest`, written into the run's own output directory
  (not just logged next to the mutable, disposable `gleif_lei`/
  `gleif_relationships` tables) specifically so a run's flags don't lose the
  ability to say which GLEIF download produced them once a later enrichment
  call, for any run, replaces those tables.
- `parent_chain()` returns an explicit `ParentChain(chain, truncated)` rather
  than a bare list, peeking one hop past `max_depth` internally, so "the
  chain is exactly this long" and "there's more we didn't check" are never
  confused with each other.
- New API endpoints, `POST /runs/{id}/ownership` and
  `GET /runs/{id}/ownership/{entity_id}`, for Epic C's "traversal depth and
  direction... queryable" acceptance criterion as an actual ad-hoc endpoint,
  not just a precomputed flag.

## Real-data verification (from the commit, cross-checked against `docs/data_sources.md`)

Two real bugs were found only by downloading and loading the actual GLEIF
files, not synthetic fixtures — exactly what a real-data acceptance criterion
is for:

- GLEIF's own documentation names fields `EntityStatus`, `EntityCategory`,
  `StartNode`, `EndNode`, `RelationshipType`, `RelationshipStatus`; the real
  CSV nests each one level deeper (`Entity.EntityStatus`,
  `Relationship.StartNode.NodeID`, etc.). Fixed in `ingest.py` and the test
  fixtures.
- GLEIF's "Concatenated Files" API (`leidata.gleif.org`) actually serves XML
  despite being described with the same LEI-CDF/RR-CDF terms as the CSV
  Golden Copy API (`goldencopy.gleif.org`) — now documented in
  `docs/data_sources.md` so this doesn't get rediscovered the hard way again.

Real-data timing pass: the actual ~3.4M-record Level 1 file (~500MB) loaded
in ~50s; the ~259K-row filtered Level 2 file in ~3s.
`resolve_entity_to_lei`'s blocking query ran 26–106ms per lookup against the
full real dataset — `block_size=3` (carried over from OpenSanctions' scale)
confirmed adequate, no widening needed.

Two genuine matcher limitations surfaced at GLEIF's scale, both documented in
`docs/data_sources.md` as properties of the shared matcher rather than
anything GLEIF-specific:

- Toyota's actual parent entity has no LEI at all (voluntary registration —
  a real coverage gap), so a name-resolution query for it falls back to a
  much weaker, unrelated fuzzy match.
- "Apple Inc" and the real, unrelated GLEIF-registered "Apple Ltd" collide
  under corporate-suffix normalization at confidence 1.0 — the same
  normalization that correctly merges true variant names can incorrectly
  merge two different real companies sharing a base name.

A status-computation bug was also fixed in `output/export.py` and
`api/dto.py`: a foreign-control flag with no screening-list hit was being
reported as `"no_hit"`, silently hiding a genuine finding.

## Out of scope

- Section 117 foreign-funding disclosure cross-check — shipped the same day,
  as its own commit/plan (`docs/plans/2026-09-01-section-117-foreign-gift-disclosure-cross-check.md`).
- Seven Sons of National Defence / BIS entity-of-concern seed list — V3.

## Verification, as reported in the commit

100 total tests passing (35 new), verified against both the FastAPI
`TestClient` and a real running uvicorn server, plus the Streamlit UI
end-to-end via headless `AppTest`. (This session did not independently
re-run that suite; it's recorded here as reported, not re-verified, since
the point of this document is provenance for the design decisions and the
real-data findings, both of which were independently cross-checked against
current `docs/architecture.md`/`docs/data_sources.md` above.)
