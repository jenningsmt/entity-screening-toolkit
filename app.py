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
    "bibliometric_hit_weight": (0.0, 150.0),
}

with st.sidebar:
    api_base_url = st.text_input(
        "API base URL", value=os.environ.get("API_BASE_URL", "http://localhost:8000")
    ).rstrip("/")

    st.header("Data sources")
    nsf_file = st.text_input("NSF awards JSON file", value="tests/fixtures/demo_nsf_awards.json")
    opensanctions_file = st.text_input(
        "OpenSanctions targets.simple.csv", value="tests/fixtures/demo_opensanctions_targets.csv"
    )
    threshold = st.slider("Screening match threshold", 0.0, 1.0, 0.80, 0.01)
    section_117_file = st.text_input(
        "Section 117 foreign funding disclosure .xlsx (optional)", value=""
    )
    run_button = st.button("Run screening", type="primary")

    st.header("Ownership analysis (optional, Epic C)")
    st.caption(
        "Leave both blank to skip — GLEIF's files aren't bundled (~525MB combined, "
        "updated daily; see docs/data_sources.md)."
    )
    gleif_lei_file = st.text_input("GLEIF Level 1 (LEI-CDF) CSV", value="")
    gleif_relationships_file = st.text_input("GLEIF Level 2 (RR-CDF) CSV", value="")
    enrich_button = st.button("Enrich with ownership data")

    st.header("Bibliometric affiliation layer (optional, Epic E)")
    st.caption(
        "Resolves this run's PIs to OpenAlex authors and checks their co-authorship/"
        "affiliation history against the same concern lists -- a live API call, no "
        "file to supply."
    )
    openalex_contact_email = st.text_input("Contact email (OpenAlex 'polite pool', optional)", value="")
    bibliometric_button = st.button("Enrich with bibliometric data")

    st.header("Topic-similarity flags (optional, advisory only)")
    st.caption(
        "Ranks PIs' real papers against DoD/CET critical-technology reference "
        "corpora -- requires bibliometric enrichment to have run first for this "
        "run. These are never scored matches: a topical-resemblance signal alone "
        "cannot establish application or risk, so results are recommendations to "
        "consult a subject-matter expert, shown separately from the scored table."
    )
    topic_similarity_button = st.button("Compute topic-similarity flags")


def _api_get(path: str, **params) -> requests.Response:
    response = requests.get(f"{api_base_url}{path}", params=params or None, timeout=30)
    response.raise_for_status()
    return response


def _api_post(path: str, payload: dict, timeout: int = 120) -> requests.Response:
    response = requests.post(f"{api_base_url}{path}", json=payload, timeout=timeout)
    response.raise_for_status()
    return response


# Bibliometric/topic-similarity enrichment can be 175-297 sequential OpenAlex
# calls for a real 53-entity run (measured directly against the real demo
# dataset -- see openalex_client.py's module docstring), any of which can add
# up to 90s of retry-backoff sleep under rate limiting. 120s (kept as the
# default above -- a reasonable guardrail for a synchronous screening run,
# which makes no live external calls at all) is nowhere near enough for this.
#
# This value is a reasoned placeholder, not a live-measured one: OpenAlex was
# rate-limited from the machine this was written on for this entire work
# session, blocking the real CLI timing pass
# docs/plans/2026-09-02-remediation-pass.md's Workstream 9 explicitly calls
# for ("time python -m entity_screening.cli run --enrich-bibliometric ...").
# Re-measure and adjust before trusting this number for anything beyond
# "better than 120s." Streamlit will also drop the websocket on a long
# synchronous POST regardless of this client-side timeout -- st.status below
# is what actually keeps the page from looking frozen either way.
ENRICHMENT_TIMEOUT_SECONDS = 600


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
    payload = {
        "nsf_file": nsf_file,
        "opensanctions_file": opensanctions_file,
        "threshold": threshold,
    }
    if section_117_file:
        payload["section_117_file"] = section_117_file
    summary = _api_post("/runs", payload).json()
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

if bibliometric_button:
    with st.status("Running bibliometric enrichment against live OpenAlex data...", expanded=True) as status:
        try:
            st.write(
                "This can take several minutes against a real dataset -- each PI's "
                "co-authorship history is walked one real paper at a time."
            )
            # Deliberately does NOT pass the sidebar's general screening threshold --
            # bibliometric cross-checking has a volume-multiplication precision risk
            # screen_entity() doesn't (every co-author's institution across every
            # paper gets checked, not one entity's own name once; a real false
            # positive at 0.80 confirmed this during V3's build, see
            # docs/data_sources.md), so it keeps its own higher default unless a
            # caller explicitly overrides it.
            payload = {"contact_email": openalex_contact_email or None}
            enrichment = _api_post(
                f"/runs/{run_id}/bibliometric", payload, timeout=ENRICHMENT_TIMEOUT_SECONDS
            ).json()
            status.update(
                label=f"Bibliometric enrichment complete: {enrichment['hits_count']} candidate hit(s) found.",
                state="complete",
            )
        except requests.RequestException as exc:
            status.update(label="Bibliometric enrichment failed.", state="error")
            st.error(
                f"Bibliometric enrichment failed: {exc}\n\n"
                "If this was a timeout, the run may still have finished on the server -- "
                "wait a moment and check the evidence trail below before retrying, since "
                "retrying a run that actually succeeded duplicates nothing (re-running is "
                "safe) but does re-do real work."
            )

if topic_similarity_button:
    with st.status("Ranking PIs' real papers against reference corpora...", expanded=True) as status:
        try:
            result = _api_post(
                f"/runs/{run_id}/topic-similarity", {}, timeout=ENRICHMENT_TIMEOUT_SECONDS
            ).json()
            st.session_state["topic_similarity_flags"] = result["flags"]
            status.update(
                label=(
                    f"Topic-similarity ranking complete: {len(result['flags'])} advisory "
                    "flag(s) -- not scored matches, see the section below."
                ),
                state="complete",
            )
        except requests.RequestException as exc:
            status.update(label="Topic-similarity ranking failed.", state="error")
            detail = exc.response.json().get("detail") if exc.response is not None else str(exc)
            st.error(f"Topic-similarity ranking failed: {detail}")

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
            "hit_kinds": ", ".join(sorted({h["producer"] for h in s["screening_hits"]})) or "—",
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
_candidate_count = sum(1 for s in scores if s["status"] == "candidate_match")
st.subheader(f"{len(df)} entities screened — {_candidate_count} candidate matches")

if _candidate_count == 0:
    # Finding 8: with the shipped demo defaults this is the common case, not
    # an error -- explain why rather than leave a visitor looking at what
    # reads as a broken demo. Real, not hand-waved: awardeeCountryCode=CN
    # against the live NSF Award Search API returns totalCount: 0 (confirmed
    # directly, 2026-09-02) -- NSF only funds US-based recipient
    # organizations, so a direct sanctions-list hit on an *awardee's own
    # name* is structurally impossible with real NSF data, not just rare in
    # this particular sample. A genuine tie to a flagged institution shows up
    # instead through the bibliometric co-authorship layer below (a legal
    # research collaboration, unlike direct funding) -- see the
    # "Enrich with bibliometric data" button in the sidebar.
    st.info(
        "**Why zero candidate matches is the expected result here, not a broken "
        "demo:** NSF only funds US-based recipient organizations, so a direct "
        "sanctions-list hit on an awardee's own name is structurally "
        "impossible with real NSF award data — confirmed directly by querying "
        "the live NSF Award Search API for any non-US awardee "
        "(`awardeeCountryCode=CN` returns `totalCount: 0`), not just absent "
        "from this particular sample. The genuine finding this dataset was "
        "built to demonstrate lives in the **bibliometric co-authorship "
        "layer** instead (a real, legal research collaboration can create a "
        "tie a direct name check never could) — see the evidence trail below "
        "after running bibliometric enrichment from the sidebar."
    )

show_hits_only = st.checkbox("Show only candidate matches", value=False)
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
        if hit["producer"] == "bibliometric":
            caveat = hit.get("evidence", {}).get("source_attribution", {}).get("caveat")
            if caveat:
                st.caption(f"⚠️ {caveat}")
        st.json(hit)
    if not hits:
        st.info("No screening hits for this entity.")

    if ownership_flags:
        st.markdown("**Foreign-control flags**")
        for flag in ownership_flags:
            st.json(flag)

st.divider()
st.subheader("Topic-similarity flags (advisory — not a scored match)")
st.caption(
    "A topical-resemblance signal alone cannot establish application or risk -- "
    "these are recommendations to consult a subject-matter expert, never blended "
    "into the scored table above or into total_score."
)
topic_flags = st.session_state.get("topic_similarity_flags", [])
if topic_flags:
    for flag in topic_flags:
        tier_label = "Primary (DoD)" if flag["corpus_tier"] == "primary" else "Secondary (CET)"
        st.markdown(
            f"**{flag['pi_name']}** — *{flag['work_title']}* — "
            f"similar to **{flag['technology_area']}** ({tier_label}, "
            f"similarity {flag['similarity_score']:.2f}, runner-up "
            f"{flag['evidence'].get('runner_up_area')} at "
            f"{flag['evidence'].get('runner_up_similarity', 0):.2f})"
        )
        st.caption(flag["recommendation"])
else:
    st.info("No topic-similarity flags yet — use the sidebar button to compute them.")

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
