# Use Case 03 — Annual COI/Outside-Interest Disclosure Reuse

**Status:** Approved and built. Step 6 is implemented — see
`docs/plans/2026-09-15-step-6-coi-annual-disclosure-reuse.md` for the approved plan
and what shipped. This document is the spec of record for the *why*; read the plan
for the *what*.
**Date:** September 15, 2026
**Scope:** reusing the reconciliation engine built for use-case-01 (HB 127) to also
serve a research university's annual conflict-of-interest disclosure cycle.

---

## 0. The headline finding, stated first

**"COI and NSPM-33" is two different problems wearing one name, the same shape as
use-case-02 §0's finding for "export control."** `docs/use-case-01-hb127-researcher-
screening.md` §12 named step 6 "COI and NSPM-33 disclosure reuse" and called it
"nearly free." Read separately, against real sources, they are not one thing:

1. **NSPM-33's own federal disclosure forms** (Biographical Sketch + Current & Pending
   (Other) Support) are submitted at proposal time and updated on event triggers — a
   new proposal, a post-award "reportable change," a 30-day window after an
   undisclosed-support discovery, and (per NSF's Research.gov process, live since May
   2024/Oct 2025) an annual PI/co-PI certification of foreign-talent-program
   non-participation. Their content is per-*project*: funding source, dollar amount,
   person-months, dates, and an explicit overlap-with-pending-proposals check. None of
   it maps onto this project's `DeclaredAffiliation` (institution + role + dates +
   activity kind) without a new, differently-shaped type. **Out of scope for this
   reuse**, permanently, for the same reason use-case-02 keeps export-control
   jurisdiction/classification out of scope: it is a different artifact, not a harder
   version of this one.
2. **A real annual institutional COI disclosure** — specifically, financial
   conflicts of interest in sponsored research — is the artifact step 6 actually
   targets. Confirmed directly against **Texas A&M System Regulation 15.01.03,
   Financial Conflicts of Interest in Sponsored Research** (not TAMU's separate
   Conflict-of-Commitment rule, 15.99.99.M0.02, which governs outside-time-commitment
   limits rather than financial/affiliation disclosure — the two are adjacent, not
   the same, the same care use-case-02 §6 took over "three different lists of
   countries"): disclosure is submitted at hire and **at least annually, plus within
   30 days of a change**, via a Disclosure Profile (TAMU uses the Huron Research
   Suite). Confirmed convergent across TAMU, Rice University Policy 218, and Ohio
   State's outside-activities policy: the content is exactly affiliation-shaped —
   outside employment, board memberships, consulting, foreign government/
   institutional affiliations, each with an organization name, a role, and dates.
   **This is a self-reported affiliation set reconciled against the record, the same
   shape as a §51B.152 declaration** — the actual basis for "nearly free."

Step 6's real scope is (2), not (1). This document exists to say so plainly, before
the two get built together by accident.

## 1. What's already reusable versus genuinely new

Verified directly against the code, not assumed from the doc that first named step 6:

**Reusable unmodified:** `Declaration`/`DeclaredAffiliation`/`DeclarationSource`/
`ScopeKind` (no field names a document type, a statute, or "hiring");
`reconciliation/reconcile.py`/`match.py` (consume only the declaration's affiliations
and sources); `Finding`, `ConcernTie`, the worksheet/adjudication/export pipeline, and
the fact/judgment-boundary field allowlist; `DISMISS_REASON_CODES` and both `TIE_*`
vocabularies (already statute-agnostic factual bases — `known_and_previously_reviewed`
already says "prior case **or disclosure cycle**," anticipating exactly this).

**Genuinely new — small, real, but not new matching logic:**

1. **A recurrence gap.** Nothing stopped two `Declaration` rows existing for one
   subject, but reconciliation and export derived "the" declaration for a case by
   looking up the subject's declaration after the fact — ambiguous the moment a
   subject has more than one, exactly what an annual disclosure cycle means. Fixed by
   giving `Case` its own `declaration_id`, set once at creation, never inferred.
2. **`coverage_basis` names a specific HB 127 statutory limb**, not generic case
   metadata — a COI case has none. Confirmed (by grepping the whole package) that
   `coverage_basis`/`access_scope` are purely descriptive, never branched on by any
   matching logic, so widening the field to `Optional` was safe but not a no-op.
3. **A COI case has no §51B.153 department-head-certification escalation path.**
   Reusing `ESCALATION_REASON_CODES` unmodified would offer that dead-end code to an
   analyst on a COI case — the same wrong-shape-reuse mistake this project's own
   retrospective already flagged once for `ConcernTie`/`Finding`
   (`docs/plans/2026-09-06-concern-ties-as-a-distinct-observation.md`). A small,
   dedicated `COI_ESCALATION_REASON_CODES` vocabulary fixes it, the same way RPS got
   its own `RPS_ESCALATION_REASON_CODES` rather than reusing HB-127's.

## 2. The fact/judgment boundary, extended here

The same discipline as use-case-01 §4 and use-case-02 §3: the system states an
observable fact about a declaration and a record, never an evaluation. A COI
`Finding` is never itself "a conflict" — whether a disclosed or discovered interest
*rises to* a conflict of interest, and what management plan follows, is the
institution's COI committee's call, exactly the same boundary `ConcernTie` already
holds for "would prevent... maintaining the security or integrity of the research."
Nothing in this reuse adds a severity, risk, or materiality field to any observation
type; `_OBSERVATION_GRAPH_ALLOWED_FIELDS` is unchanged.

## 3. What a COI case looks like as built

A `Case` with `case_kind=CaseKind.COI_ANNUAL_DISCLOSURE`: `coverage_basis=None` (no
§51B.151(a) limb applies), `trigger` naming the disclosure cycle (e.g. "Annual
Outside-Interest disclosure, TAMU System Regulation 15.01.03, FY2027"),
`access_scope` repurposed as a plain note that this isn't gating a specific
access-granting decision, and `statutory_deadline` holding the cycle's regulatory
(not statutory) due date — the same field shape, a different kind of deadline. Its
`Declaration` carries a `DeclarationSource.kind="coi_outside_interest_disclosure"`
with a `ScopeKind.TYPE_ENUMERATION` scope (the categories a real Outside-Interest
form enumerates: outside employment, board membership, consulting, foreign
government affiliation) — deliberately narrower than a DS-160/CV's scope, so an item
outside those categories (e.g. educational history) surfaces as a genuine,
scope-bounded `Finding`, not a silently-dropped gap.

## 4. Demo data (synthetic subject, real reference data)

The demo reuses the existing HB-127 demo subject (`demo-subject`, "Wei Chen" —
fabricated, per use-case-01 §10) rather than inventing a new one: a second case
(`demo-coi`) with its own `Declaration` for the same subject, run through the same
reconciliation engine independently. Its declared set keeps the fabricated
subsidiary employer (so the GLEIF ownership-chain `ConcernTie` — the project's
headline demonstration — re-fires for this case too, proving the engine reruns per
case rather than being a one-shot) but omits Nanjing University's education entry,
which a real Outside-Interest form's enumerated categories would not ask about. Its
`TYPE_ENUMERATION` scope (outside employment/board/consulting/foreign-government-
affiliation) also does not admit a bare "publication_affiliation" role at all, so
every OpenAlex-discovered institution not independently cleared by a declared-name
match surfaces as an `ABSENT_OUTSIDE_ALL_SOURCE_SCOPES` discrepancy — a *larger*
discrepancy set than the HB-127 case's own two (Beijing Institute of Technology,
Zhejiang University), which also now includes Nanjing University, since the COI
form's real scope genuinely doesn't reach any of them. This is the direct
end-to-end proof that `Case.declaration_id` actually disambiguates two cycles for
one subject: each case's discrepancy set is independently derived from its own
declaration, not shared or merged.

## 5. Open questions

- **The §51B.153 certification endpoint/UI has no `case_kind` guard.** Nothing stops
  recording a department-head certification on a COI case, where it is semantically
  meaningless (a COI case has no §51B.153 basis at all). Not fixed in this pass —
  flagged rather than silently left, the same discipline this project applies to its
  other documented gaps (the gubernatorial-designation path, OFAC-embargoed-country
  screening).
- **Whether a real TAMU Outside-Interest form's exact field list should replace the
  generic categories used here.** The TAMU rule PDFs themselves weren't
  machine-readable during this pass; the categories used (outside employment, board
  membership, consulting, foreign government affiliation) are the convergent set
  across TAMU's own compliance-office description plus Rice/Ohio State's published
  policies, not a verbatim TAMU field list.
- **Whether the periodic-sweep re-screening capability** use-case-01 §8 already
  names as a first-class, not-yet-built requirement (a batch pass re-screening the
  closed-case population against updated reference data) should run across HB-127 and
  COI cases together once built, given both are now "cases" in the same sense. Not
  resolved here; that capability doesn't exist yet for either case kind.

## 6. Sources referenced

- Texas A&M System Regulation 15.01.03, *Financial Conflicts of Interest in Sponsored
  Research*, and University Rule 15.01.03.M1 — `rules-saps.tamu.edu`,
  `research.tamu.edu/research-compliance/conflict-of-interest/` — the annual +
  30-day disclosure cadence and the Huron-Research-Suite Disclosure Profile.
- OSTP, *Guidance for Implementing National Security Presidential Memorandum 33
  (NSPM-33)*, and NSF's NSPM-33 policy pages (`nsf.gov/policies/nspm-33`) — the
  federal Biographical Sketch / Current & Pending Support disclosure content and its
  proposal/award-lifecycle timing, establishing §0's scope split.
- Rice University Policy 218, *Disclosure and Management of Outside Activities and
  Outside Interests* (`policy.rice.edu/218`), and Ohio State's outside-activities
  policy — convergent real institutional field-shape evidence for §0.2/§3.
- `docs/use-case-01-hb127-researcher-screening.md` — structural template and the
  fact/judgment boundary principle extended here.
- `docs/use-case-02-restricted-party-screening.md` §0/§6 — the two-regimes-one-name
  caution this document applies a second time.
