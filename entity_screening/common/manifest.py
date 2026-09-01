"""Run-manifest: the concrete reproducibility mechanism for this project.

Every pipeline run writes one manifest JSON recording exactly which dataset
snapshots, scoring rubric, and match thresholds were used, so any exported
row can be traced back to the inputs that produced it (docs/requirements.md
Epic G / Section 10 "Reproducibility" — mirrors the run-provenance table
pattern in the sibling project ring-density-monitor, but file-based since
this project's V1 scale doesn't need a long-lived provenance database).
"""
from __future__ import annotations

import json
import os
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_RUNS_DIR = Path("data/processed/runs")


def _git_commit() -> str | None:
    """The commit this code is running against, for the RunManifest.

    Checks GIT_COMMIT first — the API container (Dockerfile.api) bakes this
    in at build time via an ARG/ENV pair, since .dockerignore deliberately
    excludes .git from the build context (no point shipping this repo's
    whole history into a runtime image just to read one 40-character hash).
    Falls back to `git rev-parse HEAD` for native runs — the CLI, or uvicorn
    run directly on the host — where an actual .git directory is present.
    """
    env_commit = os.environ.get("GIT_COMMIT")
    if env_commit:
        return env_commit
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return None


@dataclass
class DatasetSnapshot:
    source_dataset: str
    retrieved_at: str
    location: str
    record_count: int


@dataclass
class RunManifest:
    run_id: str
    started_at: str
    finished_at: str | None = None
    git_commit: str | None = None
    dataset_snapshots: list[DatasetSnapshot] = field(default_factory=list)
    rubric: dict[str, Any] = field(default_factory=dict)
    match_thresholds: dict[str, Any] = field(default_factory=dict)
    ingestion_error_counts: dict[str, int] = field(default_factory=dict)

    @classmethod
    def start(cls) -> "RunManifest":
        return cls(
            run_id=str(uuid.uuid4()),
            started_at=datetime.now(timezone.utc).isoformat(),
            git_commit=_git_commit(),
        )

    def finish(self) -> None:
        self.finished_at = datetime.now(timezone.utc).isoformat()

    def add_dataset_snapshot(self, snapshot: DatasetSnapshot) -> None:
        self.dataset_snapshots.append(snapshot)

    def run_dir(self, base: Path | str = DEFAULT_RUNS_DIR) -> Path:
        path = Path(base) / self.run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, base: Path | str = DEFAULT_RUNS_DIR) -> Path:
        out_path = self.run_dir(base) / "manifest.json"
        out_path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
        )
        return out_path

    @classmethod
    def load(cls, path: Path | str) -> "RunManifest":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        snapshots = [DatasetSnapshot(**s) for s in data.pop("dataset_snapshots", [])]
        manifest = cls(**data)
        manifest.dataset_snapshots = snapshots
        return manifest


@dataclass
class ExportManifest:
    """Describes exactly what produced one specific exported file's score values.

    `RunManifest` records ingestion/screening provenance and the rubric active
    at run-creation time as a historical fact — it is deliberately never read
    as a live claim about what a later export's scores were computed under,
    since the API layer (Section 9a) allows re-scoring a run under a different
    rubric without re-running ingestion/screening. Every export — from the CLI
    or the API — gets its own ExportManifest, written unconditionally, so a
    downloaded file's scores are always traceable to the exact rubric that
    produced them, not just the run's original one.
    """

    export_id: str
    source_run_id: str
    exported_at: str
    rubric: dict[str, Any] = field(default_factory=dict)
    match_thresholds: dict[str, Any] = field(default_factory=dict)
    format: str = "csv"

    @classmethod
    def create(
        cls,
        source_run_id: str,
        rubric: dict[str, Any],
        match_thresholds: dict[str, Any],
        fmt: str,
    ) -> "ExportManifest":
        return cls(
            export_id=str(uuid.uuid4()),
            source_run_id=source_run_id,
            exported_at=datetime.now(timezone.utc).isoformat(),
            rubric=rubric,
            match_thresholds=match_thresholds,
            format=fmt,
        )

    def export_dir(self, base: Path | str = DEFAULT_RUNS_DIR) -> Path:
        path = Path(base) / self.source_run_id / "exports" / self.export_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, base: Path | str = DEFAULT_RUNS_DIR) -> Path:
        out_path = self.export_dir(base) / "manifest.json"
        out_path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
        )
        return out_path

    @classmethod
    def load(cls, path: Path | str) -> "ExportManifest":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**data)


@dataclass
class GleifSnapshotManifest:
    """Describes exactly which GLEIF snapshot produced a run's ownership flags.

    `gleif_lei`/`gleif_relationships` (see `ownership/ingest.py`) are a disposable
    working copy — replaced by *any* `enrich_ownership` call, for *any* run. If this
    manifest only lived next to that mutable load operation, run A's flags would
    silently lose the ability to say which GLEIF download produced them the moment
    run B's enrichment call replaces the tables — the same class of bug the
    `ExportManifest`/`git_commit` fixes addressed. So `enrich_ownership` writes a copy
    of this into the specific run's own output directory
    (`data/processed/runs/<run_id>/ownership/manifest.json`), immune to what happens
    to the shared tables afterward.

    Unlike `ExportManifest` (one immutable file per export call, since the same run
    can be exported many times under different rubrics), this is a "current state"
    record like `scored_entities` — re-running `enrich_ownership` for the same
    `run_id` overwrites it. That's a deliberate choice, not an oversight: V2 doesn't
    need per-enrichment history, just an accurate record of what's currently backing
    a run's ownership flags.
    """

    run_id: str
    loaded_at: str
    lei_record_count: int
    relationship_record_count: int
    gleif_lei_file: str
    gleif_relationships_file: str

    @classmethod
    def create(
        cls,
        run_id: str,
        lei_record_count: int,
        relationship_record_count: int,
        gleif_lei_file: Path | str,
        gleif_relationships_file: Path | str,
    ) -> "GleifSnapshotManifest":
        return cls(
            run_id=run_id,
            loaded_at=datetime.now(timezone.utc).isoformat(),
            lei_record_count=lei_record_count,
            relationship_record_count=relationship_record_count,
            gleif_lei_file=str(gleif_lei_file),
            gleif_relationships_file=str(gleif_relationships_file),
        )

    def ownership_dir(self, base: Path | str = DEFAULT_RUNS_DIR) -> Path:
        path = Path(base) / self.run_id / "ownership"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, base: Path | str = DEFAULT_RUNS_DIR) -> Path:
        out_path = self.ownership_dir(base) / "manifest.json"
        out_path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
        )
        return out_path

    @classmethod
    def load(cls, path: Path | str) -> "GleifSnapshotManifest":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**data)


@dataclass
class BibliometricSnapshotManifest:
    """Describes exactly when a run's bibliometric enrichment queried OpenAlex.

    Same durability rationale as GleifSnapshotManifest, generalized to a source with
    no file path at all: OpenAlex is a live, continuously-updated API, not a
    downloaded snapshot file, so there's nothing to name the way
    `gleif_lei_file`/`gleif_relationships_file` name a specific download. This
    manifest's job is provenance of *when* a run was enriched against that
    continuously-moving source -- the same "durable record in the run's own
    directory, immune to a later run's enrichment call" principle as GLEIF's, applied
    to a source that drifts by re-querying rather than by a new file replacing an old
    one. Re-running `enrich_bibliometric` for the same `run_id` overwrites this file --
    a "current state" record, like GleifSnapshotManifest, not a versioned history.
    """

    run_id: str
    queried_at: str
    pi_count: int
    resolved_author_count: int
    openalex_api_base_url: str

    @classmethod
    def create(
        cls,
        run_id: str,
        pi_count: int,
        resolved_author_count: int,
        openalex_api_base_url: str,
    ) -> "BibliometricSnapshotManifest":
        return cls(
            run_id=run_id,
            queried_at=datetime.now(timezone.utc).isoformat(),
            pi_count=pi_count,
            resolved_author_count=resolved_author_count,
            openalex_api_base_url=openalex_api_base_url,
        )

    def bibliometric_dir(self, base: Path | str = DEFAULT_RUNS_DIR) -> Path:
        path = Path(base) / self.run_id / "bibliometric"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, base: Path | str = DEFAULT_RUNS_DIR) -> Path:
        out_path = self.bibliometric_dir(base) / "manifest.json"
        out_path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
        )
        return out_path

    @classmethod
    def load(cls, path: Path | str) -> "BibliometricSnapshotManifest":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**data)
