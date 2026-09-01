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
