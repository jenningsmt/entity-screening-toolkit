# Use Case 02 — Restricted-Party Screening (Export Control)

**Status:** Approved and built. Step 5 (restricted-party screening only, per this
document's own Section 0 scope split) is implemented — see
`docs/plans/2026-09-14-restricted-party-screening.md` for the approved plan and what
shipped. This document remains the spec of record for the *why*; read the plan for
the *what*.
**Date:** September 14, 2026
**Scope:** U.S. export control and restricted-party-screening compliance as operated
by a research security / export control function at a large public research
university — Texas A&M used as the concrete reference throughout, mirroring
use-case-01's approach.

---

## 0. The headline finding, stated first

**"Export control" is two different problems wearing one name, and only one of them
is this project's shape.**

1. **Restricted-party screening (RPS):** is a specific person or organization named
   on one of several U.S. government prohibited/denied/debarred-party lists? This is
   a **name-matching, concern-list problem** — structurally the same shape as the
   `ConcernTie` mechanism already built for HB 127 (Epic D / `screening/lists.py`).
2. **Export-control jurisdiction, classification, and licensing:** is a specific
   *item, technology, or piece of technical data* subject to export control at all
   (ITAR vs. EAR vs. neither), does the Fundamental Research Exclusion apply, and if
   controlled, does releasing it to a specific foreign national require a license?
   This is a **case-by-case legal/technical classification problem** performed by a
   trained export control officer against the actual technology involved — it is not
   a declaration-vs-record diff, not a list lookup, and not something this system
   should attempt. It fails the same fact/judgment boundary test
   (`docs/use-case-01-hb127-researcher-screening.md` §4) that already keeps this
   project from asserting "confirmed" findings about a person.

**Step 5's real scope is (1), not (2).** §12's one-liner says "export-control and
restricted-party screening" as if they were one thing this project builds together;
they are not — this document exists specifically to separate them, per the review
instructions that prompted it. (2) is described below only so its boundary is explicit
and so nothing in this document is mistaken for proposing that the system perform it.

---

## 1. Statutory and regulatory basis

Three independent regulatory regimes are in play, each with a different reach. Read
directly, not assumed from the "export control" label:

**Export Administration Regulations (EAR), 15 CFR 730–774**, administered by the
Department of Commerce's Bureau of Industry and Security (BIS). Governs "dual-use"
items and technology. Two provisions matter most for a hiring/visiting-scholar
screening tool:
- **The deemed-export rule, 15 CFR § 734.13:** "Releasing or otherwise transferring
  'technology' or source code (but not object code) to a foreign person in the United
  States" is an export — "[a]ny release in the United States of 'technology' or source
  code to a foreign person is a deemed export to the foreign person's most recent
  country of citizenship or permanent residency." Confirmed by direct read
  (`law.cornell.edu/cfr/text/15/734.13`, mirroring the current eCFR text).
- **The Fundamental Research Exclusion (FRE), 15 CFR § 734.8:** research qualifies
  when "the researchers have not accepted restrictions for proprietary or national
  security reasons" and "remain free to publish the 'technology' or 'software'... 
  without restriction." It stops applying the moment a researcher accepts a
  publication restriction or an unresolved government access/dissemination control.
  Confirmed by direct read (`law.cornell.edu/cfr/text/15/734.8`). Traces to
  **NSDD-189** (1985, reaffirmed 2001), which is where "fundamental research" as a
  legal category originates.

**International Traffic in Arms Regulations (ITAR), 22 CFR 120–130**, administered by
the State Department's Directorate of Defense Trade Controls (DDTC). Governs defense
articles and services on the **U.S. Munitions List (USML, 22 CFR § 121.1)** — 21
categories from firearms to spacecraft to Category XXI, "Articles, Technical Data and
Defense Services Not Otherwise Enumerated" (the catch-all final category; Category
XVII, "Classified Articles, Technical Data and Defense Services Not Otherwise
Enumerated," is the similarly-worded but distinct classified-items category). Has its
own deemed-export concept and its
own Fundamental Research Exclusion at **22 CFR § 120.34(a)(8)**, with the same two
disqualifying conditions as the EAR's (accepted publication restrictions; unresolved
government-funded access/dissemination controls) — confirmed by direct read
(`law.cornell.edu/cfr/text/22/120.34`). ITAR applies narrowly relative to EAR for most
university research (it requires an actual USML-category defense article or technical
data), but is real and binding where it applies — defense-sponsored research is the
typical trigger.

**OFAC sanctions, 31 CFR Chapter V (500–599 series)**, administered by Treasury's
Office of Foreign Assets Control. Maintains the **Specially Designated Nationals and
Blocked Persons (SDN) List** and comprehensive country embargoes. **Critically, OFAC
is not affected by the FRE or by either EAR or ITAR** — a real, primary-adjacent
source (Texas A&M's own Export Control Compliance Program Manual, Aug. 31, 2026 —
see §9 below) states this explicitly: *"the restrictions enforced by OFAC are not
affected by ITAR, EAR, or the FRE. OFAC restrictions and prohibitions generally arise
in connection with interactions involving certain individuals, entities and countries
most notably in interactions with embargoed countries and individuals/entities from
embargoed countries (i.e., Cuba, Iran, North Korea, Syria, Venezuela)."* This is a
distinct legal test from either export-control regime: it's about *who you transact
with*, not what technology you release.

**The restricted-party lists themselves** (per the same TAMU manual, which names its
actual screening software's target list set — the concrete, operational answer to
"what does restricted-party screening actually check," not a theoretical one):
- OFAC Specially Designated Nationals (SDN) List (Treasury)
- BIS Denied Persons List (Commerce)
- BIS Entity List (Commerce, 15 CFR Part 744) — parties posing a "significant risk of
  becoming involved in activities contrary to the national security or foreign policy
  interests of the United States"; a license is required for EAR-controlled items and
  most license exceptions are unavailable
- BIS Unverified List (Commerce) — parties BIS could not verify, requiring added
  due diligence, not an automatic bar
- State Department Arms Export Control Act (AECA) Debarred Parties List
- State Department Designated (Foreign) Terrorist Organizations
- State Department Nonproliferation Sanctions / Orders

**What does not apply, stated explicitly rather than left implicit:** this project
models a hiring/visiting-scholar/collaboration screening tool, not an international
shipping or customs-compliance system. Physical export licensing procedures for
tangible goods (carnets, customs declarations, denied-party screening of freight
forwarders) are out of scope — the *people and organizations* dimension of export
control (restricted-party screening) is the fit; the *goods movement* dimension is
not, and this project has no shipping/logistics data model to hang it on.

## 2. The user

**Two related but organizationally distinct roles, not one** — established from a
real institutional source, not assumed. Texas A&M's actual structure (per its Export
Control Compliance Program Manual, Aug. 31, 2026, `research.tamu.edu`):

- **Research Security and Export Controls (RESEC)** — a TAMU-level office. Conducts
  restricted-party screening, jurisdiction determinations, classification reviews,
  and export licensing. This is the export control officer role.
- **Research Security Office (RSO)** — a Texas A&M *System*-level office (the same
  level use-case-01's persona already sits at). The manual states RSO **licenses the
  restricted-party-screening software** that RESEC's authorized users operate, and
  that RESEC "will also assist with and conduct Restricted Party Screening (RPS)...
  and consult with... [RSO] on export control matters as needed."

These offices **cooperate on RPS specifically**, but export-control jurisdiction and
licensing determinations remain RESEC's alone. This means: a shared
restricted-party-screening capability serving both offices' workflows is a
defensible, real target for this project; a system that performs jurisdiction or
licensing determinations is not, and would be modeling RESEC's job away from a human
expert who is legally accountable for it (the manual designates a named "Empowered
Official" — TAMU's Vice President for Research — who is personally the point of
contact with federal agencies and bears responsibility for licensing decisions).

**Job to be done**, mirroring use-case-01 §3's format:

> When a department wants to hire a Foreign Person, host a visiting scholar, enter a
> research agreement, or ship/transfer controlled items or technology, I need to know
> whether the specific people and organizations involved appear on any U.S.
> government restricted-party list — so that I can clear the transaction, escalate an
> unresolved match for a RESEC determination, or flag it before the transaction
> proceeds, leaving a record that shows what was screened, against which lists, and
> when.

Note what this job story does *not* claim: it does not say "so that I can determine
whether an export license is required" — that remains RESEC's separate, non-automatable
job, exactly as use-case-01's job story never claims to determine legal coverage under
§51B.151 (see use-case-01 §12's "Coverage is an intake input, not a derived
conclusion").

## 3. Design principle — the same fact/judgment boundary, extended here

Use-case-01 §4 established that the system states observable facts and never
evaluates them: no risk score, no "confirmed" finding, no coverage determination. That
principle transfers directly and is, if anything, sharper here, because export control
carries **personal criminal liability** for a wrong call (the TAMU manual states
violations can mean "loss of research funding, loss of export privileges, as well as
criminal and civil penalties" for both the institution and the individual investigator).

What the system **can** state: *"Name X matches restricted-party-list entry Y at
confidence Z, sourced from list W, as of snapshot date D."* A candidate match with
evidence and a citation — exactly `ConcernTie`'s existing shape.

What the system **cannot** state, ever: whether a transaction is lawful, whether a
license is required, whether the Fundamental Research Exclusion applies to a given
project, whether an item is EAR- or ITAR-controlled, what ECCN or USML category
applies, or whether a "hit" is a true match versus a same-name coincidence — that last
one is RESEC's "secondary review" step, a human judgment call the manual describes
explicitly, not a confidence-threshold problem this system resolves on its own.

## 4. Is the reconciliation engine even the right mechanism? An honest assessment.

**No — and this is the central finding this document exists to state plainly**,
unlike step 6 (COI/NSPM-33), which use-case-01 §12 correctly calls "nearly free"
because it is *structurally identical* to the declaration-vs-discovered-record diff
already built. Restricted-party screening is not a disclosure-omission problem:
there is no "declaration" to reconcile against a "discovered record." A person either
is or is not currently on a list. It is a **point-in-time gate check**, not a
reconciliation.

Reading TAMU's actual described RPS procedure confirms this directly (§3(b) of its
manual, condensed):

1. Screen a name against the restricted-party lists via compliance software.
2. If there's a **possible match ("a hit")**, conduct a **secondary review** using
   additional identifying detail.
3. If the hit survives secondary review, **escalate to RESEC** with the matching
   criteria.
4. RESEC makes the determination and the outcome is **recorded**.

This is, near-exactly, the existing `ConcernTie` lifecycle already built for HB 127's
§51B.151(b) test: a candidate match (`ScreeningHit`, confidence-scored, evidence-
carrying) → a worksheet row → an analyst action with a controlled reason vocabulary →
a recorded disposition. **The reusable primitive is the concern-list-matching engine
itself** (`screening/lists.py:EntityOfConcernList`, `resolution/matcher.py:score_pair`,
the `ConcernTie` type), not the `Finding`/reconciliation-diff machinery that step 6
reuses. This is exactly the distinction the review instructions asked this document to
establish rather than assume.

**Where it doesn't fit at all:** the `Case`/`Subject`/`Declaration` model is built
around one specific triggering event (a hiring/access decision under §51B.151) for one
specific person. RPS's real trigger population, per TAMU's own Section 3(a) "Red
Flags," is far broader — see §5 below. Forcing every RPS trigger through the HB 127
`Case` shape would be the same mistake the requirements document's §9c retrospective
already diagnosed once (a tool built around one dataset's shape, not the job actually
being done) — worth naming explicitly rather than repeating quietly.

## 5. What triggers screening, and against what

Per TAMU's own "Export Control Red Flags" (§3(a) of its manual) and its per-scenario
procedures, restricted-party screening is triggered by **several structurally
different events**, not one:

| Trigger | Who/what gets screened | TAMU's real procedure |
|---|---|---|
| Foreign Person new hire | The person, their affiliated institution/organization **going back five years**, and any personal/professional references provided | Export Control Review and Certification Form; RPS on all of the above; unresolved hits go to RESEC |
| Visiting scholar | The visitor and their affiliated institution | Form 5VS (**the same form use-case-01's demo case already cites** — `entity_screening/case/demo.py`'s `trigger` field literally reads *"Visiting scholar appointment, Division of Research review (Form 5VS + HB 127)"* — a real, independently-confirmed overlap between the two use cases' actual triggering events, not a coincidence this document invented) |
| Research agreement / sponsor contract | Contract provisions themselves (publication restrictions, foreign-national participation bars, CUI clauses) — a document-content review, not a name screen | Decision-tree review against a list of "provisions of concern" |
| International shipment | The item and destination | Jurisdiction/classification review, not primarily RPS |
| Purchasing / financial transaction | The counterparty | RPS |
| Distance-education enrollment | The student's declared location at registration | An automated alert when a student registers from an embargoed country or "country of concern," reviewed by RESEC |
| Travel | Destination country, items carried | Separate review, largely outside this project's scope (no travel data model exists here) |

**Consequence for the data model:** unlike HB 127's single "hire a covered person"
trigger, RPS's real unit of work is **a party (person or organization) to be screened
at any of several trigger events**, not a `Case` in the HB 127 sense. A generalized
"screenable party" concept — closer in shape to how `tie_from_ownership` and
`ties_from_own_affiliations` already scan names against concern lists independent of
the `Case`/`Finding` machinery — is likely the better fit than stretching `Subject`/
`Declaration` to cover shipments and purchase orders. This is a design question for
the implementation-planning stage, not resolved here, but flagged with its real basis
rather than left for that stage to rediscover.

## 6. Three different "list of countries," not one — a real distinction this project must not blur

This project already has a country-classification mechanism (`screening/
adversary_list.py`, step 4). It would be a real error to assume it also answers
export-control's country questions. It does not — confirmed by comparing the actual
lists:

| Concept | Source | Current membership (as verified) | Legal test |
|---|---|---|---|
| **Foreign adversary** (HB 127, step 4, already built) | DNI Annual Threat Assessments + (unused) gubernatorial designation | China, Russia, Iran, North Korea | Tex. Educ. Code § 51B.001 — triggers *screening coverage*, not a transaction bar |
| **OFAC comprehensively embargoed** | OFAC sanctions programs (31 CFR 500 series) | Cuba, Iran, North Korea, Syria, Venezuela (per TAMU's own manual's characterization — its narrower "comprehensive embargo" framing, not OFAC's full program list, which also includes non-comprehensive/sectoral programs for other countries) | Transactions with the country/its nationals are generally prohibited absent a license |
| **EAR destination control** | BIS country groups (15 CFR Part 740, Supplement 1) | A tiered, ECCN-dependent list far broader than either of the above | License requirement depends on *both* the ECCN and the destination country |

Note the overlap is partial, not total: **Iran and North Korea appear on all three;
China and Russia are step-4 adversary countries but not OFAC-comprehensively-embargoed;
Cuba, Syria, and Venezuela are OFAC-embargoed but not DNI-ATA adversary countries.**
Treating these as one list, or wiring step 4's `AdversaryCountryList` into an
export-control check, would silently misstate which regime actually governs a given
determination — a real, concrete failure mode this document exists to name before it
gets built by accident. If an OFAC-embargoed-country check is ever built, it needs its
own curated list, sourced from OFAC's own program pages, not step 4's file.

## 7. What's already reusable versus genuinely new

**Directly reusable, no new mechanism needed:**
- `screening/lists.py:EntityOfConcernList` / `resolution/matcher.py` — the whole
  candidate-match-with-confidence-and-evidence primitive.
- `ConcernTie`'s type shape and worksheet/adjudication lifecycle (candidate → analyst
  action with a controlled reason → recorded disposition) — matches TAMU's real
  described RPS procedure closely enough that this is a strong, not speculative, fit.
- OpenSanctions' consolidated dataset, **confirmed** (via OpenSanctions' own dataset
  pages) to already include: the OFAC SDN List, the BIS Denied Persons List, the State
  Department AECA Debarred Parties List, and State Department Designated (Foreign)
  Terrorist Organizations — four of the seven lists TAMU's own manual names, already
  flowing through this project's existing `OpenSanctionsList` machinery today, for
  free.
- The manifest/provenance pattern (`GleifSnapshotManifest`/`AdversaryListManifest`) if
  a new curated snapshot is needed for a gap list — same "hand-curated, versioned,
  re-verified on a schedule" discipline as `dod_1260h.json` and
  `adversary_countries.json`.

**Resolved during implementation planning, against real data, not left open:** the
**BIS Entity List**, **BIS Unverified List**, and **State Department Nonproliferation
Sanctions/Orders** are all confirmed present in OpenSanctions' consolidated
`targets.simple.csv` export this project already downloads — via `us_trade_csl`, the
U.S. government's own official Consolidated Screening List, itself one of the
`default` collection's member sources. Downloaded the real `us_trade_csl` file
directly and inspected its `program_ids` column: `US-BIS-EL`, `US-BIS-UVL`, and
`US-DOS-ISN` are all present (plus `US-BIS-DPL`, `US-AECA-DEBARRED`, and a bonus
`US-BIS-MEU` not named above). **No new curated snapshot is needed** — unlike DoD
1260H or step 4's adversary list, every list this document names already flows
through the existing `OpenSanctionsList` machinery unmodified. See
`docs/plans/2026-09-14-restricted-party-screening.md` for the full verification and
`docs/data_sources.md` for the citation.

**Definitely genuinely new, and explicitly out of scope for this system regardless:**
jurisdiction determination, ECCN/USML classification, license applications, Technology
Control Plans, and Acknowledgement-of-Publication/Personnel-Restriction determinations
— all of §1's "problem (2)," RESEC's exclusive, non-automatable domain (§3 above).

## 8. Open questions

- ~~**The BIS Entity List / Unverified List / Nonproliferation Sanctions coverage
  question (§7)**~~ — resolved during implementation planning against the real
  `us_trade_csl` file; see §7 and `docs/plans/2026-09-14-restricted-party-screening.md`.
- ~~**What "screenable party" should actually look like as a type.**~~ — resolved:
  built as `ScreeningEvent`/`ScreeningParty`/`ScreeningMatch`/`ScreeningDisposition`
  in `entity_screening/screening/rps_schema.py`; see the plan doc for the design.
- **Whether/how the "affiliated institution/organization going back five years"**
  requirement (TAMU's real practice for Foreign Person hires) maps onto this
  project's existing `DeclaredAffiliation` data, if a hiring-trigger screening reuses
  declaration data already collected for HB 127 rather than asking for it twice.
- ~~**Whether a disposition-recording type analogous to `WorksheetAction`**~~ —
  resolved: built new, `ScreeningDisposition` with its own `RPS_DISMISS_REASON_CODES`/
  `RPS_ESCALATION_REASON_CODES` vocabulary (`case/vocab.py`), reusing only
  `WorksheetActionKind` itself (the dismiss/escalate/etc. action vocabulary, not
  RPS-specific).
- **Whether OFAC-embargoed-country screening is in step 5's scope at all** — resolved
  for this pass: no, explicitly out of scope, documented in code
  (`screening/rps_schema.py`'s module docstring) and covered by a negative-space test.
  Still open whether it ever gets its own narrower slice later.
- **What A&M's real single-visit-triggers-both-processes overlap (§5's Form 5VS
  finding) implies for sequencing.** If a visiting-scholar case already exists in this
  system for HB 127, does an RPS check attach to that same case, or does it stay a
  fully separate screening pass that happens to share a trigger event? Real
  operational data (TAMU screens the visitor **and** their affiliated institution via
  RPS, separately from and in addition to the HB 127 background check) suggests
  "attaches to the same event, produces separate observations" — worth testing against
  the same two-discovery-paths lesson use-case-01 §12 already learned once
  (`docs/plans/2026-09-06-concern-ties-as-a-distinct-observation.md`), not re-derived
  from scratch.

## 9. Sources referenced

- [15 CFR § 734.13 — Export (EAR deemed-export rule)](https://www.law.cornell.edu/cfr/text/15/734.13)
- [15 CFR § 734.8 — Fundamental research (EAR)](https://www.law.cornell.edu/cfr/text/15/734.8)
- [22 CFR § 120.34 — Fundamental research (ITAR)](https://www.law.cornell.edu/cfr/text/22/120.34)
- [22 CFR § 121.1 — The United States Munitions List](https://www.ecfr.gov/current/title-22/chapter-I/subchapter-M/part-121)
- Texas A&M University, *Export Control Compliance Program Manual*, August 31, 2026 —
  `research.tamu.edu/wp-content/uploads/2025/04/2025-EC-Manual-2025.08.29.pdf` — the
  primary real-world operational source for §2, §4, §5, and the OFAC embargoed-country
  characterization in §1 and §6.
- OpenSanctions dataset pages: `opensanctions.org/datasets/sanctions/`,
  `opensanctions.org/programs/US-BIS-EL/`, `opensanctions.org/programs/US-BIS-DPL/`,
  `opensanctions.org/programs/US-BIS-UVL/` — for §7's reused-vs-new determination.
- `docs/use-case-01-hb127-researcher-screening.md` — structural template and the
  fact/judgment boundary principle extended here.
