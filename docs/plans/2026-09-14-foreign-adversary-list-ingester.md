# Step 4 — Foreign-adversary-country list ingester

*Plan as approved via Claude Code plan mode, 2026-09-14. Historical record — read
`git log` for what actually shipped.*

---

## Context

§51B.001 defines "foreign adversary" as a country meeting *either* of two tests: (A)
identified by the DNI as a national-security risk in at least one of the three most
recent Annual Threat Assessments (ATAs), or (B) designated by the Texas governor
after consulting the DPS director. `country_on_adversary_list: bool|None` and
`adversary_list_version: str|None` were already stubbed on both `DiscoveredAffiliation`
and `ConcernTie` (`common/schema.py`), hardcoded to `None` at three call sites in
`reconciliation/discover.py`, each commented "set in step 4." `ReconciliationManifest`
already had an `adversary_list_version` field and its `.create()` classmethod already
accepted it — nothing called it with a real value. The storage layer (`case/store.py`),
export (`case/export.py`), and the Streamlit UI (`app.py`) already handled the
three-state distinction correctly ("not yet checked" vs. `True`/`False`) — a small,
well-bounded slice of new work inside an otherwise-finished pipe.

## Real-world research done before designing this

**Path A — DNI Annual Threat Assessments.** Downloaded and read the actual unclassified
PDFs of all three ATAs making up the current rolling window:

| Year | Published | URL | Structure |
|---|---|---|---|
| 2024 | March 11, 2024 | `archive.dni.gov/.../ATA-2024-Unclassified-Report.pdf` | Dedicated **"STATE ACTORS"** chapter (p.7): China (p.7), Russia (p.14), Iran (p.18), North Korea (p.21) |
| 2025 | March 25, 2025 | `dni.gov/.../ATA-2025-Unclassified-Report.pdf` | Dedicated **"MAJOR STATE ACTORS"** chapter (p.9): China (p.9), Russia (p.16), Iran (p.22), North Korea (p.26) |
| 2026 | March 18, 2026 | `odni.gov/.../ATA-2026-Unclassified-Report.pdf` | **No dedicated state-actor chapter** — reorganized around themes. Same four countries named explicitly in the REGIONAL CHALLENGES section (p.19–20): *"China, Russia, Iran, and North Korea view the U.S. as a strategic competitor and potential adversary..."* |

**Real, load-bearing finding:** the 2026 edition dropped the "one chapter, four
countries" structure the 2024/2025 editions had — a TOC-heading parser would have
silently produced nothing for the most recent document in the window. **Consequence:**
this ships as a hand-verified, versioned, static snapshot (`dod_1260h.json`'s existing
pattern), re-derived and re-verified by a human roughly annually, not an unattended
PDF parser.

**Decision (recorded, not re-litigated per case):** the 2026 ATA's "strategic
competitor and potential adversary" framing satisfies §51B.001(A)'s "identified... as
posing a national security risk" on the same footing as 2024/2025's literal chapter
titles.

**Path B — gubernatorial designation.** Confirmed by reading HB 127's enrolled bill
text directly (`capitol.texas.gov/tlodocs/89R/billtext/html/HB00127F.HTM`):
§51B.001(B) has **no publication or recordation requirement at all**. The closest real
artifact found, Texas Executive Order GA-48 (Nov. 2024, naming China/HK/Macau, Cuba,
Iran, North Korea, Russia, and the Maduro regime/Venezuela), predates HB 127's
Sept. 1, 2025 effective date and was issued under separate authority for an unrelated
stated purpose.

**Decision: GA-48 is not used.** Path B ships empty — only the four DNI-ATA countries
ship, each `"basis": ["dni_ata"]`. The `basis` mechanism is built so a real
gubernatorial designation is trivial to add later.

**Verification done, recorded:** searched specifically for any gubernatorial
designation issued after HB 127's effective date citing §51B.001(B) directly. Found
none. Two secondary sources disagreed with each other in that search — one naming the
same four DNI-ATA countries, a student newspaper (*Daily Toreador*, Sept. 17, 2025)
attributing a six-country claim "to the bill" that this project's own direct reading of
the enrolled statute does not support (it hardcodes no country list at all). Recorded
as a checked dead end, not a silent gap.

## What was built

1. `entity_screening/screening/data/adversary_countries.json` — the curated snapshot,
   mirroring `dod_1260h.json`'s shape: `list_version`, `derived_at`, a `provenance`
   field recording both decisions and the verification search above, and per-country
   `citations` (title/url/page/note) for each of China, Russia, Iran, North Korea.
2. `entity_screening/screening/adversary_list.py` — `AdversaryCountryList` (frozen
   dataclass) + `load_adversary_list()`. `.contains(country_code)` returns `None` only
   when the code itself is unresolvable; normalizes ISO 3166-2 subdivision codes (e.g.
   GLEIF's occasional `"US-DE"`) to their country prefix before matching.
3. `entity_screening/common/manifest.py` — `AdversaryListManifest`, per the Sept 6
   plan's reserved shape. Not a per-run written file (the list is a static bundled
   artifact, not a live download, the same reason `dod_1260h.json` has none); instead
   loaded from the curated JSON's own provenance via `.from_adversary_list()`.
4. `entity_screening/reconciliation/discover.py` — the three previously-`None` call
   sites wired to real values: `_aggregate_own_affiliations`/`discover_from_publications`
   takes a new required `adversary_list` parameter and looks up each discovered
   institution's `country`; `tie_from_ownership` takes the same parameter and looks up
   the resolved parent's `parent_jurisdiction`; `ties_from_own_affiliations` takes no
   new parameter at all — it inherits `country_on_adversary_list`/
   `adversary_list_version` from each `DiscoveredAffiliation`, already resolved
   upstream, rather than a redundant second lookup.
5. `entity_screening/pipeline.py:reconcile_case` — loads the bundled list once (new
   `adversary_list_file` parameter, defaulted, mirroring `dod_1260h_file`), threads it
   into both discovery calls, and passes its `list_version` into
   `ReconciliationManifest.create(...)` — the one call site that had been omitting an
   already-accepted parameter. `discovery_sources` now includes
   `"foreign_adversary_countries"`.
6. `entity_screening/cli.py:validate` — asserts the curated file loads, every
   `iso_code` is a valid ISO 3166-1 alpha-2, and every country has at least one
   citation.
7. `tests/test_adversary_list.py` (new) — loader tests (four-country set, `True`/
   `False`/`None` behavior, ISO 3166-2 normalization), `AdversaryListManifest`
   derivation, and end-to-end wiring tests for `discover_from_publications` and
   `tie_from_ownership` against a known adversary country (`"CN"`) and a known
   non-adversary country (`"US"`), using a small fabricated GLEIF+1260H fixture for the
   ownership path (mirroring `tests/test_ownership_match.py`'s existing fixture
   convention) — not a shipped fixture.

## What was deliberately not built

- **The automated closed-case re-sweep/detection trigger.** `ReconciliationManifest`
  is already a per-case "current state" file (`case_dir()` keyed by `case_id`,
  overwritten on every reconcile) — once this shipped, every case's manifest carries
  the `adversary_list_version` it was last reconciled under, with no new DuckDB schema
  needed for a future sweep to check staleness against. A case still in
  `DISCOVERY`/`WORKSHEET`/`ADJUDICATION` self-heals on the next manual reconcile
  (already idempotent/current-state). A **closed** case does not auto-reopen on a
  version bump — `case/service.py:reopen_case` already does the right thing generically
  when invoked, but nothing decides *which* closed cases to reopen. That trigger is the
  pre-existing, separately-scoped "Detection is not manual" requirement (use-case doc
  §5), explicitly cross-cutting every reference source (GLEIF, 1260H, OpenSanctions,
  *and* the adversary list) — not something to build once, narrowly, for this source
  alone.
- Steps 5 (export-control/restricted-party screening) and 6 (COI/NSPM-33 disclosure
  reuse) — untouched, per use-case doc §12's own sequencing.
- Any UI/API surface changes — `app.py`, `case/export.py`, and `case/store.py` already
  rendered/persisted the three-state distinction correctly before this plan; they just
  started receiving real values instead of `None`.
- A waiver/"low-risk circumstances" mechanism (§51B.151(b)'s council-determined
  framework) — nothing to build until that framework is published.

## Verification

- `pytest -q` — 283 passed (277 pre-existing + 6 new).
- `python -m entity_screening.cli validate` — passed, including the new adversary-list
  checks.
- End-to-end: reconciled the demo case. Finding/tie counts unchanged (2 findings, 1
  tie) — confirmed, not assumed. The demo's own ownership tie (NIO Inc., Cayman
  Islands) correctly resolves `country_on_adversary_list=False` (not `None`); the
  demo's two bibliometric findings (China-based institutions) correctly resolve
  `True`. `ReconciliationManifest.adversary_list_version` now carries the real curated
  version, confirmed by reloading the written manifest file from disk. Exported the
  investigative file and confirmed the raw JSON payload carries the real values
  end-to-end.
- `docker` CI job's corpus-path parity assertion untouched (batch path not touched).

## Correction (2026-09-17, Phase 6 remediation, M22)

Item 3 above claims `AdversaryListManifest` is "loaded from the curated
JSON's own provenance via `.from_adversary_list()`, giving the rest of
the codebase (export, worksheet UI, docs) one typed place to read the
derivation from." That was never true in production: the class and its
classmethod were constructed only by their own unit test
(`tests/test_adversary_list.py`), never by `case/export.py`, the
worksheet UI, or `cli.py validate`. Confirmed dead by direct grep before
removal, not assumed. Removed in Phase 6 as dead code — see
`docs/plans/2026-09-17-phase-6-ops-performance-hygiene.md`'s M22
section for the verification and removal record.
