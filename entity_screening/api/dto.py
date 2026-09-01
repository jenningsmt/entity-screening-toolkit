"""Pydantic request/response models for the HTTP boundary.

Deliberately named `dto.py`, not `schemas.py` — a name one letter away from
`common/schema.py` (the internal engine model, a different module in a
different package) invites exactly the kind of mix-up that's easy to make
explaining this codebase out loud. These models shape what crosses the wire
only; `common/schema.py`'s frozen dataclasses stay the internal engine model.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from entity_screening.common.manifest import RunManifest
from entity_screening.common.schema import ScoredEntity


class RunRequest(BaseModel):
    nsf_file: str | None = None
    nsf_date_start: str | None = None
    nsf_date_end: str | None = None
    opensanctions_file: str
    rubric: dict[str, float] | None = None
    threshold: float = 0.80


class RunSummary(BaseModel):
    run_id: str
    entities_count: int
    hits_count: int
    ingestion_error_count: int


class ScreeningHitOut(BaseModel):
    list_name: str
    matched_variant: str
    confidence: float
    evidence: dict[str, Any]
    status: str


class ScoredEntityOut(BaseModel):
    entity_id: str
    canonical_name: str
    status: str
    total_score: float
    factors: dict[str, float]
    screening_hits: list[ScreeningHitOut]


class DatasetSnapshotOut(BaseModel):
    source_dataset: str
    retrieved_at: str
    location: str
    record_count: int


class RunManifestOut(BaseModel):
    run_id: str
    started_at: str
    finished_at: str | None
    git_commit: str | None
    dataset_snapshots: list[DatasetSnapshotOut]
    rubric: dict[str, float]
    match_thresholds: dict[str, Any]
    ingestion_error_counts: dict[str, int]


def scored_entity_to_dto(scored: ScoredEntity) -> ScoredEntityOut:
    return ScoredEntityOut(
        entity_id=scored.entity_id,
        canonical_name=scored.canonical_name,
        status="candidate_match" if scored.screening_hits else "no_hit",
        total_score=scored.score.total,
        factors=scored.score.factors,
        screening_hits=[
            ScreeningHitOut(
                list_name=hit.list_name,
                matched_variant=hit.matched_variant,
                confidence=hit.confidence,
                evidence=hit.evidence,
                status=hit.status.value,
            )
            for hit in scored.screening_hits
        ],
    )


def run_manifest_to_dto(manifest: RunManifest) -> RunManifestOut:
    return RunManifestOut(
        run_id=manifest.run_id,
        started_at=manifest.started_at,
        finished_at=manifest.finished_at,
        git_commit=manifest.git_commit,
        dataset_snapshots=[
            DatasetSnapshotOut(
                source_dataset=s.source_dataset,
                retrieved_at=s.retrieved_at,
                location=s.location,
                record_count=s.record_count,
            )
            for s in manifest.dataset_snapshots
        ],
        rubric=manifest.rubric,
        match_thresholds=manifest.match_thresholds,
        ingestion_error_counts=manifest.ingestion_error_counts,
    )
