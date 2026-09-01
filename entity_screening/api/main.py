"""FastAPI layer over the entity_screening pipeline (docs/requirements.md
Section 9a). Streamlit (app.py) is a thin client of this API; the CLI
(cli.py) calls entity_screening/pipeline.py directly and does not depend on
this service being up.

Run with: uvicorn entity_screening.api.main:app --reload

No auth layer: this is still a local/portfolio demo (Section 9a explicitly
scopes that out). Note for whoever deploys this beyond localhost — `/runs`
and the export endpoints accept caller-supplied local file paths, the same
trust boundary the CLI already has (`--nsf-file`/`--opensanctions-file`);
that's fine for a single local user, not fine to expose on a public network
without adding path validation or auth first.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse

from entity_screening import pipeline
from entity_screening.api.dto import (
    RunManifestOut,
    RunRequest,
    RunSummary,
    ScoredEntityOut,
    run_manifest_to_dto,
    scored_entity_to_dto,
)
from entity_screening.common import storage
from entity_screening.common import manifest as manifest_module
from entity_screening.common.manifest import RunManifest
from entity_screening.scoring.rubric import STOCK_RUBRIC, rubric_from_dict, rubric_to_dict

app = FastAPI(title="Entity Screening Toolkit API")

# Resolved at call time (not bound as a function default) so tests can
# redirect these via env vars without touching the real data/processed/
# directory — see entity_screening/pipeline.py's runs_dir docstring for why
# a module-level default wouldn't be enough here.
_DB_PATH_ENV = "ENTITY_SCREENING_DB_PATH"
_RUNS_DIR_ENV = "ENTITY_SCREENING_RUNS_DIR"


def _db_path() -> Path:
    return Path(os.environ.get(_DB_PATH_ENV, str(storage.DEFAULT_DB_PATH)))


def _runs_dir() -> Path:
    return Path(os.environ.get(_RUNS_DIR_ENV, str(manifest_module.DEFAULT_RUNS_DIR)))


def _load_manifest(run_id: str) -> RunManifest:
    path = _runs_dir() / run_id / "manifest.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Unknown run_id: {run_id}")
    return RunManifest.load(path)


def rubric_overrides(
    screening_hit_weight: float | None = None,
    screening_hit_confidence_multiplier: float | None = None,
    multiple_list_hit_bonus: float | None = None,
) -> dict[str, float]:
    """Shared query-param -> rubric-override dict, used by every endpoint that
    lets a caller re-score under a modified rubric (scores/export routes)."""
    candidates = {
        "screening_hit_weight": screening_hit_weight,
        "screening_hit_confidence_multiplier": screening_hit_confidence_multiplier,
        "multiple_list_hit_bonus": multiple_list_hit_bonus,
    }
    return {k: v for k, v in candidates.items() if v is not None}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/rubric/default")
def rubric_default() -> dict:
    return rubric_to_dict(STOCK_RUBRIC)


@app.post("/runs", response_model=RunSummary)
def create_run(request: RunRequest) -> RunSummary:
    """Ingest -> resolve -> screen -> score -> persist. Synchronous (`def`,
    not `async def`, so FastAPI runs it in its threadpool rather than
    blocking the event loop) — V1 stays batch, no job queue, per Section 10's
    batch-first NFR."""
    rubric = rubric_from_dict(request.rubric or {})
    manifest, scored_entities = pipeline.run_screening(
        nsf_file=request.nsf_file,
        nsf_date_start=request.nsf_date_start,
        nsf_date_end=request.nsf_date_end,
        opensanctions_file=request.opensanctions_file,
        rubric=rubric,
        threshold=request.threshold,
        db_path=_db_path(),
        runs_dir=_runs_dir(),
    )
    return RunSummary(
        run_id=manifest.run_id,
        entities_count=len(scored_entities),
        hits_count=sum(len(s.screening_hits) for s in scored_entities),
        ingestion_error_count=manifest.ingestion_error_counts.get("total", 0),
    )


@app.get("/runs/{run_id}/manifest", response_model=RunManifestOut)
def get_run_manifest(run_id: str) -> RunManifestOut:
    return run_manifest_to_dto(_load_manifest(run_id))


@app.get("/runs/{run_id}/scores", response_model=list[ScoredEntityOut])
def get_scores(
    run_id: str, overrides: dict[str, float] = Depends(rubric_overrides)
) -> list[ScoredEntityOut]:
    """Ephemeral preview endpoint — backs the Streamlit rubric sliders. Calls
    pipeline.rescore_run(), which performs zero database writes; a slider
    drag must never grow scored_entities."""
    _load_manifest(run_id)  # 404s cleanly on an unknown run_id
    rubric = rubric_from_dict(overrides)
    scored_entities = pipeline.rescore_run(run_id, rubric, db_path=_db_path())
    return [scored_entity_to_dto(s) for s in scored_entities]


def _export(run_id: str, fmt: str, overrides: dict[str, float]) -> FileResponse:
    manifest = _load_manifest(run_id)
    rubric = rubric_from_dict(overrides)
    scored_entities = pipeline.rescore_run(run_id, rubric, db_path=_db_path())
    out_path, export_manifest = pipeline.export_scored_entities(
        scored_entities,
        source_run_id=run_id,
        rubric=rubric,
        match_thresholds=manifest.match_thresholds,
        fmt=fmt,
        runs_dir=_runs_dir(),
    )
    media_type = (
        "text/csv"
        if fmt == "csv"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return FileResponse(
        out_path,
        media_type=media_type,
        filename=out_path.name,
        headers={"X-Export-Id": export_manifest.export_id},
    )


@app.get("/runs/{run_id}/export.csv")
def export_csv_route(
    run_id: str, overrides: dict[str, float] = Depends(rubric_overrides)
) -> FileResponse:
    return _export(run_id, "csv", overrides)


@app.get("/runs/{run_id}/export.xlsx")
def export_xlsx_route(
    run_id: str, overrides: dict[str, float] = Depends(rubric_overrides)
) -> FileResponse:
    return _export(run_id, "xlsx", overrides)
