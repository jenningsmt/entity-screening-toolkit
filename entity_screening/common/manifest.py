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
    def start(cls, run_id: str | None = None) -> "RunManifest":
        """`run_id` is normally left to generate a fresh UUID -- every real
        caller (the API route, the CLI) wants a new, unpredictable run each
        time. The override exists for a caller that deliberately wants a
        fixed, well-known run_id, e.g. the baked-in public-demo run (see
        api/main.py:_ensure_demo_run_exists), which needs the same ID every
        time so the app can find it again after a restart."""
        return cls(
            run_id=run_id or str(uuid.uuid4()),
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
    # None means uncapped (every real work fetched). A non-None value means a
    # capped run's bibliometric coverage is partial by design (Workstream 9c)
    # -- a silently truncated works history would otherwise be a
    # reproducibility claim this run can no longer make, the same reasoning
    # ownership/graph.py:ParentChain.truncated already applies to a bounded
    # ownership walk. Defaulted so .load() still works on a manifest file
    # written before this field existed.
    max_works_per_author: int | None = None

    @classmethod
    def create(
        cls,
        run_id: str,
        pi_count: int,
        resolved_author_count: int,
        openalex_api_base_url: str,
        max_works_per_author: int | None = None,
    ) -> "BibliometricSnapshotManifest":
        return cls(
            run_id=run_id,
            queried_at=datetime.now(timezone.utc).isoformat(),
            pi_count=pi_count,
            resolved_author_count=resolved_author_count,
            openalex_api_base_url=openalex_api_base_url,
            max_works_per_author=max_works_per_author,
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


@dataclass
class ReconciliationManifest:
    """Provenance for one reconciliation run of one case (Use Case 01).

    Same "current state, run-scoped, overwritten-on-re-run" pattern as
    GleifSnapshotManifest -- re-running reconciliation for a case overwrites
    this. The immutable per-adjudication record is the exported investigative
    file, not this.

    Records `case_id` (an opaque identifier) and NOTHING that identifies the
    subject -- no name, no date of birth, no passport number. Personal data
    never reaches a manifest or a log (use-case-01 Section 9); `case_id` is
    the only join key back to the subject, which lives in the `subjects`
    table with field-level sensitivity classification.
    """

    case_id: str
    run_id: str
    reconciled_at: str
    reconciliation_threshold: float
    discovery_sources: list[str] = field(default_factory=list)
    discovered_count: int = 0
    finding_count: int = 0
    tie_count: int = 0  # Sec. 51B.151(b) concern-tie observations
    # None until the foreign-adversary-country list exists (Section 12 step 4).
    adversary_list_version: str | None = None
    git_commit: str | None = None

    @classmethod
    def create(
        cls,
        case_id: str,
        run_id: str,
        reconciliation_threshold: float,
        discovery_sources: list[str],
        discovered_count: int,
        finding_count: int,
        tie_count: int = 0,
        adversary_list_version: str | None = None,
    ) -> "ReconciliationManifest":
        return cls(
            case_id=case_id,
            run_id=run_id,
            reconciled_at=datetime.now(timezone.utc).isoformat(),
            reconciliation_threshold=reconciliation_threshold,
            discovery_sources=list(discovery_sources),
            discovered_count=discovered_count,
            finding_count=finding_count,
            tie_count=tie_count,
            adversary_list_version=adversary_list_version,
            git_commit=_git_commit(),
        )

    def case_dir(self, base: Path | str = DEFAULT_RUNS_DIR) -> Path:
        path = Path(base) / "cases" / self.case_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, base: Path | str = DEFAULT_RUNS_DIR) -> Path:
        out_path = self.case_dir(base) / "reconciliation.json"
        out_path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
        )
        return out_path

    @classmethod
    def load(cls, path: Path | str) -> "ReconciliationManifest":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**data)


@dataclass(frozen=True)
class AdversaryListManifest:
    """Describes the foreign-adversary-country list (Texas Education Code
    Sec. 51B.001(4), use-case-01 Section 12 step 4): list version, ATA-year
    derivation, gubernatorial designations, source URLs -- the shape reserved
    for this in `docs/plans/2026-09-06-use-case-01-implementation.md` Section
    4.6.

    Unlike GleifSnapshotManifest, this is not written per-run: the adversary
    list is a static, hand-curated bundled artifact (see
    `screening/adversary_list.py`'s module docstring), not a live per-run
    download, the same reason `dod_1260h.json` has no per-run manifest of its
    own either. Instead this is loaded *from* the curated JSON's own
    provenance block via `from_adversary_list`, giving the rest of the
    codebase (export, worksheet UI, docs) one typed place to read the
    derivation from.
    """

    list_version: str
    derived_at: str
    dni_ata_years: tuple[int, ...]
    dni_ata_sources: tuple[dict[str, Any], ...]
    gubernatorial_designations: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_adversary_list(cls, adversary_list: Any) -> "AdversaryListManifest":
        """`adversary_list` is a `screening.adversary_list.AdversaryCountryList`
        (not imported here -- `common/` stays a leaf package with no
        dependency on `screening/`, matching every other module in this
        file); only its `list_version`/`derived_at`/`countries` attributes
        are read, structurally."""
        dni_sources: dict[tuple[str, int], dict[str, Any]] = {}
        gubernatorial: list[dict[str, Any]] = []
        for citations in adversary_list.countries.values():
            for citation in citations:
                if citation.get("kind") == "dni_ata":
                    key = (citation.get("title", ""), citation.get("year", 0))
                    dni_sources.setdefault(
                        key,
                        {
                            "year": citation.get("year"),
                            "title": citation.get("title"),
                            "url": citation.get("url"),
                        },
                    )
                elif citation.get("kind") == "gubernatorial":
                    if citation not in gubernatorial:
                        gubernatorial.append(citation)
        years = tuple(sorted({src["year"] for src in dni_sources.values() if src["year"]}))
        sources = tuple(
            dni_sources[key] for key in sorted(dni_sources, key=lambda k: k[1])
        )
        return cls(
            list_version=adversary_list.list_version,
            derived_at=adversary_list.derived_at,
            dni_ata_years=years,
            dni_ata_sources=sources,
            gubernatorial_designations=tuple(gubernatorial),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScreeningEventManifest:
    """Provenance for one restricted-party-screening event (Use Case 02,
    step 5). Same "current state, per-event, overwritten on re-screen"
    pattern as ReconciliationManifest -- re-screening an event overwrites
    this. Records `event_id` (opaque) and nothing else identifying any
    party's real name, matching ReconciliationManifest's own case_id-only
    discipline (use-case-01 Section 9).

    No new curated-snapshot manifest is needed here the way
    AdversaryListManifest was for step 4 -- RPS reuses the existing
    OpenSanctions consolidated data unmodified (confirmed during this
    feature's planning against the real `us_trade_csl` source, see
    docs/plans/2026-09-14-restricted-party-screening.md). This manifest is
    provenance for *when* that existing data was consulted, not a new
    list's derivation.
    """

    event_id: str
    screened_at: str
    opensanctions_snapshot_date: str | None
    party_count: int = 0
    match_count: int = 0
    git_commit: str | None = None

    @classmethod
    def create(
        cls,
        event_id: str,
        opensanctions_snapshot_date: str | None,
        party_count: int,
        match_count: int,
    ) -> "ScreeningEventManifest":
        return cls(
            event_id=event_id,
            screened_at=datetime.now(timezone.utc).isoformat(),
            opensanctions_snapshot_date=opensanctions_snapshot_date,
            party_count=party_count,
            match_count=match_count,
            git_commit=_git_commit(),
        )

    def event_dir(self, base: Path | str = DEFAULT_RUNS_DIR) -> Path:
        path = Path(base) / "screening-events" / self.event_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, base: Path | str = DEFAULT_RUNS_DIR) -> Path:
        out_path = self.event_dir(base) / "manifest.json"
        out_path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
        )
        return out_path

    @classmethod
    def load(cls, path: Path | str) -> "ScreeningEventManifest":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**data)


@dataclass
class InvestigativeFileManifest:
    """One immutable record per investigative-file export (Sec. 51B.153's
    named output artifact). Same per-call immutability as ExportManifest --
    the same case, re-exported at a later adjudication seq or a different
    redaction profile, gets its own file. Records `case_id` (opaque) only,
    never the subject.
    """

    export_id: str
    case_id: str
    exported_at: str
    redaction_profile: str  # "default" (classified fields redacted) | "unredacted"
    adjudication_seq_exported: int | None
    format: str
    finding_count: int
    git_commit: str | None = None

    @classmethod
    def create(
        cls,
        case_id: str,
        redaction_profile: str,
        adjudication_seq_exported: int | None,
        fmt: str,
        finding_count: int,
    ) -> "InvestigativeFileManifest":
        return cls(
            export_id=str(uuid.uuid4()),
            case_id=case_id,
            exported_at=datetime.now(timezone.utc).isoformat(),
            redaction_profile=redaction_profile,
            adjudication_seq_exported=adjudication_seq_exported,
            format=fmt,
            finding_count=finding_count,
            git_commit=_git_commit(),
        )

    def export_dir(self, base: Path | str = DEFAULT_RUNS_DIR) -> Path:
        path = Path(base) / "cases" / self.case_id / "investigative_file" / self.export_id
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
    def load(cls, path: Path | str) -> "InvestigativeFileManifest":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**data)


@dataclass
class TopicSimilarityManifest:
    """Describes exactly which embedding model and reference-corpus files produced
    a run's topic-similarity flags (deferred VSS work).

    Same "current state," run-scoped, overwritten-on-re-run pattern as
    BibliometricSnapshotManifest. Recording the exact embedding model *and its
    pinned revision* is the same reproducibility discipline as GleifSnapshotManifest
    recording dataset versions -- an embedding model is exactly the same class of
    external dependency whose exact version needs to be part of the reproducibility
    record.
    """

    run_id: str
    computed_at: str
    embedding_model: str
    embedding_model_revision: str
    dod_corpus_file: str
    cet_corpus_file: str
    flags_count: int

    @classmethod
    def create(
        cls,
        run_id: str,
        embedding_model: str,
        embedding_model_revision: str,
        dod_corpus_file: Path | str,
        cet_corpus_file: Path | str,
        flags_count: int,
    ) -> "TopicSimilarityManifest":
        return cls(
            run_id=run_id,
            computed_at=datetime.now(timezone.utc).isoformat(),
            embedding_model=embedding_model,
            embedding_model_revision=embedding_model_revision,
            dod_corpus_file=str(dod_corpus_file),
            cet_corpus_file=str(cet_corpus_file),
            flags_count=flags_count,
        )

    def topic_similarity_dir(self, base: Path | str = DEFAULT_RUNS_DIR) -> Path:
        path = Path(base) / self.run_id / "topic_similarity"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, base: Path | str = DEFAULT_RUNS_DIR) -> Path:
        out_path = self.topic_similarity_dir(base) / "manifest.json"
        out_path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
        )
        return out_path

    @classmethod
    def load(cls, path: Path | str) -> "TopicSimilarityManifest":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**data)
