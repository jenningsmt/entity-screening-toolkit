"""Shared Streamlit sidebar config and HTTP helpers -- imported by app.py and
every page under pages/, so a second page doesn't duplicate the API-base-URL/
actor/action-secret sidebar boilerplate app.py used to declare inline (and
risk drifting out of sync with a second copy). Lives at the repo root as a
plain sibling of app.py, not inside entity_screening/, because Streamlit's
`pages/` auto-discovery requires the entrypoint script and its pages/
directory to sit together, and this module is imported by both.

Only what's genuinely shared lives here: the logo, the page switcher
(`render_navigation`), the API base URL, the "Analyst" (actor) field, and the
"Actions" (action-secret gate) section. Page-specific sidebar sections
(the HB127 page's "Case" ID field, the RPS page's own inputs) stay in their
own page file.

`render_navigation` is the one exception to "every page calls this itself":
it's called exactly once, by app.py (the router), per
docs/plans/2026-09-14-sidebar-navigation.md -- calling it a second time from
within a page would register a second, conflicting navigation and render the
logo twice. `render_sidebar_config` stays called by each page individually
(verified during that migration: Streamlit composes `st.sidebar` calls
strictly in call order regardless of which file makes them, so the router's
logo+nav rendering first and each page's own `render_sidebar_config` call
second produces the right combined order with no session_state plumbing
needed to pass config between them).
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


def render_navigation() -> st.Page:
    """Called once, by app.py, before `pg.run()`. Replaces Streamlit's
    classic `pages/` auto-discovery (which derives each nav label from its
    filename via a regex, and always renders a plain-link switcher pinned
    above everything else, with no supported way to move or restyle it) with
    `st.navigation(..., position="hidden")` plus our own styled
    `st.sidebar.button()`s -- real titles via `st.Page(title=...)`, no
    dependency on filenames, and buttons positioned directly under the logo.

    `position="hidden"` suppresses Streamlit's own switcher entirely; only
    these buttons render. `type="primary"` on whichever button matches the
    page `st.navigation()` returns gives free active-state highlighting --
    verified via `pg is candidate` identity comparison, no CSS needed.

    Calling `st.navigation()` makes Streamlit ignore the `pages/` directory's
    auto-discovery from this point on (its own docstring states this) -- the
    page files still live under `pages/`, just referenced explicitly here by
    path rather than auto-discovered by filename.

    The buttons call `st.switch_page()` from a plain `if st.button(...):`
    check, not from `on_click=`/`args=`. An `on_click` callback runs in a
    separate pass before the main script body, and invoking `st.switch_page`
    (which halts execution and requests a rerun targeted at the new page)
    from within that pass was observed, empirically, to make the *next* rerun
    fail to re-render this router's own sidebar content (logo and nav buttons
    both vanished) -- reproduced via `streamlit.testing.v1.AppTest` on a live
    click-through. The plain `if st.button(...): st.switch_page(...)` form,
    Streamlit's own documented pattern for page-switch buttons, does not have
    this problem.
    """
    hb127 = st.Page(
        "pages/0_HB127_Case_Worksheet.py", title="HB 127 Case Worksheet", default=True
    )
    rps = st.Page(
        "pages/1_Restricted_Party_Screening.py", title="Restricted Party Screening"
    )
    pg = st.navigation([hb127, rps], position="hidden")

    render_logo()
    with st.sidebar:
        if st.button(
            "HB 127 Case Worksheet",
            key="nav_hb127",
            width="stretch",
            type="primary" if pg is hb127 else "secondary",
        ):
            st.switch_page(hb127)
        if st.button(
            "Restricted Party Screening",
            key="nav_rps",
            width="stretch",
            type="primary" if pg is rps else "secondary",
        ):
            st.switch_page(rps)

    return pg


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
        env_base_url = os.environ.get("API_BASE_URL")
        if env_base_url:
            # S8: on a deployed image API_BASE_URL is set, so the field is
            # never rendered -- a visitor-editable API base URL on the
            # public site is a read-SSRF vector (it can repoint the
            # Streamlit server at an arbitrary URL: the Docker network,
            # cloud metadata endpoints, or the demo itself as a relay).
            # Local dev (env var unset) keeps the editable widget.
            api_base_url = env_base_url.rstrip("/")
        else:
            api_base_url = st.text_input(
                "API base URL", value="http://localhost:8000"
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
