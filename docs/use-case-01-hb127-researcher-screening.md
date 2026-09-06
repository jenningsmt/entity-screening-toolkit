# Use Case 01 — HB 127 Foreign Researcher Screening

**Status:** User and workflow definition. Approved in principle; no schema or interface work has started against it.
**Date:** September 5, 2026
**Scope:** Texas HB 127 (89th Legislature) screening of researchers and research-support personnel, as it would be operated by a research security office in a large public university system — Texas A&M System institutions used as the concrete reference throughout.

**What this document is for.** `docs/requirements.md` Section 4 names the project's users as *"Mike, running it against real public data as a hands-on exercise"* and *"anyone evaluating it as a portfolio piece."* That is an audience, not a user with a job to be done, and building against it produced a corpus-screening tool that no research security analyst would have a use for (see `docs/how-this-was-built.md`, Phase 5). This document supplies what Section 4 lacked, for one use case, and is deliberately written **before** any schema or interface work.

**Method note.** Every requirement traceable to statute quotes the operative text rather than paraphrasing it. Where this document states a design position rather than a statutory requirement, it says so.

---

## 1. Statutory basis

Three provisions do the work. Quoted from the enrolled text.

**Who is covered — §51B.151(a).** Screening is required *before* an offer or an access grant:

> "Before offering a person employment for a research or research-related support position at the institution or granting a person access to research data or activities or other sensitive data of the institution, an institution of higher education must screen the person as provided by this subchapter if the person: (1) is a citizen of a foreign country and is not a permanent resident of the United States; or (2) is affiliated with an institution or program, or has at least one year of employment or training, in a foreign adversary, other than employment or training by an agency of the United States."

**What is collected — §51B.152:**

> "An institution of higher education must require a person subject to screening under Section 51B.151 to submit to the institution: (1) if the person is a citizen of a foreign country, a copy of the person's passport and nonimmigrant visa application most recently submitted to the United States Department of State; and (2) any additional information as determined by the council."

**What the office does, and the bar — §51B.153:**

> "The chief administrative officer of an institution of higher education shall establish a research security office to: (1) review the materials submitted to the institution by a person under Section 51B.152; (2) take reasonable steps to verify the information in the submission; and (3) take any other action the office considers appropriate."

> "An institution of higher education may not employ a person subject to screening under Section 51B.151 in a research or research-related support position if the person **fails to disclose in the submission a substantial educational, employment, or research-related activity, publication, or presentation** unless the applicable department head or the department head's designee **certifies in writing** the substance of the failure to disclose and the reasons for disregarding that failure. A copy of the certification must be kept in the **investigative file of the research security office**."

**Foreign adversary — §51B.001:** a country identified by the DNI as posing a national security risk in at least one of the three most recent Annual Threat Assessments, or designated by the governor after consulting the DPS director.

### 1.1 Four consequences that shape everything below

1. **The disqualifying condition is an omission, not a risk.** The employment bar triggers on failure to disclose a substantial activity — not on nationality, not on affiliation, not on a concern-list hit. This is a **declaration-versus-record reconciliation** problem.
2. **"Substantial" is undefined**, the statute is months old, and no settled institutional practice exists. See §4.
3. **A covered person may have no DS-160.** §51B.151(a)(2) catches anyone — U.S. citizens included — with a foreign-adversary institutional affiliation or ≥1 year of employment/training there, but §51B.152(1) requires passport and visa application only "if the person is a citizen of a foreign country." A DS-160-first data model is wrong on day one.
4. **The statute names the output artifact:** the "investigative file," and mandates one document within it — the department head's written certification when a non-disclosure is disregarded.

---

## 2. The user

**Role:** research security analyst, Division of Research, a Texas A&M System institution.

**Where they sit.** A&M's existing visiting-scholar review (Form 5VS) is initiated by the faculty host, routed through department head and college dean, then to the Division of Research, which "screen[s] the application for export controls, research security, and other compliance requirements." HB 127 adds passport and visa application to the packet and a statutory completion deadline. The analyst is the last gate before an offer or an access grant.

**Working conditions that the design has to respect:**

- **They work a queue, not a corpus.** Cases arrive one subject at a time with deadlines attached.
- **They are between two failure modes.** A wrong clear is a research security failure. A wrong flag is an unfair barrier to a legitimate scholar, and — at volume — a reputational and recruiting problem for the institution. Neither error is cheap.
- **They are under schedule pressure from someone who outranks them.** The host wants their visitor to start. The dean already approved. The analyst is the one saying "wait."
- **Their work product must survive an audit** by someone who was not present and is reading it years later.
- **They are not the decision-maker on employment.** They assemble and assess; the department head certifies; the institution employs or doesn't.

**What they bring that the system cannot.** Judgment about what matters in context — whether a two-year postdoc at a named institution twelve years ago is meaningful for this person in this role, or noise. That judgment is the job. The system's role is to make it *possible and fast*, not to pre-empt it.

---

## 3. Job to be done

> When a department wants to bring on a researcher covered by §51B.151, I need to establish whether their declaration is complete and whether they have ties to a foreign adversary that would compromise the security or integrity of our research data — so that I can clear, escalate, or refer the case before the statutory deadline, leaving a file that a future auditor can follow without me in the room.

**The decision being supported:** the analyst's assessment and recommendation, feeding the department head's certification decision and the institution's employ / grant-access decision.

**The decision the system never makes:** any of the above.

---

## 4. Design principle — the fact/judgment boundary

This is the central design commitment of this use case and it is binding, not aspirational.

**The problem it solves.** "Substantial" is undefined in statute and unsettled in practice. A tool that hard-coded a materiality threshold would be asserting a standard the legislature declined to set, and would be wrong differently at every institution. But a tool that surfaced every discrepancy undifferentiated would be worse: a mid-career researcher legitimately generates dozens of affiliations absent from a five-year disclosure window (see §6), the worksheet becomes noise, and the analyst learns to skim it. **Refusing to judge cannot mean refusing to organize.**

**The line.** The system states observable facts about each discrepancy and never evaluates them.

**Assertions the system may make** — each is checkable against a source:

- which declaration sources were searched for this item, and the stated scope of each
- whether the item falls **inside** a declaration source's scope window (its absence is a gap in a document that asked for it) or **outside** it (its absence may be an artifact of the form's scope)
- measurable attributes: number of supporting records, first and last observed dates, authorship position, publication venue
- the country of an affiliation, and whether that country is on the foreign-adversary list — **with the list version and derivation cited**
- a name match against a concern list, with confidence, matched variant, matched field, and the matched entry's own record inlined (existing Epic D machinery, unchanged)
- an ownership relationship from a declared employer to a parent entity, with the traversal path and its truncation/branching status (existing Epic C machinery, unchanged)

**Assertions the system may not make, ever:**

- that an omission is or is not *substantial*
- that a person is or is not a risk
- any aggregate number presented as a risk score for a person
- any ranking of subjects against one another
- any recommended disposition

**Enforcement, not convention.** `MatchStatus` has exactly one member so that "confirmed" is unrepresentable in code rather than merely discouraged in documentation (`docs/architecture.md`, "Why no 'confirmed' status is possible"). The same mechanism applies here: the `Finding` type carries **no severity, risk, priority or score field at all**. An evaluative claim about a person is not a thing the schema can hold. `cli.py validate` asserts this, so CI fails if anyone adds one.

**Note on the existing scoring rubric.** Epic F's user-editable weights and factor decomposition have no role in this use case — there is no statutory concept of a risk score, and an analyst needs "these three affiliations are absent from the declaration, here is the evidence" rather than "this subject scored 73." The rubric machinery may survive as **queue-ordering for triage** (which case to work first) or as **materiality configuration** (which classes of discrepancy to surface by default), both of which are properties of the *worklist*, not claims about a person. It does not survive as output.

### 4.1 The by-product worth building for

Because materiality is undefined, every disposition should record **which discrepancies the analyst dismissed and on what stated basis**. Over months the office accumulates its own case law: an evidence-backed answer to "how does your institution define substantial?" drawn from actual adjudications rather than a policy guessed at in 2026. This falls out of the adjudication model at no extra cost and is likely the single most defensible artifact the system produces.

---

## 5. Case lifecycle

The unit of work is a **case**: one subject, one triggering event, one deadline, one file.

| State | Enters when | Leaves when |
|---|---|---|
| **Intake** | A covered hire or access request is raised | Subject, trigger, requested access scope and statutory deadline are recorded |
| **Declaration assembly** | Intake complete | All available declaration sources are attached, each tagged with its own scope (see §6) |
| **Discovery** | Declaration assembled | Reconciliation has run against all discovery sources (§7) |
| **Worksheet** | Discovery complete | **Every row has an analyst action.** No exceptions — this is the closure rule |
| **Adjudication** | Worksheet complete | Analyst records an assessment and recommendation, attributed and timestamped |
| **Outcome** | Adjudication recorded | Institutional outcome recorded: cleared / cleared with §51B.153 certification / not cleared / withdrawn |
| **Closed** | Outcome recorded | — file is exportable as the investigative file |

**Statutory constraint on the lifecycle:** the case must reach Closed *before* the offer is made or access is granted. The deadline is captured at Intake and is a first-class field, not a note.

**Re-opening.** A closed case re-opens on new information (a later disclosure, an updated adversary list, a new publication). Re-opening creates a new adjudication rather than editing the prior one — the earlier assessment stays intact and readable, because it was correct given what was known then. This mirrors the `ExportManifest` discipline already in the codebase.

---

## 6. The declared set

**The trap this section exists to prevent.** The DS-160's previous-employment section covers **five years**. Education is frequently only the highest qualification. A mid-career researcher has fifteen years of entirely legitimate affiliations that will never appear on that form. A naive diff of DS-160 against a publication record produces an omission alert for nearly every affiliation older than five years — a false-positive generator that would train the analyst to distrust the tool. This is the same class of failure as the `Chinese Academy of Sciences` / `Chinese Academy of Ordnance Science` false positive documented in `docs/data_sources.md`, but structural rather than incidental.

**Therefore the declared set is a merge of sources, each carrying its own scope**, and every discrepancy states which sources were searched and what each covers:

| Source | Statutory basis | Scope it actually covers |
|---|---|---|
| DS-160 (visa application) | §51B.152(1), foreign citizens only | 5yr employment; highest education; professional/social/charitable org memberships; specialized skills and training; military service; other nationalities; countries visited (5yr) |
| Passport | §51B.152(1), foreign citizens only | Identity, nationality, travel |
| Institutional supplemental disclosure | §51B.152(2), "as determined by the council" | Not yet defined — see §11 |
| Form 5VS + CV | Institutional practice (A&M already requires "an up to date resume or CV in English") | Full career history — in practice the only source covering pre-5-year affiliations |

**Design position:** the CV is load-bearing, not supplementary. It is the only routinely-collected document whose scope matches the statute's test, which is broader than any single form asks for. A system that treats DS-160 as *the* declaration will be wrong in the majority of cases.

**A covered subject may have no DS-160 at all** (§1.1, consequence 3). The declaration model must be complete and functional with the DS-160 absent.

---

## 7. The discovered set

Reference data the declaration is reconciled against. All public; all already in the codebase except the last.

| Source | Answers | Status |
|---|---|---|
| OpenAlex | Publications, presentations, co-authorship, institutional affiliation history — i.e. the statute's "research-related activity, publication, or presentation" verbatim | Built (Epic E) |
| GLEIF Level 1 + 2 | Declared employer → ultimate parent, and cross-jurisdiction control | Built (Epic C) |
| OpenSanctions | Restricted-party and PEP matching; also carries all seven "Seven Sons" universities | Built (Epic D) |
| DoD Section 1260H | Chinese military companies | Built (Epic D) |
| NSF Award Search | Prior U.S. federal funding by PI name — **repurposed from input corpus to discovery source** | Built, needs repointing |
| Foreign adversary list | §51B.001 country determination | **New** — derived from the three most recent DNI Annual Threat Assessments plus gubernatorial designations |

**Two notes on the discovery sources.**

*The bibliometric layer becomes the core.* Epic E was the project's most speculative and technically difficult component, sequenced last as the highest-risk piece. Under this use case it is the primary evidence source for the statutory test, because "publication, or presentation" is precisely what OpenAlex holds. Its existing precision caveats and author-disambiguation tie-handling become more important, not less.

*The ownership graph finally earns its place.* Epic C previously had the weakest justification — a corporate parent/subsidiary chain is not obviously relevant to screening NSF awardees. Under this use case it produces the single most valuable finding shape available: **a declared employer whose ultimate parent is on a concern list**, which no amount of name matching against the declared name alone would surface.

**The adversary list is versioned and moves.** A rolling three-ATA window means the list in 2026 differs from 2028. A determination made under one version must remain traceable to it. This is the `GleifSnapshotManifest` problem exactly, and the existing manifest machinery handles it.

---

## 8. The worksheet

The analyst's working surface is a worksheet of discrepancies, **one row per finding, not one per subject**.

**Row contents:**

- the discovered fact (with its source and evidence links)
- the declaration sources searched, and the stated scope of each
- **why it surfaced** — the factual basis, per §4
- measurable attributes (record count, date range, authorship position, country, list version)
- concern-list or ownership evidence where applicable, with confidence and matched-entry record inlined
- the analyst action
- the stated reason for that action
- actor and timestamp

**Analyst actions:** dismiss (reason required) · request clarification from the subject · escalate for further review · flag as requiring §51B.153 department-head certification.

**Closure rule:** a case cannot leave the worksheet state while any row is unactioned. This is what makes the exported file defensible — not that the case was reviewed, but that every item was dispositioned by a named person on a stated basis.

**Bulk action is a requirement, not a convenience.** An analyst must be able to dismiss an entire class in one action with one reason — e.g. all items falling outside the DS-160's five-year window. Without it the volume defeats the worksheet, and §4's fact-based classification exists precisely to make such classes selectable.

**The worked worksheet plus its adjudication is the investigative file.** Export produces that file, not a table of matches.

---

## 9. Data handling

DS-160 content is among the more sensitive personal data an institution holds: date of birth, passport and national ID numbers, home address, salary, parents' identities, social media handles. `docs/requirements.md` Section 3 states this project handles no sensitive non-public data of any kind, and that non-goal stands.

**Consequences, binding:**

- **No real declaration data, ever, in this build.** Demo and test subjects are synthetic (§10).
- **The architecture is nonetheless built as though for real data**, because designing that is the demonstrable skill: field-level sensitivity classification on the declaration model, redaction by default in exports, and no personal data written into manifests or logs — which currently record dataset provenance only, and must stay that way.
- **The declaration is modeled and displayed as a structured affiliation list, not as a DS-160 replica.** The reconciliation needs only the affiliation-bearing fields. A filled visa-application form rendered beside a findings panel on a public URL reads as a template for doing this to real people, at no functional gain.

---

## 10. Demo data strategy

**The split is clean rather than compromised: real reference data, synthetic person.**

- **Real:** publications, institutional records, concern lists, ownership chains, adversary-country determinations. All public, all already in the repository.
- **Synthetic:** the subject and their declaration. Fabricated entirely.
- **Never:** a real author's publication record attached to a fictional name. Anyone who looks up the papers finds the real person, and the result is a screening dossier on them with deniability attached — worse than either honest alternative.

**The primary demo finding requires no publication record at all:**

> *Declared employer: [synthetic Chinese subsidiary]. Not disclosed: that entity's ultimate parent, per GLEIF Level 2 relationship data, appears on the DoD Section 1260H list.*

This runs on a synthetic declaration plus wholly real GLEIF and 1260H reference data. No fabricated publications, no real person, and it gives Epic C the demonstration it has never had. A second finding driven by a clearly-labeled bibliometric fixture exercises Epic E without attributing real work to a fictional author.

---

## 11. Open questions and external dependencies

- **What the council determines** under §51B.152(2). The supplemental declaration's content is set partly by a state body, not the institution. Until it publishes, the institutional-disclosure source in §6 is a shape rather than a specification.
- **How "substantial" settles in practice.** Tracked deliberately as §4.1 rather than resolved.
- **Where the research security office sits in a system.** §51B.153 places the duty on "the chief administrative officer of an institution of higher education." The A&M System comprises eleven universities and eight state agencies; whether that means nineteen offices, a shared service, or something between is a real architectural question (single-tenant vs. multi-tenant) and is currently unknown.
- **Turnaround expectations.** A&M's published visiting-scholar process states no timeline. The statutory deadline is an event ("before offering... or granting"), not a duration, so the operative constraint is the host's hiring date.
- **The adversary-country list must be derived and verified** against the three most recent DNI Annual Threat Assessments before it is used for anything, including the demo.

---

## 12. Build sequencing

Bundling with export control and COI review is the eventual goal; sequencing keeps it manageable. The vertical slice that is genuinely useful and demoable is **one subject, one declaration, a worked reconciliation worksheet, an exportable file** — everything after step 3 is breadth on that spine.

1. `Subject`, `Declaration`, `DeclaredAffiliation`, and the case shell
2. Reconciliation engine and the worksheet
3. Adjudication, §51B.153 certification, investigative-file export
4. Foreign-adversary list ingester and the concern-list / ownership layer — cheap; the machinery exists
5. Export-control and restricted-party screening bundled into the same review (A&M performs these together today)
6. COI and NSPM-33 disclosure reuse

**Step 6 is nearly free and worth stating now:** an annual conflict-of-interest disclosure is structurally identical to a §51B.152 declaration — a self-reported affiliation set to be reconciled against the record. The same engine serves NSPM-33 disclosure verification with no new matching logic. That is the argument for bundling, and it is why the reconciliation engine should be built against a general `Declaration`, not against a DS-160.
