# Step 5 — Restricted-party screening

*Plan as approved via Claude Code plan mode, 2026-09-14. Historical record — read
`git log` for what actually shipped.*

---

## Context

`docs/use-case-02-restricted-party-screening.md` (approved) established that step 5's
real scope is restricted-party screening (RPS) only — a name-against-list match,
structurally close to the existing `ConcernTie` mechanism — not export-control
jurisdiction/classification/licensing, which stays out of scope permanently (a
judgment call for a trained export control officer, not this system). Two decisions
from that review were binding:

1. **First cut covers all three clean-fit triggers**, not a narrower slice: Foreign
   Person hire, visiting scholar, and purchasing/financial. Purchasing is included
   from day one specifically so the new "screenable party" type is designed against a
   case-shaped trigger (hire) *and* a non-case-shaped one (purchasing) together,
   rather than risk re-deriving `Case`'s shape from only case-like examples and
   needing a redesign later — the same mistake `docs/requirements.md` §9c already
   diagnosed once.
2. **OFAC-embargoed-country screening is explicitly out of scope**, not a silent gap
   — it's a country-of-nationality gate, a different legal test than restricted-party
   name-matching, and must not be implied as "handled" by this work.

## Real-data research done before designing this

**What "restricted-party screening" actually checks, confirmed against the live
data.** The spec left open whether the BIS Entity List, BIS Unverified List, and
State Department Nonproliferation Sanctions are already inside the OpenSanctions
consolidated file this project already downloads. Resolved with real data:

- OpenSanctions' `default` collection (the collection `targets.simple.csv` bulk-exports
  — the exact file `entity_screening/ingestion/opensanctions.py:OpenSanctionsTargetsIngester`
  already reads) includes `us_trade_csl` — the U.S. government's own official
  Consolidated Screening List, a single merged database Commerce/State/Treasury
  publish jointly.
- Downloaded the real `us_trade_csl` targets file directly
  (`data.opensanctions.org/datasets/latest/us_trade_csl/targets.simple.csv`, 24,204
  rows) and inspected its real `program_ids` column. Confirmed present:
  `US-BIS-DPL` (Denied Persons), `US-BIS-EL` (**Entity List**), `US-BIS-UVL`
  (**Unverified List**), `US-BIS-MEU` (Military End-User, a bonus), `US-AECA-DEBARRED`
  (AECA Debarred Parties), `US-DOS-ISN` (**State Dept Nonproliferation Sanctions**).
- Combined with the OFAC SDN List and State Dept Foreign Terrorist Organizations list
  (already separately confirmed as direct `default`-collection members), all seven
  restricted-party lists the real TAMU manual named are accounted for through the
  existing, unmodified `OpenSanctionsList`/`OpenSanctionsTargetsIngester` path.
  **No new curated list file was needed** — unlike step 4 or DoD 1260H.
- The project's bundled demo fixture (`tests/fixtures/demo_opensanctions_targets.csv`)
  was checked directly and already contains 22 real CSL-sourced rows, including
  "Shenzhen Huada Jiutianke Technology Co., Ltd." (`US-BIS-EL`) — no fixture update
  was needed either.

**Operational grounding**, from TAMU's Export Control Compliance Program Manual: a
Foreign Person hire's restricted-party screening covers the person, their affiliated
institution/organization going back five years, and any personal/professional
references provided — one trigger event produces multiple independently-screened
parties, not one. This shaped the two-level type design.

## What was built

1. **`entity_screening/screening/rps_schema.py`** (new module) — `ScreeningTrigger`,
   `PartyKind`, `ScreeningEvent`, `ScreeningParty`, `ScreeningMatch`,
   `ScreeningDisposition`. Deliberately its own module, not `common/schema.py`, and
   its own `Screening*` naming family, not `ScreeningRequest`/`ScreenableParty`/
   `RestrictedPartyHit`/`PartyScreeningAction` as originally drafted — resolved in
   review to one consistent prefix, with `ScreeningParty` (not the reviewed
   `ScreeningSubject`) to avoid colliding with `common/schema.py`'s real `Subject`
   type. `ScreeningEvent.synthetic` carries the same "no real PII by construction"
   guard as `Subject`/`Declaration`. `RPS_OBSERVATION_ALLOWED_FIELDS` in this module
   guards `ScreeningMatch`'s field set the same way `common/schema.py`'s
   `_OBSERVATION_GRAPH_ALLOWED_FIELDS` guards `Finding`/`ConcernTie` — kept as its own
   dict here specifically so `common/schema.py` never has to import from `screening/`.
2. **`entity_screening/screening/rps_screen.py`** (new) — `screen_party`/
   `screen_parties`, matching logic deliberately *not* imported from
   `reconciliation/discover.py:_screen_name_against_concern_lists` despite the close
   resemblance, since `reconciliation/` already imports from `screening/` and the
   reverse import would invert this project's established layering.
3. **`entity_screening/screening/rps_store.py`** (new) — DuckDB persistence,
   mirroring `case/store.py`'s save/load conventions. Four new tables in
   `common/storage.py`'s `SCHEMA_DDL`: `screening_events`, `screening_parties`,
   `screening_matches`, `screening_dispositions`.
4. **`entity_screening/screening/rps_service.py`** (new) — orchestration
   (`create_event`, `screen_event`, `record_disposition`), mirroring `case/service.py`'s
   role: reason-code validation via a new `RPS_DISMISS_REASON_CODES`/
   `RPS_ESCALATION_REASON_CODES` vocabulary in `case/vocab.py`. Only screens against
   `OpenSanctionsList`, never `DoD1260HList` — DoD 1260H is a distinct HB 127/Epic D
   concern list, not one of the seven restricted-party lists this use case is about.
5. **`entity_screening/common/manifest.py`** — `ScreeningEventManifest`, mirroring
   `ReconciliationManifest`'s "current state, per-event, overwritten on re-screen"
   shape. No new curated-snapshot manifest (unlike `AdversaryListManifest`) — this is
   provenance for *when* the existing OpenSanctions data was consulted.
6. **`entity_screening/api/rps_routes.py`** (new) — one creation route per trigger
   (`POST /screening-events/hire|visiting-scholar|purchasing`), `POST
   /screening-events/{id}/screen`, `GET /screening-events/{id}`, `POST
   /screening-events/{id}/matches/{match_id}/disposition`, `GET
   /screening-events/reason-codes`. Gated by the existing `_require_action_secret`
   dependency, registered in `api/main.py`. A hire/visiting-scholar event's `case_id`
   is a display-only join key to an HB 127 case — confirmed in review, no worksheet
   indicator built this pass.
7. **`entity_screening/cli.py:validate`** — extended with the same `synthetic=False`-
   rejection check for `ScreeningEvent` as `Subject`/`Declaration`, and the same
   allowed-fields/forbidden-token check for `ScreeningMatch` as `Finding`/`ConcernTie`
   (via the new `RPS_OBSERVATION_ALLOWED_FIELDS`).
8. **`tests/test_rps.py`** (new, 11 tests) — pure-matching tests against a real
   extracted BIS Entity List row (`tests/fixtures/sample_us_trade_csl.csv`, one row
   verbatim from the real `us_trade_csl` download above), a negative-space test
   proving no OFAC-country filtering occurs across all five comprehensively-embargoed
   countries, storage/service round-trip tests for all three triggers, and
   end-to-end API tests via `TestClient`.

## Explicit scope boundary — what stayed out, and how it's documented

- **OFAC-embargoed-country screening**, per the binding decision: `ScreeningParty.country`
  is captured for display/evidence only and never checked against any country list.
  Documented in `screening/rps_schema.py`'s module docstring (repeated in
  `rps_screen.py`), in `docs/data_sources.md`'s new entry, and in
  `docs/use-case-02-restricted-party-screening.md` — the same "not used, documented"
  treatment step 4 gave Texas Executive Order GA-48. Proven, not just asserted, by
  `test_country_is_never_a_screening_gate`.
- Export-control jurisdiction, classification, and licensing — permanently out of
  scope, not deferred (use-case-02 §1, "problem (2)").
- Research agreements, international shipments, travel — no data model exists for
  any of them and none was proposed.
- Folding RPS matches into the existing HB 127 worksheet view — a separate
  `screening-events` view was built instead; a shared worksheet is a follow-on
  question.
- The generic closed-case/closed-event re-sweep trigger — same "Detection is not
  manual" cross-cutting requirement deferred from step 4, not rebuilt narrowly here.

## Verification

- `pytest -q` — 294 passed (283 pre-existing + 11 new).
- `python -m entity_screening.cli validate` — passed, including the new
  `ScreeningEvent`/`ScreeningMatch` guards.
- Real-data verification: a genuine BIS Entity List row (`US-BIS-EL`,
  "Taiyuan Jinke Semiconductor Technology Co., Ltd.") produces a `ScreeningMatch`
  whose evidence carries the real government program id, confirmed by
  `test_screen_party_matches_the_real_bis_entity_list_row`.
- `docker` CI job's corpus-path parity assertion untouched — this work doesn't touch
  the batch path or the existing HB 127 case path.
