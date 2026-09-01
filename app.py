"""Streamlit review UI: a thin HTTP client of the FastAPI layer
(entity_screening/api/main.py) — docs/requirements.md Section 9a. No direct
imports from the entity_screening pipeline package; everything shown here
arrived over HTTP, exactly as any other API consumer would see it.

Run with (two terminals):
    uvicorn entity_screening.api.main:app --reload
    streamlit run app.py
Or via `docker compose up` (see docker-compose.yml), which points this at
the api container automatically through the API_BASE_URL env var.
"""
from __future__ import annotations

import os

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Entity & Research-Affiliation Screening Toolkit", layout="wide")

st.title("Entity & Research-Affiliation Screening Toolkit")
st.caption(
    "Portfolio project — every result below is a **scored candidate**, never a "
    "confirmed finding. See docs/requirements.md for non-goals and methodology."
)

# Wider slider ranges for weights whose sensible ceiling isn't simply
# "a few times the default" — screening_hit_confidence_multiplier and
# multiple_list_hit_bonus in particular.
RUBRIC_SLIDER_RANGES = {
    "screening_hit_weight": (0.0, 150.0),
    "screening_hit_confidence_multiplier": (0.0, 3.0),
    "multiple_list_hit_bonus": (0.0, 60.0),
    "foreign_control_weight": (0.0, 150.0),
}

with st.sidebar:
    api_base_url = st.text_input(
        "API base URL", value=os.environ.get("API_BASE_URL", "http://localhost:8000")
    ).rstrip("/")

    st.header("Data sources")
    nsf_file = st.text_input("NSF awards JSON file", value="tests/fixtures/sample_nsf_awards.json")
    opensanctions_file = st.text_input(
        "OpenSanctions targets.simple.csv", value="tests/fixtures/sample_opensanctions_targets.csv"
    )
    threshold = st.slider("Screening match threshold", 0.0, 1.0, 0.80, 0.01)
    run_button = st.button("Run screening", type="primary")

    st.header("Ownership analysis (optional, Epic C)")
    st.caption(
        "Leave both blank to skip — GLEIF's files aren't bundled (~525MB combined, "
        "updated daily; see docs/data_sources.md)."
    )
    gleif_lei_file = st.text_input("GLEIF Level 1 (LEI-CDF) CSV", value="")
    gleif_relationships_file = st.text_input("GLEIF Level 2 (RR-CDF) CSV", value="")
    enrich_button = st.button("Enrich with ownership data")


def _api_get(path: str, **params) -> requests.Response:
    response = requests.get(f"{api_base_url}{path}", params=params or None, timeout=30)
    response.raise_for_status()
    return response


def _api_post(path: str, payload: dict) -> requests.Response:
    response = requests.post(f"{api_base_url}{path}", json=payload, timeout=120)
    response.raise_for_status()
    return response


@st.cache_data(show_spinner="Fetching default rubric...")
def _default_rubric(base_url: str) -> dict:
    return requests.get(f"{base_url}/rubric/default", timeout=10).json()


try:
    default_rubric = _default_rubric(api_base_url)
except requests.RequestException as exc:
    st.error(
        f"Can't reach the API at {api_base_url}: {exc}\n\n"
        "Start it with `uvicorn entity_screening.api.main:app --reload`."
    )
    st.stop()

with st.sidebar:
    st.header("Scoring rubric")
    st.caption("Adjust weights and re-score instantly — no code changes required.")
    rubric_overrides = {}
    for field_name, default_value in default_rubric.items():
        lo, hi = RUBRIC_SLIDER_RANGES.get(field_name, (0.0, max(default_value * 3, 10.0)))
        rubric_overrides[field_name] = st.slider(
            field_name.replace("_", " "),
            min_value=lo,
            max_value=hi,
            value=float(default_value),
            step=max((hi - lo) / 50, 0.1),
        )


def _start_new_run() -> str:
    summary = _api_post(
        "/runs",
        {"nsf_file": nsf_file, "opensanctions_file": opensanctions_file, "threshold": threshold},
    ).json()
    st.session_state["run_id"] = summary["run_id"]
    return summary["run_id"]


run_id = st.session_state.get("run_id")
manifest = None
if run_id and not run_button:
    try:
        manifest = _api_get(f"/runs/{run_id}/manifest").json()
    except requests.RequestException:
        # The API may have restarted (fresh, data-wiped) since this browser
        # session last ran — a stale run_id 404s cleanly, so just start over
        # rather than surfacing that as an error the user has to act on.
        run_id = None

if run_id is None or run_button:
    try:
        run_id = _start_new_run()
        manifest = _api_get(f"/runs/{run_id}/manifest").json()
    except requests.RequestException as exc:
        st.error(f"Run failed: {exc}")
        st.stop()

with st.expander("Run provenance", expanded=False):
    st.json(manifest)

if enrich_button:
    if gleif_lei_file and gleif_relationships_file:
        try:
            enrichment = _api_post(
                f"/runs/{run_id}/ownership",
                {
                    "gleif_lei_file": gleif_lei_file,
                    "gleif_relationships_file": gleif_relationships_file,
                    "threshold": threshold,
                },
            ).json()
            st.success(
                f"Ownership analysis complete: {enrichment['flags_count']} "
                "foreign-control flag(s) found."
            )
        except requests.RequestException as exc:
            st.error(f"Ownership enrichment failed: {exc}")
    else:
        st.warning("Both GLEIF file paths are required to run ownership analysis.")

try:
    scores = _api_get(f"/runs/{run_id}/scores", **rubric_overrides).json()
except requests.RequestException as exc:
    st.error(f"Couldn't fetch scores: {exc}")
    st.stop()

df = pd.DataFrame(
    [
        {
            "canonical_name": s["canonical_name"],
            "status": s["status"],
            "total_score": round(s["total_score"], 1),
            "factors": ", ".join(f"{k}={v:.1f}" for k, v in s["factors"].items()) or "—",
            "list_hits": ", ".join(sorted({h["list_name"] for h in s["screening_hits"]})) or "—",
            "best_match_confidence": round(
                max((h["confidence"] for h in s["screening_hits"]), default=0.0), 3
            ),
            "foreign_control": (
                ", ".join(
                    sorted({f["ultimate_parent_jurisdiction"] for f in s["ownership_flags"]})
                )
                or "—"
            ),
        }
        for s in scores
    ]
).sort_values("total_score", ascending=False)

# A foreign-control flag with no screening hit is still a genuine candidate
# match (Epic C) -- status (from the API) already reflects that, so counting
# by status here rather than by screening_hits alone avoids undercounting.
st.subheader(
    f"{len(df)} entities screened — "
    f"{sum(1 for s in scores if s['status'] == 'candidate_match')} candidate matches"
)

show_hits_only = st.checkbox("Show only candidate matches", value=True)
display_df = df[df["status"] == "candidate_match"] if show_hits_only else df

st.dataframe(display_df, width="stretch", hide_index=True)

st.subheader("Evidence trail")
scores_by_name = {s["canonical_name"]: s for s in scores}
selected_name = st.selectbox(
    "Inspect an entity's evidence",
    options=display_df["canonical_name"].tolist() if not display_df.empty else [],
)
if selected_name:
    hits = scores_by_name[selected_name]["screening_hits"]
    ownership_flags = scores_by_name[selected_name]["ownership_flags"]

    for hit in hits:
        st.json(hit)
    if not hits:
        st.info("No screening hits for this entity.")

    if ownership_flags:
        st.markdown("**Foreign-control flags**")
        for flag in ownership_flags:
            st.json(flag)

st.subheader("Export")
st.caption(
    "Each export is a deliberate action, not a side effect of moving a slider — "
    "every click here writes its own manifest recording exactly which rubric "
    "produced the file, independent of the run's original one."
)
col1, col2 = st.columns(2)
if col1.button("Prepare CSV export"):
    try:
        response = _api_get(f"/runs/{run_id}/export.csv", **rubric_overrides)
        st.session_state["csv_export"] = (response.content, response.headers.get("X-Export-Id"))
    except requests.RequestException as exc:
        st.error(f"CSV export failed: {exc}")
if col2.button("Prepare Excel export"):
    try:
        response = _api_get(f"/runs/{run_id}/export.xlsx", **rubric_overrides)
        st.session_state["xlsx_export"] = (response.content, response.headers.get("X-Export-Id"))
    except requests.RequestException as exc:
        st.error(f"Excel export failed: {exc}")

if "csv_export" in st.session_state:
    content, export_id = st.session_state["csv_export"]
    st.download_button(
        f"Download CSV (export {export_id})",
        data=content,
        file_name="candidate_matches.csv",
        mime="text/csv",
    )
if "xlsx_export" in st.session_state:
    content, export_id = st.session_state["xlsx_export"]
    st.download_button(
        f"Download Excel (export {export_id})",
        data=content,
        file_name="candidate_matches.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
