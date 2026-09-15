"""Canonical internal data model shared by every pipeline stage.

Every dataclass here is immutable, and MatchStatus deliberately has a single
member: this project never asserts a confirmed finding (docs/requirements.md
Section 10 — "candidate," "potential," and "unconfirmed" are enforced in the
data schema itself, not left to documentation to clarify).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any


class MatchStatus(Enum):
    CANDIDATE_MATCH = "candidate_match"


@dataclass(frozen=True)
class SourceRecord:
    """One raw record as ingested from an external dataset, before resolution."""

    source_dataset: str
    retrieval_date: date
    source_record_id: str
    fields: dict[str, Any]


@dataclass(frozen=True)
class ResolvedEntity:
    """A single logical entity, resolved from one or more SourceRecords."""

    entity_id: str
    canonical_name: str
    entity_type: str
    source_records: tuple[SourceRecord, ...]


@dataclass(frozen=True)
class MatchCandidate:
    """A candidate match between two name strings — always a scored confidence,
    never a bare boolean."""

    left_name: str
    right_name: str
    confidence: float
    match_basis: str
    status: MatchStatus = MatchStatus.CANDIDATE_MATCH


@dataclass(frozen=True)
class ScreeningHit:
    """A resolved entity's candidate match against one entity-of-concern list.

    `producer` names which pipeline *stage* produced this hit
    ("direct_name" / "section_117" / "bibliometric") -- distinct from
    `matched_field`, which stays the finer-grained distinction within a stage
    (e.g. a PI's own past affiliation vs. a co-author's institution, both
    "bibliometric"). storage.insert_screening_hits groups by `producer` to
    delete-and-replace only the calling stage's own rows on a re-run, since
    screening_hits serves three producers with three different lifecycles and
    a bare `DELETE WHERE run_id = ?` would also wipe the other two stages'
    hits for that run."""

    entity_id: str
    list_name: str
    matched_variant: str
    matched_field: str
    confidence: float
    evidence: dict[str, Any]
    status: MatchStatus = MatchStatus.CANDIDATE_MATCH
    producer: str = "direct_name"


@dataclass(frozen=True)
class OwnershipMatch:
    """A resolved entity's match against a GLEIF LEI record — a name-to-LEI match
    is exactly as uncertain as a screening-list match, so it carries the same
    confidence score and MatchStatus, never a bare LEI string (Epic C)."""

    entity_id: str
    lei: str
    legal_name: str
    legal_jurisdiction: str
    confidence: float
    match_basis: str
    status: MatchStatus = MatchStatus.CANDIDATE_MATCH


@dataclass(frozen=True)
class ForeignControlFlag:
    """Flags that a resolved entity's ultimate parent (per GLEIF Level 2 data) is
    registered in a different jurisdiction than the entity itself (Epic C). Everything
    here inherits the uncertainty of the underlying OwnershipMatch — including whether
    the parent chain was truncated before reaching a genuine top — so it's evidence
    to review, never an assertion.

    One entity can legitimately produce more than one of these: a real GLEIF
    ownership graph can branch (more than one active
    `IS_DIRECTLY_CONSOLIDATED_BY` edge from a given entity), so
    `ownership/flagging.py:flag_from_match` emits one flag per distinct
    foreign ultimate parent rather than picking one arbitrarily —
    `relationship_path` here is always one specific, real path that exists in
    the data, never a flattened/ordering-artifact stand-in for "the" chain,
    which is the adjacent honesty problem to `truncated` that an earlier
    version of this type didn't anticipate (see
    `ownership/graph.py:ParentChain`'s docstring)."""

    entity_id: str
    entity_lei: str
    entity_jurisdiction: str
    ultimate_parent_lei: str
    ultimate_parent_name: str
    ultimate_parent_jurisdiction: str
    relationship_path: tuple[str, ...]
    match_confidence: float
    evidence: dict[str, Any]
    status: MatchStatus = MatchStatus.CANDIDATE_MATCH


@dataclass(frozen=True)
class ResolvedAuthor:
    """A resolved entity's PI, disambiguated to an OpenAlex author identity (Epic E).

    Genuinely new, not representable as ScreeningHit: this is an identity-resolution
    result (which real-world person is this?), not a concern-list match — same
    reasoning as OwnershipMatch (GLEIF's name-to-LEI resolution) above. Real OpenAlex
    data shows a PI name can genuinely tie between multiple distinct author records
    even after filtering to a specific institution (see
    docs/plans/2026-09-01-v3-openalex-bibliometric-affiliation-layer.md's Finding 3),
    so `disambiguate_pi_to_openalex_author` returns one ResolvedAuthor per surviving
    candidate, not a single forced pick -- `evidence` carries the full tie context
    (other tied candidate IDs, shared ORCIDs) so a genuine ambiguity is visible, not
    hidden."""

    entity_id: str
    pi_name: str
    openalex_author_id: str
    display_name: str
    confidence: float
    match_basis: str
    evidence: dict[str, Any]
    status: MatchStatus = MatchStatus.CANDIDATE_MATCH


@dataclass(frozen=True)
class TopicSimilarityFlag:
    """A paper's topic resembles a named critical-technology area (deferred VSS
    work, docs/plans/2026-09-01-vss-topic-similarity-layer.md).

    Deliberately NOT a ScreeningHit and carries no MatchStatus: a semantic-
    similarity signal can establish that a paper's topic *resembles* a technology
    area description, but it cannot establish that the paper has any actual
    application or risk -- that judgment genuinely needs a subject-matter expert,
    not this system. This type is advisory-only and is never read by
    scoring/score.py -- it does not and must not contribute to an entity's
    numeric score, by design, not by omission."""

    entity_id: str
    pi_name: str
    openalex_work_id: str
    work_title: str
    technology_area: str
    corpus_tier: str  # "primary" (DoD) or "secondary" (CET) -- never blended
    similarity_score: float
    evidence: dict[str, Any]
    recommendation: str = (
        "Topically similar to a named critical-technology area; consult a "
        "subject-matter expert to assess actual relevance -- this signal "
        "establishes topical resemblance only, not application or risk."
    )


@dataclass(frozen=True)
class ScoreBreakdown:
    """A total score decomposed into its contributing factors — never an opaque
    single number without a breakdown available."""

    total: float
    factors: dict[str, float]


@dataclass(frozen=True)
class ScoredEntity:
    entity_id: str
    canonical_name: str
    score: ScoreBreakdown
    screening_hits: tuple[ScreeningHit, ...]
    run_id: str
    ownership_flags: tuple[ForeignControlFlag, ...] = ()


# ---------------------------------------------------------------------------
# Case model (Use Case 01 -- HB 127 researcher screening).
#
# docs/use-case-01-hb127-researcher-screening.md is the specification;
# docs/plans/2026-09-06-use-case-01-implementation.md is the plan. The unit
# of work is a *case*: one subject, one triggering event, one deadline, one
# file. The statutory test is a failure to disclose, so this is a
# declaration-versus-record reconciliation problem, not screening-and-scoring.
#
# Two structural commitments, both enforced here rather than in documentation:
#
#   1. The fact/judgment boundary (use-case doc Section 4). The system states
#      observable facts and never evaluates them. The observation types --
#      Finding (the Sec. 51B.153 omission test) and ConcernTie (the
#      Sec. 51B.151(b) tie test) -- and every type in their graphs carry no
#      severity, risk, priority, score, materiality, tier, weight,
#      disposition or "would prevent / impair" field.
#      _OBSERVATION_GRAPH_ALLOWED_FIELDS below is the frozen allowlist;
#      cli.py `validate` fails CI if any of these types grows a field not on
#      it. This is the same mechanism as MatchStatus's single member,
#      applied to two more kinds of assertion -- guarding the whole graph,
#      not just the outer shell, because an evaluative field added to
#      DiscoveredAffiliation would reach the export just as surely.
#
#   2. No real PII, ever, in this build (use-case doc Section 9,
#      requirements Section 3). Subject and Declaration reject synthetic=False
#      in __post_init__ -- "no real PII by construction," not by policy.
# ---------------------------------------------------------------------------


class CoverageBasis(Enum):
    """Which limb of HB 127 Sec. 51B.151(a) brings a subject under screening.

    Recorded at intake by whoever opens the case -- never inferred by the
    system. Whether a person is subject to screening is a legal
    determination, not an observable fact, so Section 4's fact/judgment
    boundary keeps the system out of it (use-case doc Section 12).
    """

    FOREIGN_NATIONAL_NO_PR = "151a1"  # foreign citizen, not a US permanent resident
    FOREIGN_ADVERSARY_TIE = "151a2"  # foreign-adversary affiliation, or >=1yr employment/training


class CaseKind(Enum):
    """Which disclosure regime a `Case` belongs to. Added for step 6 (annual
    COI/Outside-Interest disclosure reuse, docs/use-case-03-coi-annual-
    disclosure-reuse.md) so the shared worksheet/adjudication engine can pick
    the right escalation-reason vocabulary (case/vocab.py) without inferring
    it from `coverage_basis` being absent. Defaults to the original HB-127
    kind so every pre-existing call site is unaffected."""

    HB127_RESEARCHER_SCREENING = "hb127_researcher_screening"
    COI_ANNUAL_DISCLOSURE = "coi_annual_disclosure"


class CaseState(Enum):
    """The case lifecycle (use-case doc Section 5). A case must reach CLOSED
    before an offer is made or access is granted."""

    INTAKE = "intake"
    DECLARATION_ASSEMBLY = "declaration_assembly"
    DISCOVERY = "discovery"
    WORKSHEET = "worksheet"
    ADJUDICATION = "adjudication"
    OUTCOME = "outcome"
    CLOSED = "closed"


@dataclass(frozen=True)
class Subject:
    """The person a case is about. PII-bearing; `classified_fields` holds the
    sensitive declaration attributes (DOB, passport/national-ID numbers, home
    address, ...) and is redacted by default on export.

    `synthetic` must be True: this build never handles real declaration data
    (use-case doc Section 9). The guard is in __post_init__ so a real subject
    is unrepresentable, not merely discouraged.

    `coverage_basis` is `None` for a subject who has never had an HB-127 case
    opened for them (e.g. a subject known only through an annual COI
    disclosure cycle, step 6) -- `CoverageBasis` names a specific HB 127
    Sec. 51B.151(a) limb and has no member that applies otherwise.
    """

    subject_id: str
    display_name: str
    coverage_basis: CoverageBasis | None
    synthetic: bool
    classified_fields: dict[str, Any]

    def __post_init__(self) -> None:
        if self.synthetic is not True:
            raise ValueError(
                "Subject.synthetic must be True -- this build handles no real "
                "declaration data of any kind (docs/requirements.md Section 3, "
                "use-case-01 Section 9). Real-subject screening is out of scope "
                "by construction, not by policy."
            )


class ScopeKind(Enum):
    """How a declaration source's coverage is bounded, per category
    (use-case doc Section 6). A DS-160's employment history is a five-year
    TEMPORAL_WINDOW; its education is HIGHEST_ONLY; its org memberships are a
    TYPE_ENUMERATION. A CV is FULL_HISTORY. The reconciliation engine uses
    this to decide whether a discovered fact's absence is a gap in a document
    that asked for it, or an artifact of that document's scope."""

    TEMPORAL_WINDOW = "temporal_window"
    HIGHEST_ONLY = "highest_only"
    TYPE_ENUMERATION = "type_enumeration"
    FULL_HISTORY = "full_history"


@dataclass(frozen=True)
class DeclarationSource:
    """One document (or absent document) in the declared set, with the scope
    it actually covers. `present=False` records that a source type was
    considered and is not available for this subject -- a covered person may
    have no DS-160 at all (use-case doc Section 1.1, consequence 3)."""

    source_id: str
    kind: str  # "ds160" | "passport" | "cv" | "institutional_supplemental"
    present: bool
    scope_kind: ScopeKind
    scope_descriptor: dict[str, Any]  # e.g. {"window_years": 5, "anchor": "<submission date>"}


@dataclass(frozen=True)
class DeclaredAffiliation:
    """One institution/employer association the subject declared, tagged with
    the source it came from."""

    affiliation_id: str
    source_id: str
    institution_name: str
    country: str | None
    role: str | None
    start_date: str | None
    end_date: str | None
    activity_kind: str | None  # "employment" | "education" | "membership" | ...


@dataclass(frozen=True)
class Declaration:
    """The merged declared set for one subject: every available source, each
    carrying its own scope, plus the flattened affiliation list."""

    declaration_id: str
    subject_id: str
    synthetic: bool
    sources: tuple[DeclarationSource, ...]
    affiliations: tuple[DeclaredAffiliation, ...]

    def __post_init__(self) -> None:
        if self.synthetic is not True:
            raise ValueError(
                "Declaration.synthetic must be True -- see Subject.__post_init__."
            )


@dataclass(frozen=True)
class Case:
    """One case: one subject, one triggering event, one deadline, one file.
    `statutory_deadline` is a first-class field, captured at intake, not a
    note -- the case must reach CLOSED before that date for an HB-127 case
    (use-case doc Section 5); for a step-6 COI case it holds the annual
    disclosure cycle's due date instead, a regulatory rather than statutory
    deadline, but the same field shape.

    `declaration_id` names the exact `Declaration` this case reconciles
    against -- set once at case creation (deterministically,
    `f"{case_id}-declaration"`, never supplied by a caller) and read from
    directly by reconciliation/export, rather than derived by looking up
    "the" declaration for `subject_id` after the fact. That derived lookup
    (`case_store.load_declaration_for_subject`) is ambiguous once a subject
    can have more than one declaration over time -- exactly what an annual
    COI disclosure cycle means -- so a case must name its own.

    `coverage_basis` is `None` for a non-HB-127 case (see `CaseKind`); HB 127
    Sec. 51B.151(a) has no limb for an annual COI disclosure.
    """

    case_id: str
    subject_id: str
    declaration_id: str
    trigger: str
    access_scope: str
    coverage_basis: CoverageBasis | None
    synthetic: bool
    case_kind: CaseKind = CaseKind.HB127_RESEARCHER_SCREENING
    state: CaseState = CaseState.INTAKE
    statutory_deadline: date | None = None
    office_id: str = "default"  # single-tenant for now; a later multi-tenant filter, not a migration


@dataclass(frozen=True)
class DiscoveredAffiliation:
    """One institution/employer association found in a discovery source
    (OpenAlex publications, the GLEIF ownership chain, NSF awards). The
    measurable attributes are what Section 4 permits the system to state:
    counts, date ranges, authorship position, country -- never an
    evaluation of them.

    `country_on_adversary_list` is None until the foreign-adversary-country
    list exists (Section 12 step 4); None means "not yet checked," never
    "clear" (use-case doc Section 7)."""

    source: str  # "openalex" | "gleif_ownership" | "nsf_award"
    institution_name: str
    country: str | None
    country_on_adversary_list: bool | None
    adversary_list_version: str | None
    first_observed: str | None
    last_observed: str | None
    record_count: int
    role: str | None
    source_refs: tuple[str, ...]


@dataclass(frozen=True)
class DeclarationSearch:
    """Per-source: was this declaration source searched for the discovered
    item, what scope does it cover, and does that scope admit the item. The
    trail every Finding carries so an auditor can see which documents were
    consulted and what each one asked for (use-case doc Section 4, Section 8)."""

    source_kind: str
    present: bool
    scope_kind: ScopeKind
    scope_descriptor: dict[str, Any]
    covers_this_item: bool


@dataclass(frozen=True)
class NearestDeclared:
    """A declared affiliation that came closest to matching a discovered one
    without clearing -- retained so a genuine near-miss is visible, not
    hidden (the same discipline as author_resolve keeping tied candidates)."""

    declared_affiliation_id: str
    institution_name: str
    best_confidence: float
    match_basis: str
    cleared_name: bool
    scope_compatible: bool


class FactualBasis(Enum):
    """Why a discovered affiliation surfaced as a Finding -- a factual
    classification, never an evaluation (use-case doc Section 4)."""

    ABSENT_FROM_IN_SCOPE_SOURCE = "absent_from_in_scope_source"
    ABSENT_OUTSIDE_ALL_SOURCE_SCOPES = "absent_outside_all_source_scopes"
    PARTIAL_MATCH_BELOW_THRESHOLD = "partial_match_below_threshold"


@dataclass(frozen=True)
class Finding:
    """One discrepancy between the declared set and the discovered record --
    the Sec. 51B.153 *omission* test (failure to disclose).

    Carries NO severity, risk, priority, score, materiality, tier, weight or
    disposition field -- and neither does any type in its graph
    (DiscoveredAffiliation, DeclarationSearch, NearestDeclared). An
    evaluative claim about a person is not a thing this schema can hold. The
    human's decision lives on a separate WorksheetAction / Adjudication
    record. _OBSERVATION_GRAPH_ALLOWED_FIELDS below is checked by cli.py
    `validate`.

    A Finding no longer carries concern-list / ownership evidence: that is a
    Sec. 51B.151(b) *tie* matter, a distinct observation type (ConcernTie),
    not a non-disclosure. See docs/plans/2026-09-06-concern-ties-as-a-
    distinct-observation.md.
    """

    finding_id: str
    case_id: str
    run_id: str  # the reconciliation execution that produced it
    discovered: DiscoveredAffiliation
    declaration_search: tuple[DeclarationSearch, ...]
    factual_basis: FactualBasis
    nearest_declared: tuple[NearestDeclared, ...]


class TieKind(Enum):
    """How the subject connects to a concern-listed entity -- a factual
    descriptor of the connection, never an evaluation of it."""

    DECLARED_EMPLOYER_ULTIMATE_PARENT = "declared_employer_ultimate_parent"
    DECLARED_AFFILIATION_DIRECT = "declared_affiliation_direct"  # a declared institution is itself listed
    OWN_AFFILIATION_HISTORY = "own_affiliation_history"  # subject's own OpenAlex affiliation matches
    # CO_AUTHOR_INSTITUTION -- a co-author's institution matching a list; follow-on, not built


@dataclass(frozen=True)
class ConcernTie:
    """A tie between the subject (or something the subject declared) and a
    concern-listed entity -- the Sec. 51B.151(b) *background check* test.

    Section 4's fact/judgment boundary applies exactly as it does to Finding,
    with one statute-specific addition: the type carries NO field asserting
    that the tie "would prevent the person from being able to maintain the
    security or integrity" of the research -- Sec. 51B.151(b)'s "would
    prevent" clause is the analyst's judgment, recorded on a TieAction, never
    a thing this schema can hold. _OBSERVATION_GRAPH_ALLOWED_FIELDS is
    checked by cli.py `validate`.

    `anchor_affiliation_id` is the DECLARED affiliation the tie runs from
    (kinds 1 and 2); None for OWN_AFFILIATION_HISTORY. `related_finding_id`
    is set when the SAME discovered affiliation also produced a Finding (the
    both-at-once case) -- a join key stamped at creation, not a name match;
    always None for an ownership tie (it has no corresponding finding). The
    traversal path and its truncation status live inside the evidence
    payloads, not duplicated here.
    """

    tie_id: str
    case_id: str
    run_id: str
    tie_kind: TieKind
    anchor_affiliation_id: str | None
    related_finding_id: str | None
    concern_entity_name: str
    country: str | None
    country_on_adversary_list: bool | None  # None = not yet checked (step 4); never "clear"
    adversary_list_version: str | None
    first_observed: str | None
    last_observed: str | None
    record_count: int
    concern_list_evidence: tuple[ScreeningHit, ...]
    ownership_evidence: tuple[ForeignControlFlag, ...] = ()


class WorksheetActionKind(Enum):
    DISMISS = "dismiss"
    REQUEST_CLARIFICATION = "request_clarification"
    ESCALATE = "escalate"
    CERTIFICATION_REQUIRED = "certification_required"  # flag as needing a Sec. 51B.153 certification


@dataclass(frozen=True)
class WorksheetAction:
    """One analyst disposition of one Finding. `reason_code` is a controlled
    vocabulary (see case/vocab.py) so the office's accumulated dismissal
    bases can be aggregated -- the "how does your institution define
    substantial?" by-product (use-case doc Section 4.1). `batch_id` groups a
    bulk action taken across a class of findings in one step."""

    finding_id: str
    action: WorksheetActionKind
    reason_code: str
    reason_note: str
    actor: str
    recorded_at: str
    batch_id: str | None = None


@dataclass(frozen=True)
class TieAction:
    """One analyst disposition of one ConcernTie. Structurally the twin of
    WorksheetAction but keyed to a `tie_id`, with its own reason-code
    vocabulary (case/vocab.py:TIE_DISMISS_REASON_CODES) -- `outside_
    declaration_scope` is meaningful for a discrepancy and meaningless for a
    tie."""

    tie_id: str
    action: WorksheetActionKind
    reason_code: str
    reason_note: str
    actor: str
    recorded_at: str
    batch_id: str | None = None


@dataclass(frozen=True)
class Adjudication:
    """The analyst's assessment and recommendation for a case. Append-only:
    re-opening a closed case appends a new Adjudication (seq + 1) rather than
    editing the prior one, which stays intact and readable because it was
    correct given what was known then (use-case doc Section 5)."""

    case_id: str
    seq: int
    assessment: str
    recommendation: str
    actor: str
    recorded_at: str


@dataclass(frozen=True)
class Certification:
    """A department head's written certification under Sec. 51B.153 that a
    non-disclosure may be disregarded, and why. The statute names this
    document and requires a copy in the research security office's
    investigative file."""

    case_id: str
    finding_id: str
    substance_of_failure: str
    reasons_for_disregarding: str
    department_head: str
    recorded_at: str


# The frozen allowlist behind the fact/judgment boundary. cli.py `validate`
# asserts that every observation type (Finding and its graph, ConcernTie and
# its graph) has exactly the fields listed here -- so adding e.g. `risk_tier`
# to DiscoveredAffiliation, or `would_prevent_security` to ConcernTie, fails
# CI until someone deliberately edits this dict in the same commit and is
# forced to notice they are widening what the system is allowed to assert.
_OBSERVATION_GRAPH_ALLOWED_FIELDS: dict[str, frozenset[str]] = {
    "Finding": frozenset(
        {
            "finding_id",
            "case_id",
            "run_id",
            "discovered",
            "declaration_search",
            "factual_basis",
            "nearest_declared",
        }
    ),
    "ConcernTie": frozenset(
        {
            "tie_id",
            "case_id",
            "run_id",
            "tie_kind",
            "anchor_affiliation_id",
            "related_finding_id",
            "concern_entity_name",
            "country",
            "country_on_adversary_list",
            "adversary_list_version",
            "first_observed",
            "last_observed",
            "record_count",
            "concern_list_evidence",
            "ownership_evidence",
        }
    ),
    "DiscoveredAffiliation": frozenset(
        {
            "source",
            "institution_name",
            "country",
            "country_on_adversary_list",
            "adversary_list_version",
            "first_observed",
            "last_observed",
            "record_count",
            "role",
            "source_refs",
        }
    ),
    "DeclarationSearch": frozenset(
        {"source_kind", "present", "scope_kind", "scope_descriptor", "covers_this_item"}
    ),
    "NearestDeclared": frozenset(
        {
            "declared_affiliation_id",
            "institution_name",
            "best_confidence",
            "match_basis",
            "cleared_name",
            "scope_compatible",
        }
    ),
}

# Field-name substrings that must never appear on an observation type: an
# evaluative claim about a person. Checked alongside the allowlist so a
# rename that slips a new field past review still trips on the intent. The
# last group is Sec. 51B.151(b)'s "would prevent ... security or integrity"
# conclusion -- the analyst's, never the schema's.
_FORBIDDEN_OBSERVATION_FIELD_TOKENS: tuple[str, ...] = (
    "severity",
    "risk",
    "priority",
    "score",
    "materiality",
    "tier",
    "weight",
    "disposition",
    "rank",
    "impair",
    "prevent",
    "disqualif",
)
