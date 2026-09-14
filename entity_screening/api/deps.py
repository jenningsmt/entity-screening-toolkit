"""Shared FastAPI dependencies and path resolution.

api/case_routes.py uses these so it reuses the exact same action-secret gate
and env-var-driven paths as api/main.py without importing main.py (which
mounts case_routes' router -- a circular import). main.py keeps its own
copies of the same three-line helpers, reading the same environment
variables, so the two stay in lockstep; this module is deliberately tiny.

api/rps_routes.py uses `allowed_data_files`/`check_allowlisted` for the same
reason: `ScreenRequest.opensanctions_file` (entity_screening/screening/
rps_service.py:screen_event) accepts a caller-supplied path exactly like the
older batch `/runs` routes' `opensanctions_file`/`gleif_lei_file` params in
api/main.py, which are already gated by `MONOPS_DATA_FILE_ALLOWLIST` -- the
RPS route was built without the equivalent check (found while wiring the RPS
Streamlit page, which is the first caller that could actually reach it), so
this closes that gap using the identical env var and logic as main.py's own
`_allowed_data_files`/`_check_allowlisted`, duplicated here on purpose per
this module's own stated convention above.
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
_DATA_FILE_ALLOWLIST_ENV = "MONOPS_DATA_FILE_ALLOWLIST"


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


def allowed_data_files() -> list[Path] | None:
    """None means the env var is unset -- behavior is unchanged (arbitrary
    paths allowed), the correct trust boundary for a single local user or the
    CLI. A non-None list means every data-file path a caller supplies must
    resolve to exactly one of these. Identical logic to api/main.py's
    `_allowed_data_files`."""
    raw = os.environ.get(_DATA_FILE_ALLOWLIST_ENV)
    if not raw:
        return None
    return [Path(p).resolve() for p in raw.split(os.pathsep) if p]


def check_allowlisted(path_str: str | None, allowlist: list[Path] | None) -> None:
    """Resolves *before* comparing so a `../`-traversal attempt can't slip
    past a naive string comparison. No-ops when either side is absent: a
    caller-omitted optional path or an unset allowlist both mean nothing to
    check here. Identical logic to api/main.py's `_check_allowlisted`."""
    if path_str is None or allowlist is None:
        return
    if Path(path_str).resolve() not in allowlist:
        raise HTTPException(
            status_code=400,
            detail=f"File path not permitted on this deployment: {path_str!r}",
        )
