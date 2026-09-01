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

from entity_screening.bibliometric.cross_check import (
    DEFAULT_CONCERN_THRESHOLD as DEFAULT_BIBLIOMETRIC_CONCERN_THRESHOLD,
)
from entity_screening.common.manifest import (
    BibliometricSnapshotManifest,
    GleifSnapshotManifest,
    RunManifest,
    TopicSimilarityManifest,
)
from entity_screening.common.schema import ScoredEntity, TopicSimilarityFlag
from entity_screening.ownership.graph import ParentChain
from entity_screening.screening.section_117 import DEFAULT_INSTITUTION_THRESHOLD


class RunRequest(BaseModel):
    nsf_file: str | None = None
    nsf_date_start: str | None = None
    nsf_date_end: str | None = None
    opensanctions_file: str
    # DoD's Section 1260H list is small and bundled with the package (see
    # entity_screening/screening/data/dod_1260h.json) — unlike the other two
    # sources, there's no live/per-run file a caller needs to supply, so
    # this is optional purely as a test/override hook, not a normal input.
    dod_1260h_file: str | None = None
    # Optional, no bundled default (like GLEIF's files) -- omit to skip the
    # Section 117 foreign-funding cross-check entirely.
    section_117_file: str | None = None
    section_117_institution_threshold: float = DEFAULT_INSTITUTION_THRESHOLD
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


class ForeignControlFlagOut(BaseModel):
    entity_lei: str
    entity_jurisdiction: str
    ultimate_parent_lei: str
    ultimate_parent_name: str
    ultimate_parent_jurisdiction: str
    relationship_path: list[str]
    match_confidence: float
    evidence: dict[str, Any]
    status: str


class ScoredEntityOut(BaseModel):
    entity_id: str
    canonical_name: str
    status: str
    total_score: float
    factors: dict[str, float]
    screening_hits: list[ScreeningHitOut]
    ownership_flags: list[ForeignControlFlagOut] = []


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


class OwnershipEnrichmentRequest(BaseModel):
    gleif_lei_file: str
    gleif_relationships_file: str
    threshold: float = 0.80
    max_depth: int = 10


class BibliometricEnrichmentRequest(BaseModel):
    contact_email: str | None = None
    threshold: float = DEFAULT_BIBLIOMETRIC_CONCERN_THRESHOLD


class TopicSimilarityEnrichmentRequest(BaseModel):
    margin: float | None = None


class TopicSimilarityManifestOut(BaseModel):
    run_id: str
    computed_at: str
    embedding_model: str
    embedding_model_revision: str
    dod_corpus_file: str
    cet_corpus_file: str
    flags_count: int


class TopicSimilarityFlagOut(BaseModel):
    pi_name: str
    openalex_work_id: str
    work_title: str
    technology_area: str
    corpus_tier: str
    similarity_score: float
    evidence: dict[str, Any]
    recommendation: str


class TopicSimilarityEnrichmentSummary(BaseModel):
    flags: list[TopicSimilarityFlagOut]
    topic_similarity_snapshot: TopicSimilarityManifestOut


class BibliometricSnapshotManifestOut(BaseModel):
    run_id: str
    queried_at: str
    pi_count: int
    resolved_author_count: int
    openalex_api_base_url: str


class BibliometricEnrichmentSummary(BaseModel):
    hits_count: int
    bibliometric_snapshot: BibliometricSnapshotManifestOut


class GleifSnapshotManifestOut(BaseModel):
    run_id: str
    loaded_at: str
    lei_record_count: int
    relationship_record_count: int
    gleif_lei_file: str
    gleif_relationships_file: str


class OwnershipEnrichmentSummary(BaseModel):
    flags_count: int
    gleif_snapshot: GleifSnapshotManifestOut


class ParentChainOut(BaseModel):
    chain: list[str]
    truncated: bool


def scored_entity_to_dto(scored: ScoredEntity) -> ScoredEntityOut:
    return ScoredEntityOut(
        entity_id=scored.entity_id,
        canonical_name=scored.canonical_name,
        # A foreign-control flag is a genuine finding even with no screening
        # hit — must not report "no_hit" for it (Epic C).
        status="candidate_match" if (scored.screening_hits or scored.ownership_flags) else "no_hit",
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
        ownership_flags=[
            ForeignControlFlagOut(
                entity_lei=flag.entity_lei,
                entity_jurisdiction=flag.entity_jurisdiction,
                ultimate_parent_lei=flag.ultimate_parent_lei,
                ultimate_parent_name=flag.ultimate_parent_name,
                ultimate_parent_jurisdiction=flag.ultimate_parent_jurisdiction,
                relationship_path=list(flag.relationship_path),
                match_confidence=flag.match_confidence,
                evidence=flag.evidence,
                status=flag.status.value,
            )
            for flag in scored.ownership_flags
        ],
    )


def gleif_snapshot_manifest_to_dto(manifest: GleifSnapshotManifest) -> GleifSnapshotManifestOut:
    return GleifSnapshotManifestOut(
        run_id=manifest.run_id,
        loaded_at=manifest.loaded_at,
        lei_record_count=manifest.lei_record_count,
        relationship_record_count=manifest.relationship_record_count,
        gleif_lei_file=manifest.gleif_lei_file,
        gleif_relationships_file=manifest.gleif_relationships_file,
    )


def bibliometric_snapshot_manifest_to_dto(
    manifest: BibliometricSnapshotManifest,
) -> BibliometricSnapshotManifestOut:
    return BibliometricSnapshotManifestOut(
        run_id=manifest.run_id,
        queried_at=manifest.queried_at,
        pi_count=manifest.pi_count,
        resolved_author_count=manifest.resolved_author_count,
        openalex_api_base_url=manifest.openalex_api_base_url,
    )


def topic_similarity_manifest_to_dto(
    manifest: TopicSimilarityManifest,
) -> TopicSimilarityManifestOut:
    return TopicSimilarityManifestOut(
        run_id=manifest.run_id,
        computed_at=manifest.computed_at,
        embedding_model=manifest.embedding_model,
        embedding_model_revision=manifest.embedding_model_revision,
        dod_corpus_file=manifest.dod_corpus_file,
        cet_corpus_file=manifest.cet_corpus_file,
        flags_count=manifest.flags_count,
    )


def topic_similarity_flag_to_dto(flag: TopicSimilarityFlag) -> TopicSimilarityFlagOut:
    return TopicSimilarityFlagOut(
        pi_name=flag.pi_name,
        openalex_work_id=flag.openalex_work_id,
        work_title=flag.work_title,
        technology_area=flag.technology_area,
        corpus_tier=flag.corpus_tier,
        similarity_score=flag.similarity_score,
        evidence=flag.evidence,
        recommendation=flag.recommendation,
    )


def parent_chain_to_dto(chain: ParentChain) -> ParentChainOut:
    return ParentChainOut(chain=list(chain.chain), truncated=chain.truncated)


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
