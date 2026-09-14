"""Shared Streamlit sidebar config and HTTP helpers -- imported by app.py and
every page under pages/, so a second page doesn't duplicate the API-base-URL/
actor/action-secret sidebar boilerplate app.py used to declare inline (and
risk drifting out of sync with a second copy). Lives at the repo root as a
plain sibling of app.py, not inside entity_screening/, because Streamlit's
`pages/` auto-discovery requires the entrypoint script and its pages/
directory to sit together, and this module is imported by both.

Only what's genuinely shared lives here: the logo, the API base URL, the
"Analyst" (actor) field, and the "Actions" (action-secret gate) section.
Page-specific sidebar sections (app.py's "Case" ID field, an RPS page's own
inputs) stay in their own page file.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import requests
import streamlit as st

LOGO = Path(__file__).resolve().parent / "assets" / "monops-logo.png"


def render_logo() -> None:
    """The brand mark, pinned to the very top of the sidebar -- must run
    before any other `st.sidebar` call so it lands above everything else.
    See app.py's original placement comment for the full sizing/theme
    rationale (unchanged by this refactor)."""
    if LOGO.exists():
        st.sidebar.image(str(LOGO), width="stretch")


@dataclass(frozen=True)
class SidebarConfig:
    api_base_url: str
    actor: str
    actions_enabled: bool
    headers: dict[str, str]
    gate_enabled: bool


def render_sidebar_config(actor_default: str = "analyst.demo") -> SidebarConfig:
    """Renders the API base URL field, the /health gate check, the "Analyst"
    section, and the "Actions" (action-secret) section -- identical rendering
    to app.py's original inline sidebar, minus any page-specific section."""
    with st.sidebar:
        api_base_url = st.text_input(
            "API base URL", value=os.environ.get("API_BASE_URL", "http://localhost:8000")
        ).rstrip("/")

        try:
            gate_enabled = bool(
                requests.get(f"{api_base_url}/health", timeout=10).json().get("action_gate_enabled")
            )
        except requests.RequestException:
            gate_enabled = False

        st.header("Analyst")
        actor = st.text_input("Your identifier (recorded on every action)", value=actor_default)

        st.header("Actions")
        st.caption(
            "Mutating actions are gated on the public demo. Viewing and exporting stay open."
        )
        action_secret = st.text_input("Action secret (public demo only)", type="password", value="")
        actions_enabled = (not gate_enabled) or bool(action_secret)
        headers = {"X-Monops-Action-Secret": action_secret} if action_secret else {}
        if gate_enabled and not actions_enabled:
            st.caption("⚠️ Enter the action secret to enable the gated actions.")

    return SidebarConfig(
        api_base_url=api_base_url,
        actor=actor,
        actions_enabled=actions_enabled,
        headers=headers,
        gate_enabled=gate_enabled,
    )


def get(cfg: SidebarConfig, path: str, **params) -> requests.Response:
    r = requests.get(f"{cfg.api_base_url}{path}", params=params or None, timeout=60)
    r.raise_for_status()
    return r


def post(cfg: SidebarConfig, path: str, payload: dict, timeout: int = 120) -> requests.Response:
    r = requests.post(f"{cfg.api_base_url}{path}", json=payload, timeout=timeout, headers=cfg.headers)
    r.raise_for_status()
    return r
