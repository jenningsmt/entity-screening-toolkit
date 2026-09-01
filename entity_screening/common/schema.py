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
