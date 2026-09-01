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
    """A resolved entity's candidate match against one entity-of-concern list."""

    entity_id: str
    list_name: str
    matched_variant: str
    matched_field: str
    confidence: float
    evidence: dict[str, Any]
    status: MatchStatus = MatchStatus.CANDIDATE_MATCH


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
    to review, never an assertion."""

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
