# Phase 4 — Reconciliation evidence correctness

## Context

`Claude outputs/monops-remediation-strategy-2026-09-15.md` sequences the
2026-09-15 pre-ship review into six phases. Phases 1-3 shipped and
deployed. Phase 4 is next: every stated fact on a `Finding`/`ConcernTie`
must be *computed*, not a constant standing in for a computation nobody
did — the schema layer's fact/judgment discipline only holds if every
field it lets through is actually derived from evidence.

**This is the one phase the strategy doc explicitly allows to change demo
evidence.** Phases 1-3 all proved an empty content diff; Phase 4 does not
— `relationship_path`, `record_count`, and the recited sentence for the
demo's own ownership tie all become *more correct* (not different-by-bug),
and that's the point. One `DEMO_FIXTURE_VERSION` bump, done once, at the
end, after every item below is green against unit fixtures.

All line numbers below were re-read from the current tree on 2026-09-17
(post Phase 3 — `finding_id`/`tie_id` are already deterministic uuid5s;
nothing here touches how ids are generated, only what the observations
they identify actually say).

---

## 1. S15 first — close the allowlist gap before anything else adds fields under it

**Current state.** `entity_screening/common/schema.py`'s
`_OBSERVATION_GRAPH_ALLOWED_FIELDS` (lines 605-663) has entries for
`Finding`, `ConcernTie`, `DiscoveredAffiliation`, `DeclarationSearch`,
`NearestDeclared` — **no `ScreeningHit` or `ForeignControlFlag` entry**,
even though `ConcernTie` embeds both as `concern_list_evidence`/
`ownership_evidence`. `entity_screening/cli.py`'s `_cmd_validate`
(`_observation_graph_types`, lines 174-180) walks exactly the same five
types — the two embedded ones are invisible to `cli validate`. Neither
type's `evidence: dict[str, Any]` field is walked recursively against
`_FORBIDDEN_OBSERVATION_FIELD_TOKENS` (lines 670-683) at any level — the
forbidden-token check (cli.py lines 198-203) only inspects each
dataclass's own *field names*, never a dict's *keys* at runtime.
`tests/test_output_contract.py`'s `_walk_keys`-based check (lines 256-267)
strips `concern_list_evidence` out before walking — `ownership_evidence`
is not excluded (already walked today), only `concern_list_evidence` is.

**Fix.**
1. Add `"ScreeningHit"` and `"ForeignControlFlag"` entries to
   `_OBSERVATION_GRAPH_ALLOWED_FIELDS`, field sets copied from the
   dataclasses' actual current fields (`ScreeningHit`: lines 52-73;
   `ForeignControlFlag`: lines 91-119).
2. Add both to `cli.py`'s `_observation_graph_types` dict.
3. Add a recursive dict-key walker in `cli.py` (a `_walk_dict_keys`
   generator, same shape as the test's own `_walk_keys`) and call it
   against every `evidence` dict found on every `ScreeningHit`/
   `ForeignControlFlag` instance the validate command touches — this
   needs *fixture data* to walk (validate today is data-free structural
   checking of the dataclasses themselves; walking real `evidence` dict
   *contents* requires either the demo fixtures or a synthetic sample).
   Simplest: `cli validate` builds one demo `ScreeningHit`/
   `ForeignControlFlag` via the existing screening/ownership modules (or
   imports a tiny fixture) and walks its `evidence` keys — matching how
   the rest of `_cmd_validate` already validates the rubric/list registry
   against real, not empty, structures.
4. `test_output_contract.py`: remove the `concern_list_evidence`
   exclusion (line 260) so the recursive key-walk covers it too, and
   confirm nothing inside its nested `ownership_path` dict trips the
   forbidden-token check today (it shouldn't — `declared_employer_name`,
   `declared_employer_lei`, etc. are all clean).

**Tests.** `cli validate` fails today if pointed at a hand-built
`ScreeningHit`/`ForeignControlFlag` carrying a forbidden-token key nested
inside `evidence` (e.g. `evidence={"ownership_path": {"risk_note": "x"}}`)
— add this as a new validate-command test proving the recursive walk
actually descends, not just checks top-level keys. Confirm `cli validate`
and the full suite still pass once S15 lands alone, before anything else
in this phase adds new fields (S3 adds two to `ConcernTie` itself — must
land after S15's allowlist mechanism is proven to actually catch a
violation, or a mistake in those two new fields would ship silently).

---

## 2. S1 — ownership-tie evidence becomes a real traversal, by reusing the already-correct batch-path code

**Current state.** `entity_screening/reconciliation/discover.py`'s
`tie_from_ownership` (lines 241-354) calls `ultimate_parent(conn,
match.lei, max_depth=max_depth)` (line 273) — terminal LEIs only, no
path — then hard-codes `relationship_path=(match.lei, parent_lei)` (line
315), a fixed 2-tuple regardless of real hop count, and an `ownership_path`
evidence dict (lines 285-291) with no intermediate nodes.
`entity_screening/ownership/flagging.py`'s `flag_from_match` (lines 48-52,
body 72-123) is the already-correct batch-path equivalent: it calls
`parent_chain(conn, match.lei, direction="up", max_depth=max_depth)`
directly (never `ultimate_parent`), iterates every distinct real chain,
de-dupes by ultimate LEI, skips same-jurisdiction (not genuinely
"foreign") chains, and builds `full_path = (match.lei, *chain)` — the
real path, whatever its length. `compute_foreign_control_flag`
(`flagging.py` lines 21-27, body 40-45) is a thin resolve-then-delegate
wrapper around `flag_from_match`, confirmed dead in production (grep:
called only by 6 sites in `tests/test_ownership_flagging.py`; every real
call site — `pipeline.py:84,382` — already calls `flag_from_match`
directly).

**Fix — reuse `parent_chain` directly (the primitive `flag_from_match`
itself calls), not `flag_from_match` as a black box.** `flag_from_match`
is the wrong function to delegate to here: it exists specifically to
detect *foreign control* (Epic C), and its own logic (lines 93-94)
silently `continue`s past — never returns anything for — any ultimate
parent whose jurisdiction matches the employer's own. Calling it from
`tie_from_ownership` would mean a same-jurisdiction parent that *is*
concern-listed never even reaches the concern-list screen at all. That
contradicts the concern-tie's own documented purpose:
`docs/use-case-01-hb127-researcher-screening.md:92` — "the fact that a
declared employer's ultimate parent is concern-listed is a §51B.151(b)
matter" — with no jurisdiction precondition. Whether the parent is
*also* foreign-controlled (S3's separate jurisdiction/HQ-country check)
must not gate whether the tie exists in the first place.

So: reimplement the same small per-chain walk `flag_from_match` uses
(call `parent_chain` directly, de-dupe by ultimate LEI, build the real
`full_path`) *without* its same-jurisdiction skip, and make the
foreign/domestic distinction control only whether a `ForeignControlFlag`
gets attached — not whether the tie gets built:
```python
result = parent_chain(conn, match.lei, direction="up", max_depth=max_depth)
seen_ultimate_leis: set[str] = set()
for chain in result.chains:
    ultimate_lei = chain[-1]
    if ultimate_lei in seen_ultimate_leis:
        continue
    seen_ultimate_leis.add(ultimate_lei)

    parent_row = conn.execute(
        "SELECT legal_name, legal_jurisdiction, hq_country FROM gleif_lei WHERE lei = ?",
        [ultimate_lei],
    ).fetchone()
    if parent_row is None:
        continue
    parent_name, parent_jurisdiction, parent_hq_country = parent_row
    full_path = (match.lei, *chain)

    hits = _screen_name_against_concern_lists(
        parent_name, concern_lists, concern_threshold,
        anchor_entity_id=employer.affiliation_id,
        matched_field="ownership_ultimate_parent", producer="ownership_parent",
        ownership_path={
            "declared_employer_name": employer.institution_name,
            "declared_employer_lei": match.lei,
            "declared_employer_lei_match_basis": match.match_basis,
            "declared_employer_lei_confidence": match.confidence,
            "ultimate_parent_lei": ultimate_lei,
            "chain_truncated": result.truncated,
        },
    )
    if not hits:
        continue  # not concern-listed -- no tie, regardless of jurisdiction

    # S3, computed here since both country attributes are already in hand.
    country_on_adversary_list = adversary_list.contains(parent_jurisdiction)
    hq_country_on_adversary_list = adversary_list.contains(parent_hq_country)

    # A ForeignControlFlag is attached only when the parent's jurisdiction
    # genuinely differs from the employer's own -- same-jurisdiction
    # ownership isn't "foreign control" by Epic C's own definition. But
    # that's a separate fact from whether the tie exists: a same-
    # jurisdiction, concern-listed parent still produces a tie, just with
    # no ownership_evidence attached.
    ownership_evidence: tuple[ForeignControlFlag, ...] = ()
    if parent_jurisdiction != match.legal_jurisdiction:
        ownership_evidence = (ForeignControlFlag(
            entity_id=match.entity_id, entity_lei=match.lei,
            entity_jurisdiction=match.legal_jurisdiction,
            ultimate_parent_lei=ultimate_lei, ultimate_parent_name=parent_name,
            ultimate_parent_jurisdiction=parent_jurisdiction,
            relationship_path=full_path, match_confidence=match.confidence,
            evidence={"lei_match_basis": match.match_basis,
                      "relationship_path": list(full_path),
                      "truncated": result.truncated,
                      "source_attribution": attribution_for("gleif_golden_copy")},
            status=MatchStatus.CANDIDATE_MATCH,
        ),)

    ties.append(ConcernTie(
        tie_id=..., # unchanged S5 uuid5 key -- see below
        ..., concern_entity_name=parent_name,
        country=parent_jurisdiction or None,
        country_on_adversary_list=country_on_adversary_list,
        hq_country=parent_hq_country or None,
        hq_country_on_adversary_list=hq_country_on_adversary_list,
        record_count=len(full_path) - 1,  # M13 falls out for free
        concern_list_evidence=tuple(hits),
        ownership_evidence=ownership_evidence,
    ))
```
One `ConcernTie` per distinct ultimate-parent branch (de-duped the same
way `flag_from_match` de-dupes, just without its jurisdiction filter
gating inclusion). `tie_id`'s uuid5 key (`case_id`, `tie_kind`,
`anchor_affiliation_id`, `concern_entity_name`) is unchanged — for the
demo's single-branch, genuinely-foreign case, `concern_entity_name` is
still `parent_name` (NIO INC.), same value as today, so **the demo's
tie_id does not change**, only its embedded evidence does. Delete
`ultimate_parent`'s call site from this function entirely (confirm no
other caller in `discover.py` needs the import before removing it).
`flag_from_match`/`flagging.py` are **not touched** — the batch path's
own foreign-control semantics stay exactly as they are; this phase only
adds a second, independent caller of `parent_chain` with different
inclusion rules, not a shared refactor of the gated wrapper (a shared
"walk and look up distinct ultimate parents" helper is a reasonable
future cleanup if this duplication ever drifts, but not required now —
the two callers' decisions genuinely diverge at the one line that
matters, so factoring out just the walk would save a dozen lines at the
cost of an extra layer of indirection between two five-line call sites;
not worth it yet).

**Delete `compute_foreign_control_flag`** (M22, bundled here per the
strategy doc — confirmed dead in production regardless of this fix,
called only by 6 test sites, every real caller already uses
`flag_from_match` directly for the batch path). Update those 6 test call
sites in `tests/test_ownership_flagging.py` to call
`resolve_entity_to_lei(...)` then `flag_from_match(...)` directly (two
lines instead of one) — same coverage, no wrapper. This deletion is
independent of the jurisdiction-gating fix above; both are happening in
`ownership`/`reconciliation` code in the same phase, not because one
requires the other.

**A new, dedicated 3-node fixture — not the demo's own GLEIF fixture.**
The demo's `tests/fixtures/demo_case/gleif_lei.csv`/
`gleif_relationships.csv` is a genuine 2-node chain that ALSO carries
GLEIF's own `IS_ULTIMATELY_CONSOLIDATED_BY` shortcut edge between the
same two LEIs — `parent_chain` still returns a real one-hop chain here
(confirmed: the shortcut only short-circuits the *old* `ultimate_parent`
function, which this fix removes from this call path entirely; `parent_chain`
itself walks `IS_DIRECTLY_CONSOLIDATED_BY` edges regardless), so the demo
fixture is unaffected in shape and cannot be *extended* into a 3-node
chain without touching the two LEIs several other tests already assert
exact counts against, and without disturbing the "real, GLEIF-verified"
provenance `docs/plans/2026-09-14-close-gleif-verification-gate.md`
specifically established for those two rows. Build a small, separate,
clearly-synthetic 3-node fixture (e.g.
`tests/fixtures/multi_hop_gleif_lei.csv`/`multi_hop_gleif_relationships.csv`,
SUB → MID → ULTIMATE, `IS_DIRECTLY_CONSOLIDATED_BY` edges only, no
ultimate-consolidation shortcut, so the walk is genuinely forced through
`parent_chain`'s multi-hop path) for a **unit test directly on
`tie_from_ownership`**, not routed through the full demo case.

**Tests.**
1. Unit test: the new 3-node fixture, `tie_from_ownership` called
   directly with `SUB`'s institution as the declared employer, `ULTIMATE`
   on a concern list — assert `MID` appears in the resulting
   `ConcernTie.ownership_evidence[0].relationship_path`, and
   `record_count == 2` (2 links, SUB→MID→ULTIMATE).
2. **The bug this review round caught, made a binding test, not just a
   fixed line of code:** a same-jurisdiction fixture — `SUB` and its
   direct ultimate parent share one jurisdiction (e.g. both `CN`), and
   that parent's name *is* on a concern list. Assert a `ConcernTie` is
   still produced (`concern_list_evidence` populated,
   `country_on_adversary_list`/`hq_country_on_adversary_list` computed),
   with `ownership_evidence == ()` (no `ForeignControlFlag` — correctly,
   since it isn't foreign control). This is the exact case that would
   have silently vanished under the rejected `flag_from_match`-as-black-box
   design; it must exist as its own fixture/test, not be inferred from
   the 3-node one.
3. `compute_foreign_control_flag`'s deletion doesn't break
   `test_ownership_flagging.py` (6 call sites updated).
4. Demo case re-reconciled: tie count and tie_id unchanged; `record_count`
   changes from the fabricated `1` to whatever the real walk over the
   demo's own 2-node chain returns (expected: still `1`, since it's
   genuinely one hop — same number, but now computed, not asserted).
   `relationship_path` changes from the fabricated `(employer_lei,
   parent_lei)` 2-tuple to the real `full_path` this fix builds. Confirm
   both explicitly rather than assuming — run it and check.

---

## 3. S3 — carry both `legal_jurisdiction` and `hq_country` on the tie, label each verdict

**Current state.** `tie_from_ownership`'s GLEIF row lookup for the parent
(lines 278-284, `SELECT legal_name, legal_jurisdiction FROM gleif_lei
WHERE lei = ?`) never selects `hq_country`, even though
`entity_screening/ownership/ingest.py`'s `load_gleif_level1` (lines 51-96)
loads it into the `gleif_lei` table at ingestion time (line 73:
`"Entity.HeadquartersAddress.Country" AS hq_country`) — the column exists,
nothing downstream reads it. `ConcernTie` (`common/schema.py` lines
490-525) has exactly one country slot (`country`/
`country_on_adversary_list`/`adversary_list_version`) — confirmed by
direct read there is no room for a second verdict without a schema
change, and that change requires an `_OBSERVATION_GRAPH_ALLOWED_FIELDS`
edit (why S15 had to land first). `AdversaryCountryList.contains`
(`screening/adversary_list.py` lines 44-57) is shape-agnostic — it just
takes a country-code string, so it works identically against `hq_country`
with no changes there. This is scoped to `ConcernTie`/`tie_from_ownership`
only — `ForeignControlFlag`/`flag_from_match`/the batch `ownership_flags`
table are unaffected (the review's own "sound" list didn't flag them, and
S1 above deliberately leaves `flagging.py` untouched).

**Fix.**
1. Add `hq_country: str | None = None` and
   `hq_country_on_adversary_list: bool | None = None` to `ConcernTie`
   (with the S15-updated allowlist covering both from the start, not as a
   follow-up edit).
2. Already folded into S1's rewrite above: the parent-row lookup (now
   keyed off `ultimate_lei` from the direct `parent_chain` walk) already
   selects `hq_country` alongside `legal_jurisdiction`, and both
   `adversary_list.contains(...)` calls are already in that snippet. Kept
   as its own numbered item here only to state the *why* once, in one
   place, rather than splitting the rationale from the code.
3. UI (`pages/0_HB127_Case_Worksheet.py`'s concern-tie table): the
   existing single "adversary-list" column becomes two labelled columns
   — "adversary-list (legal)" and "adversary-list (HQ)" — reading `None`
   gracefully for `OWN_AFFILIATION_HISTORY` ties, which have no ownership
   dimension and so never populate the HQ pair.
4. Recitation (`explanation/skeletons.py`'s
   `_tie_declared_employer_ultimate_parent`, folded into the M1/M2 fix
   below since it's the same function): state both verdicts, each
   labelled with which attribute it refers to, not a bare "adversary-list:
   False."

**Verification against the live demo data point the review named
directly.** NIO INC. is `KY`-incorporated (legal jurisdiction),
`CN`-headquartered — confirmed in `tests/fixtures/demo_case/gleif_lei.csv`
(`hq_country` column already present in that CSV's header, just unread
today). Under this fix the demo's own tie should show
`country=KY, country_on_adversary_list=<whatever KY evaluates to>` and
`hq_country=CN, hq_country_on_adversary_list=<whatever CN evaluates to>`
— run it and record the actual values rather than assuming both differ
(that's the empirical point the review made, but confirm it against the
real adversary list content before writing it into the plan's
implementation note as fact).

**Tests.** Unit test on `tie_from_ownership` with a parent LEI whose
`legal_jurisdiction` and `hq_country` differ and land on opposite sides of
the adversary list (construct a small fixture proving this if the demo's
own KY/CN pair doesn't actually straddle the list both ways — check
first, don't assume) — assert both fields are populated and independently
correct.

---

## 4. S4 / M4 — `scope_compatible` computed for real; TEMPORAL_WINDOW honours `category`

**Current state.** `reconcile.py`'s `build_finding` hard-codes
`scope_compatible=True` on every `NearestDeclared` (line ~148, the
`ranked_declared_matches` comprehension) with the comment "scope is a
source property; recorded in the trail" — but nothing in the trail is
actually consulted here. `_overlaps_temporal_window` (lines 42-66) reads
only `descriptor["window_years"]`/`["anchor"]`; `descriptor.get("category")`
is never called anywhere in the codebase (confirmed by grep — the string
`"category"` as a dict key appears nowhere under `entity_screening/`).
`_source_covers` (lines 69-90) already does a comparable role/kind
comparison for `HIGHEST_ONLY` and `TYPE_ENUMERATION` (matching
`discovered.role`) — `TEMPORAL_WINDOW`'s branch is the one that doesn't.
`reconcile()`'s actual clearance gate (lines 173-192) is name-match-only
(`best.cleared`) — scope is computed (once fixed) only as trail/diagnostic
information on `NearestDeclared`, never consulted to decide whether an
item counts as declared in the first place.

**The clearance-gating question, settled empirically, not by
inspection.** The use-case-01 implementation plan's own §4.4 (`docs/plans/
2026-09-06-use-case-01-implementation.md:258-259`) defines "declared" as
"best name match ≥ threshold **and** the declared entry's scope admits
the discovered fact's date range" — a conjunction, stronger than today's
name-match-only gate. I checked whether wiring this conjunction into
`reconcile()`'s actual clearance would change either demo case's
findings, by hand-tracing every currently-clearing name match against its
declaring source's scope and the discovered item's actual date:
- **HB-127 demo case:** UT Austin clears via the DS-160 source
  (`TEMPORAL_WINDOW`, `category: employment`, window 2021–2026); its
  discovered occurrences are 2022/2023 — inside the window. Nanjing
  University clears via the CV source (`FULL_HISTORY` — always admits).
  Both still clear under the AND-rule. Beijing Institute of Technology /
  Zhejiang University (the case's two actual Findings) don't name-match
  any declared affiliation above threshold in the first place — scope
  gating is moot for them. **No change to this demo case's finding count
  either way.**
- **demo-coi case:** every declared affiliation (TAMU, UT Austin, the
  subsidiary) is declared under a single `TYPE_ENUMERATION` source
  (`outside_employment`/`board_membership`/`consulting`/
  `foreign_government_affiliation`) — a scope that, by the fixture's own
  design note, **never admits a bare `publication_affiliation` role at
  all**. Under the strict AND-rule, UT Austin and TAMU and the subsidiary
  would all *stop* clearing and become new Findings for demo-coi, even
  though they're the subject's own already-declared primary
  affiliations. This is wrong for a COI/outside-interest disclosure,
  where the declared set's job is to name primary affiliations at all,
  independent of the outside-interest form's own scope — the AND-rule is
  use-case-01/DS-160-specific per its own citation, not a general
  cross-case-kind rule, and demo-coi is `CaseKind.COI_ANNUAL_DISCLOSURE`.

**Decision: compute `scope_compatible` for real as trail/diagnostic
information on `NearestDeclared`; do not wire it into `reconcile()`'s
clearance gate.** This satisfies the review's actual complaint (a field
that always says `True` is a stated fact with no basis) without
introducing the cross-case-kind clearance-semantics change the empirical
check above shows would be actively wrong for COI cases. If a future
finding wants the stronger AND-gate, it should be scoped explicitly to
`CaseKind.HB127_RESEARCHER_SCREENING`, as its own reviewed change — not
smuggled into this fix.

**Fix.**
1. Add `_declared_source(declaration, declared_affiliation) ->
   DeclarationSource | None` (a lookup by `source_id` — a few lines, no
   new abstraction beyond what's needed).
2. In `build_finding`'s `NearestDeclared` construction, for each
   candidate `m`: `source = _declared_source(declaration, m.declared)`;
   `scope_compatible = _source_covers(source, item) if source else False`
   — reusing `_source_covers` exactly as `_declaration_search_trail`
   already does, no duplicated logic.
3. `_overlaps_temporal_window`: honour `category` before the date check.
   Since the only category value anywhere in this codebase's fixtures is
   `"employment"`, and every `DiscoveredAffiliation.role` from the
   OpenAlex path is always `"publication_affiliation"`-prefixed (never an
   employment record — a publication co-affiliation is evidence of an
   academic address on a paper, not a verified employment relationship),
   the honest, computed rule is: an `"employment"`-categorized window
   never admits a `publication_affiliation`-sourced item, regardless of
   date overlap — the same conservative-reading principle the function's
   own docstring already states for missing dates ("claiming coverage we
   can't establish would wrongly upgrade the finding"), extended to
   category. No other category value exists to build a rule for yet; add
   one only when a real fixture needs it, don't speculate now.

**Tests.** Unit test: `_overlaps_temporal_window` / `_source_covers` with
`category="employment"` and a `publication_affiliation` role, dates
inside the window → `False` (fails on the unmodified tree first, since
today only the date check runs and would return `True`). Unit test:
`NearestDeclared.scope_compatible` computed `False` for a candidate whose
declaring source's scope doesn't admit the discovered item's date/role,
`True` for one that does — against the demo's own real near-miss
candidate data (`Beijing Institute of Technology` vs `Tsinghua University`
at confidence 0.41, already present as a fixture in both
`tests/test_case_store.py:135-136` and `tests/test_explanation.py:68-69`)
rather than an invented case.

---

## 5. S2 — wire `TieKind.DECLARED_AFFILIATION_DIRECT`'s producer (optional — see note)

**Current state.** The enum member (`common/schema.py:484`) and its
recitation skeleton (`explanation/skeletons.py:97-126,
_tie_declared_affiliation_direct`, already registered in `_TIE_SKELETONS`)
both exist; grep confirms **no `ConcernTie` construction site anywhere**
uses this kind — it's templated dead code waiting for a producer.

**Fix.** New `ties_from_declared_affiliations(case_id, run_id,
declared_affiliations, concern_lists, *, concern_threshold=...)` in
`discover.py`, structurally closest to `ties_from_own_affiliations`
(no GLEIF/LEI dependency) but iterating `declared_affiliations` (each a
`DeclaredAffiliation`) instead of discovered ones:
```python
for a in declared_affiliations:
    hits = _screen_name_against_concern_lists(
        a.institution_name, concern_lists, concern_threshold,
        anchor_entity_id=a.affiliation_id,
        matched_field="declared_affiliation_direct",
        producer="declared_affiliation",
    )
    if not hits:
        continue
    ties.append(ConcernTie(tie_kind=TieKind.DECLARED_AFFILIATION_DIRECT, ...))
```
Wire into `pipeline.py`'s `reconcile_case` tie-assembly block as another
unconditional `ties += ties_from_declared_affiliations(case_id, run_id,
list(declaration.affiliations), concern_lists)` (no GLEIF gate, same as
`ties_from_own_affiliations`), and append `"declared_affiliation_direct"`... no —
reuses the same `"dod_section_1260h"`/`"opensanctions"` `discovery_sources`
entries `_case_concern_lists` already covers; no new discovery-source
label needed since it's screening against the same lists, just a
different anchor.

**Confirmed the demo stays clean.** Both demo declarations' institution
names (`Texas A&M University`, `University of Texas at Austin`, `Nanjing
University`, `Nanjing Zhongke Robotics Co., Ltd.` for HB-127;
the same three minus Nanjing University for COI) — read directly from
both fixture files — none of them are themselves on DoD 1260H/
OpenSanctions (only the *subsidiary's GLEIF ultimate parent*, a different,
undeclared legal name, is). Zero new ties for either demo case; the
producer existing and being wired in changes nothing about demo evidence.

**Note — this is the one item in this phase that's genuinely optional.**
Per the strategy doc's own framing, S2 is "a feature dressed as a
finding," not a regression fix — it's in Phase 4 only because it changes
reconciliation output and belongs under the one fixture bump. If this
phase is running long, it can be dropped without harm; its skeleton/label
would then get deleted under a future M22-style cleanup instead. Building
it is small (one new function, one wiring line, confirmed zero demo
impact), so the recommendation is to build it — but it's the one line
item to cut first if time is short.

**Tests.** Unit test: a declared "Beijing Institute of Technology" (real
1260H/OpenSanctions entry — Seven Sons Universities, already a curated
list per this project's own prior verification work) not independently
matched by any discovered item → a `DECLARED_AFFILIATION_DIRECT` tie.
Both demo cases: zero new ties (confirms the "stays clean" claim, not
just asserts it).

---

## 6. M1 / M2 — recitation: real link count, name the declared employer

**Current state.** `explanation/skeletons.py`'s
`_tie_declared_employer_ultimate_parent` (lines 81-94) recites
`len(flag.relationship_path)` as the link count — node count, not link
count (a 2-node path recites "2 link(s)" for what is, correctly, one
hop). It never reads `t.anchor_affiliation_id` or
`hit.evidence["ownership_path"]["declared_employer_name"]` — the
employer's name is reachable from the full `ConcernTie` `recite()`
already passes in, just never read.

**Fix (same function, one edit — also where S3's dual-verdict labelling
lands, per §3 above). Uses `t.record_count` for the link count, not
`len(ownership_evidence[0].relationship_path)`** — after S1's fix,
`record_count` is always set correctly on the tie itself regardless of
whether a `ForeignControlFlag` happens to be attached (a same-
jurisdiction-but-listed tie has real path/hop data but legitimately no
`ownership_evidence`, per §2's redesign — reading the count off the tie
directly, not off evidence that may not exist, is the more robust source
either way):
```python
def _tie_declared_employer_ultimate_parent(t: ConcernTie) -> str:
    hit = t.concern_list_evidence[0] if t.concern_list_evidence else None
    employer_name = (
        hit.evidence.get("ownership_path", {}).get("declared_employer_name")
        if hit else None
    ) or "a declared employer"
    path_text = f" via an ownership chain of {t.record_count} link(s)" if t.record_count else ""
    list_text = f" on {hit.list_name}" if hit else ""
    jurisdiction_text = f", legal jurisdiction {t.country}" if t.country else ""
    hq_text = f", headquartered in {t.hq_country}" if t.hq_country else ""
    adversary_text = (
        f" (adversary-list — legal: {t.country_on_adversary_list}, HQ: {t.hq_country_on_adversary_list})"
    )
    return (
        f"{employer_name}'s ultimate parent, per GLEIF ownership data, is "
        f"{t.concern_entity_name}{jurisdiction_text}{hq_text}, which appears"
        f"{list_text}{path_text}{adversary_text}."
    )
```
(Exact prose to be refined against the lexicon check during
implementation — this is the shape, not final copy; must still pass
`lexicon.is_clean` and the fact/judgment discipline — no evaluative
language, every clause a stated fact.)

**Tests.** Recitation test with a real 2-node chain → "1 link(s)", real
3-node chain (the new S1 fixture) → "2 link(s)". Recitation contains the
employer's name string. Recitation for the same-jurisdiction-but-listed
fixture (§2's new required test) still states a real link count with no
`ownership_evidence` attached — proves the fix reads `record_count`, not
the evidence tuple, for this number. Demo recitation text changes
(expected, part of the one fixture bump) — diff it explicitly in the
implementation note.

---

## 7. M21 — drop the unused `declared_affiliations` parameter

**Current state.** `discover_from_publications` (`discover.py` lines
113-123) takes `declared_affiliations: list[DeclaredAffiliation]` at
position 3 — confirmed never read in the function body. 3 call sites,
all positional: `pipeline.py:706`, `tests/test_reconciliation.py:170`,
`tests/test_adversary_list.py:87`.

**Fix.** Remove the parameter; update all 3 call sites. Small, mechanical,
no behavior change — safe to do alongside the bigger changes in this
phase since it touches the same function signature S2/S1 neighbor code
already has open.

---

## 8. B4 follow-up — a real (if narrow) GLEIF path for non-demo cases

**Current state.** `docs/architecture.md`'s "Known limitations" section
(added Phase 1) states plainly: a case created via `POST /cases` never
receives GLEIF files, so it never gets ownership-parent screening — no
real path exists yet, only the demo one. `ReconcileRequest`
(`case_routes.py:92-94`) has exactly one field, `contact_email` — no way
for a caller to supply their own GLEIF snapshot. `api/main.py`'s batch
`/runs/{id}/ownership` route already accepts `gleif_lei_file`/
`gleif_relationships_file` as caller-supplied paths, gated through
`_allowed_data_files`/`_check_allowlisted` (lines 344-345) — the same
`MONOPS_DATA_FILE_ALLOWLIST` mechanism `entity_screening/api/deps.py`
already exposes for `case_routes.py`/`rps_routes.py` to reuse
(`deps.allowed_data_files`/`deps.check_allowlisted`, confirmed present
and not yet imported into `case_routes.py`).

**Decision: wire the existing allowlisted-path mechanism through to the
case route, rather than building a real GLEIF network-download path.** A
live GLEIF Golden Copy download is a large, gated fetch — building that
is out of scope for a portfolio project's Phase 4 and is exactly the kind
of feature the strategy doc's §9 warns against smuggling in. What *is*
in scope and genuinely closes the limitation: a caller who already has a
GLEIF snapshot on disk (downloaded once, out of band, same posture as the
batch route's own `gleif_lei_file` param) can now supply it to a
non-demo case's reconcile call, gated by the same allowlist every other
caller-supplied path already goes through.

**Fix.**
1. `ReconcileRequest` gains `gleif_lei_file: str | None = None`,
   `gleif_relationships_file: str | None = None`, `opensanctions_file:
   str | None = None` (the last one isn't wired into the case route at
   all today either, for any case, demo included — closing that too,
   same mechanism).
2. In the `reconcile` route: import `allowed_data_files`/
   `check_allowlisted` from `api/deps.py`; call `check_allowlisted` on
   all three request paths before calling `pipeline.reconcile_case`;
   pass `request.gleif_lei_file or (demo path if is_demo)` etc. — demo
   cases keep using their bundled fixture paths regardless of what a
   caller supplies (ignore caller-supplied GLEIF paths for `demo`/
   `demo-coi`, don't let a caller override the verified demo fixture).
3. Update `docs/architecture.md`'s "Known limitations" section to state
   the corrected, narrower limitation: non-demo ownership screening now
   has a real path (a caller-supplied, allowlisted GLEIF snapshot) — the
   remaining limitation is that nothing in this build fetches one
   automatically; an operator must have one locally and supply its path.

**Tests.** `POST /cases/{id}/reconcile` with a real (small,
already-bundled test-fixture) GLEIF file pair for a non-demo case →
ownership-parent screening actually runs (mirrors Phase 1's B4 test
pattern, but through the route this time, not only at the pipeline
layer). Path outside the allowlist (when `MONOPS_DATA_FILE_ALLOWLIST` is
set) → 400, same as the batch route's existing test for this. A
caller-supplied GLEIF path for `case_id="demo"` is ignored in favor of
the bundled demo fixture (demo integrity can't be overridden by a
caller).

---

## Cross-cutting

**Failing test first for every item with a real "before" state**: S15's
recursive-walk test, S1's 3-node fixture test, S4/M4's category test,
S2's declared-affiliation test, M4's `_overlaps_temporal_window` test —
all run red against the unmodified tree first.

**The fixture bump — once, at the end, after every item above is green
against unit fixtures.**
1. Reconcile both demo cases under the new code; diff against the
   pre-phase snapshot the same way Phase 1/3 did (stash, capture, restore,
   diff) — this time the diff is *expected* to be non-empty on evidence
   fields (`relationship_path`, `record_count`, recited text) while tie
   *counts* stay the same for both demo cases (confirmed by the S1/S4
   empirical checks above). Record the actual diff in the implementation
   note, not just "it changed as expected."
2. Bump `DEMO_FIXTURE_VERSION` (8, following Phase 3's 7) so the self-heal
   rebuilds under the corrected evidence — needed because `_ensure_demo_case_exists`
   only rebuilds on a version change, not on a code change; `finding_id`/
   `tie_id` values are unchanged by this phase (confirmed above), so this
   bump is purely to force re-computation of evidence, not for id
   continuity.
3. **Regenerating demo explanations with a live key.** Epic J's
   corrected grounding gate (Phase 2) meeting real demo evidence for the
   first time is exactly what the strategy doc means by "the calibration
   pass" — expect a lower synthesis yield, and the lexicon/prompt may
   need a follow-up pass *after* seeing real output, not before (do not
   pre-tune against a guess). Mechanism: make `_ensure_demo_case_exists`'s
   explanation-pre-generation call use `_default_anthropic_call` when
   `ANTHROPIC_API_KEY` is set in the environment at build/deploy time,
   falling back to today's `_demo_no_synthesis_call` when it isn't — a
   small conditional, not a new CLI command, and it keeps the existing
   safety property (the public box, with no key, is unaffected either
   way). **This step needs a live key I don't have in this environment**
   (same limitation Phase 2's S13 hit) — the code change lands regardless;
   the actual regeneration and recording its raw output/yield happens
   wherever a key is available (locally, or the deploying box with the
   env var set once for the rebuild), and that record goes in the
   implementation note afterward, not invented now.

**Full suite green, `cli validate` passes** before calling this phase
done.

**Deploy is part of the phase.** Set `ANTHROPIC_API_KEY` on the deploying
shell (not committed anywhere) if real demo synthesis is wanted for this
deploy — omit it and the demo stays recitation-only, exactly as safe as
every prior deploy. Runbook §7, confirm both demo cases load post-rebuild,
and specifically confirm "Explain this match" for the demo's ownership
tie shows the corrected recitation (real link count, employer named, both
jurisdiction verdicts labelled).

**Docs.** Copy this plan into
`docs/plans/2026-09-17-phase-4-reconciliation-evidence-correctness.md`,
index it in `docs/plans/README.md`, dated implementation note appended
afterward.

## Verification summary (binding acceptance criteria)

- [x] `cli validate` walks `ScreeningHit`/`ForeignControlFlag` and
      recursively into every `evidence` dict; fails on a planted
      forbidden-token key nested inside one (fails on the unmodified tree
      first).
- [x] 3-node chain fixture: `MID` appears in `ownership_evidence[0].relationship_path`;
      `record_count` reflects the real 2-link chain.
- [x] Same-jurisdiction, concern-listed parent still produces a
      `ConcernTie` (with `ownership_evidence == ()`) — the regression the
      first plan draft would have silently introduced.
- [x] `compute_foreign_control_flag` deleted; its 6 test call sites
      updated to call `resolve_entity_to_lei` + `flag_from_match` directly.
- [x] The demo's own ownership tie shows both `country`/`country_on_adversary_list`
      (legal) and `hq_country`/`hq_country_on_adversary_list` (HQ),
      independently computed, each labelled in the recitation.
- [x] `NearestDeclared.scope_compatible` is computed (not `True` by
      default) against the demo's own near-miss candidate data; an
      `"employment"`-categorized `TEMPORAL_WINDOW` source never admits a
      `publication_affiliation`-sourced item (fails on the unmodified
      tree first).
- [x] `reconcile()`'s clearance gate is unchanged (deliberately) — both
      demo cases' finding counts are unaffected by the scope_compatible
      fix, confirmed by re-running both after the change.
- [x] `DECLARED_AFFILIATION_DIRECT` has a producer and a test; zero new
      ties for either demo case (confirmed, not assumed) — or explicitly
      dropped from this phase with a dated note, per the strategy doc's
      own "optional" framing.
- [x] Recitation states the real link count and names the declared
      employer; a real 2-node flag recites "1 link(s)."
- [x] `discover_from_publications`'s unused parameter removed; all 3 call
      sites updated.
- [x] A non-demo case can supply an allowlisted GLEIF snapshot through
      `POST .../reconcile` and get real ownership-parent screening; a
      caller-supplied GLEIF path is ignored for `demo`/`demo-coi`.
- [x] One `DEMO_FIXTURE_VERSION` bump (7→8); demo-evidence diff recorded
      in the implementation note, non-empty on evidence fields, unchanged
      on finding/tie counts and ids.
- [x] Full suite green; `cli validate` passes.
- [ ] Deployed; both demo cases confirmed loading; the ownership tie's
      recitation confirmed corrected on the live site.

## Implementation note (2026-09-17)

Built as planned, with one deviation and one confirmed-optional item kept
in (not dropped):

**S1** shipped exactly as revised in review: `tie_from_ownership` now
calls `parent_chain` directly, screens every distinct ultimate parent
regardless of jurisdiction, and attaches `ForeignControlFlag` only when
jurisdictions genuinely differ. `compute_foreign_control_flag` deleted;
its 6 test call sites in `tests/test_ownership_flagging.py` now call
`resolve_entity_to_lei` + `flag_from_match` directly (no wrapper
reintroduced -- an early draft of this edit added one back and was
caught and removed before landing). New fixtures:
`tests/fixtures/multi_hop_gleif_lei.csv`/`multi_hop_gleif_relationships.csv`
(a genuine 3-node SUB->MID->ULTIMATE chain) back a direct unit test on
`tie_from_ownership` proving `record_count == 2` and `MID` appears in
`relationship_path`. The same-jurisdiction-but-listed regression test
(the one the first plan draft would have failed) is
`tests/test_reconciliation.py::test_tie_from_ownership_still_ties_a_same_jurisdiction_listed_parent`.

**S3**: `ConcernTie.hq_country`/`hq_country_on_adversary_list` added.
**Deviation from the plan as reviewed**: the plan's storage-layer impact
wasn't spelled out in the reviewed text, and building it surfaced a real
gap -- `entity_screening/common/storage.py`'s `concern_ties` DDL,
`case/store.py`'s `_TIE_COLUMNS`/`replace_ties`/`load_ties`, and
`case/export.py`'s `_tie_to_dict` all had to be extended too, or the two
new fields would silently vanish on every save/reload round-trip (the API
response, the worksheet UI, and the investigative-file export all read
through `_tie_to_dict`). Added an idempotent `ALTER TABLE concern_ties
ADD COLUMN IF NOT EXISTS` migration (same pattern already used for
`screening_hits.producer`/`cases.declaration_id`) rather than relying only
on `CREATE TABLE IF NOT EXISTS`, which is a no-op against a pre-existing
DB file. Verified empirically against the demo's own NIO INC. tie: legal
jurisdiction `KY` -> adversary-list `False`; HQ `CN` -> adversary-list
`True` -- the two verdicts genuinely differ, confirming the review's
prediction rather than assuming it.

**S4/M4, S2, M21, B4-followup** shipped exactly as planned. S2's producer
was kept (not dropped) since it was small and confirmed zero-impact, per
the plan's own "recommend building it" framing. B4-followup's new
`/cases/{id}/reconcile` fields are gated through the same
`allowed_data_files`/`check_allowlisted` mechanism as the batch route;
`demo`/`demo-coi` ignore a caller-supplied path (tested explicitly in
`tests/test_api_security.py`, including the demo-integrity-can't-be-
overridden case, which required driving the demo case through its full
WORKSHEET -> ADJUDICATION -> OUTCOME -> CLOSED -> DISCOVERY cycle first,
since the demo case self-heals into WORKSHEET on first touch and
`reconcile` refuses to run again from there).

**Demo-evidence diff** (the one phase expected to produce one), read
directly off the demo's own NIO INC. tie, before vs. after:

| field | before | after |
|---|---|---|
| `record_count` | `1` (hard-coded) | `1` (now the real 1-hop `parent_chain` walk -- same value, now computed) |
| `ownership_evidence[0].relationship_path` | `(SUB_lei, ULT_lei)` (hard-coded 2-tuple) | `(SUB_lei, ULT_lei)` (same value, now `(match.lei, *chain)` from the real traversal) |
| `hq_country` | field did not exist | `"CN"` |
| `hq_country_on_adversary_list` | field did not exist | `True` |
| `country_on_adversary_list` | `False` (KY) | `False` (unchanged -- this check predates Phase 4) |
| recitation | *"A declared employer's ultimate parent, per GLEIF ownership data, is NIO INC. (KY), which appears on dod_section_1260h via an ownership chain of 2 link(s)."* (M1/M2's bug: 2 is the node count of a hard-coded 2-tuple, not the real 1-hop link count) | *"Nanjing Zhongke Robotics Co., Ltd.'s ultimate parent, per GLEIF ownership data, is NIO INC., legal jurisdiction KY, headquartered in CN, which appears on dod_section_1260h via an ownership chain of 1 link(s) (adversary-list -- legal: False, HQ: True)."* |

`finding_id`/`tie_id` are byte-identical before and after (confirmed --
neither the tie's natural key nor `case_id`/`tie_kind`/
`anchor_affiliation_id`/`concern_entity_name` changed). Both demo cases'
finding counts (2 for HB-127, 3 for demo-coi) and tie counts (1 each) are
unchanged. `DEMO_FIXTURE_VERSION` bumped 7->8 so a pre-existing data
volume's cached rows self-heal into the corrected evidence on next
deploy.

**Not done in this session**: the live-key explanation regeneration
itself. The code change landed, but no `ANTHROPIC_API_KEY` was available
in this environment to actually run it and record the real synthesis
yield -- same limitation Phase 2's S13 hit. Deploy (and the live-site
recitation confirmation) is still outstanding, same as Phase 3.

**Two corrections made after independent review of this diff, before any
commit:**

1. **B4-followup's new tests had a live network dependency.** The
   `/cases/{id}/reconcile` tests drive a non-demo case through the real
   `pipeline.reconcile_case`, which -- unlike the demo path -- has no
   `works_fixture` to short-circuit `discover_from_publications`, and the
   HTTP route can't accept an injectable `fetch` over the wire. This was
   the only test in the suite reaching live `api.openalex.org` with
   nothing standing in front of it, and it was caught by a real failure
   (proxy-blocked) rather than by inspection. Fixed with an autouse
   `no_live_openalex_calls` fixture in `tests/test_api_security.py` that
   monkeypatches `openalex_client._http_get` to return an empty result --
   the identical fixture (same name, same fix) `tests/test_api_bibliometric.py`
   already uses for the same reason.
2. **The live-key regeneration switch wasn't actually scoped to deploy
   time.** As first written, `_ensure_demo_case_exists` gated on a bare
   `os.environ.get("ANTHROPIC_API_KEY")` -- but that function runs from
   the plain test suite too (any test touching `/cases/demo/...`, five
   files' worth), and `ANTHROPIC_API_KEY` is commonly already set in a
   developer's shell for reasons unrelated to this project (other Claude
   tooling). A developer running the ordinary suite with that var set
   would have silently started making real, billed API calls across those
   tests -- confirmed current CI is safe today (the base `test` job never
   sets the secret; `llm-explanation-real-model.yml` scopes it to one
   file) so nothing was actually broken, but it was a latent trap sitting
   on an accident of a shared env var name, not a deliberate gate. Fixed
   by requiring a second, separate opt-in,
   `MONOPS_DEMO_LIVE_SYNTHESIS` (documented in
   `docs/deployment-runbook.md`'s §8), set only by a deliberate deploy
   step -- never by the base test/CI config -- alongside the real key.
   Added `tests/test_api_case.py::test_demo_self_heal_never_calls_the_live_anthropic_client_from_anthropic_api_key_alone`,
   which monkeypatches `_default_anthropic_call` to raise if called and
   sets only `ANTHROPIC_API_KEY` (not the new opt-in), proving the gate
   holds.
