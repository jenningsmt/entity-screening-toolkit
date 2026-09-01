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
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_RUNS_DIR = Path("data/processed/runs")


def _git_commit() -> str | None:
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
