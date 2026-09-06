"""Shared FastAPI dependencies and path resolution.

api/case_routes.py uses these so it reuses the exact same action-secret gate
and env-var-driven paths as api/main.py without importing main.py (which
mounts case_routes' router -- a circular import). main.py keeps its own
copies of the same three-line helpers, reading the same environment
variables, so the two stay in lockstep; this module is deliberately tiny.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import Header, HTTPException

from entity_screening.common import manifest as manifest_module
from entity_screening.common import storage

_DB_PATH_ENV = "ENTITY_SCREENING_DB_PATH"
_RUNS_DIR_ENV = "ENTITY_SCREENING_RUNS_DIR"
_ACTION_SECRET_ENV = "MONOPS_ACTION_SECRET"


def db_path() -> Path:
    return Path(os.environ.get(_DB_PATH_ENV, str(storage.DEFAULT_DB_PATH)))


def runs_dir() -> Path:
    return Path(os.environ.get(_RUNS_DIR_ENV, str(manifest_module.DEFAULT_RUNS_DIR)))


def require_action_secret(x_monops_action_secret: str | None = Header(default=None)) -> None:
    """When MONOPS_ACTION_SECRET is unset, every action is unlocked -- the
    correct trust boundary for a single local user (dev, the CLI). When set,
    a request whose X-Monops-Action-Secret header is missing or wrong is
    refused with 403 before any work happens. The UI's disabled-button
    treatment is UX; this is the actual control."""
    required = os.environ.get(_ACTION_SECRET_ENV)
    if not required:
        return
    if x_monops_action_secret != required:
        raise HTTPException(
            status_code=403, detail="This action requires the correct action secret."
        )
