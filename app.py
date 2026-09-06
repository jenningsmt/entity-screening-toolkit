"""Streamlit review UI -- the HB 127 case worksheet (Use Case 01).

A thin HTTP client of the FastAPI layer (entity_screening/api/case_routes.py).
No direct imports from the engine; everything shown here arrived over HTTP,
exactly as any other API consumer would see it.

This is the only visitor-facing view. The corpus-screening batch path
(docs/requirements.md Section 9c) stays reachable through the CLI and the
/runs/* API routes, unadvertised -- it is not a second front door here.

Run with (two terminals):
    uvicorn entity_screening.api.main:app --reload
    streamlit run app.py
"""
from __future__ import annotations

import os

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="HB 127 Researcher Screening", layout="wide")

DEMO_CASE_ID = "demo"

st.title("HB 127 Researcher Screening — case worksheet")
st.caption(
    "Portfolio project. Every row below is an **observed discrepancy**, never an "
    "evaluation: the system states facts about each item and never says whether an "
    "omission is *substantial* — that judgment is the analyst's. Demo data is "
    "**synthetic**; no real declaration data is handled (see docs/use-case-01-"
    "hb127-researcher-screening.md)."
)

with st.sidebar:
    api_base_url = st.text_input(
        "API base URL", value=os.environ.get("API_BASE_URL", "http://localhost:8000")
    ).rstrip("/")

    try:
        _gate = bool(
            requests.get(f"{api_base_url}/health", timeout=10).json().get("action_gate_enabled")
        )
    except requests.RequestException:
        _gate = False

    st.header("Case")
    case_id = st.text_input("Case ID", value=DEMO_CASE_ID)

    st.header("Analyst")
    actor = st.text_input("Your identifier (recorded on every action)", value="analyst.demo")

    st.header("Actions")
    st.caption(
        "Running reconciliation, dispositioning findings, adjudicating and "
        "certifying are gated on the public demo. Viewing the worksheet and "
        "exporting the investigative file stay open."
    )
    action_secret = st.text_input("Action secret (public demo only)", type="password", value="")
    _actions_enabled = (not _gate) or bool(action_secret)
    _headers = {"X-Monops-Action-Secret": action_secret} if action_secret else {}
    if _gate and not _actions_enabled:
        st.caption("⚠️ Enter the action secret to enable the gated actions.")


def _get(path: str, **params) -> requests.Response:
    r = requests.get(f"{api_base_url}{path}", params=params or None, timeout=60)
    r.raise_for_status()
    return r


def _post(path: str, payload: dict, timeout: int = 120) -> requests.Response:
    r = requests.post(f"{api_base_url}{path}", json=payload, timeout=timeout, headers=_headers)
    r.raise_for_status()
    return r


try:
    reason_codes = _get("/cases/reason-codes").json()
except requests.RequestException as exc:
    st.error(
        f"Can't reach the API at {api_base_url}: {exc}\n\n"
        "Start it with `uvicorn entity_screening.api.main:app --reload`."
    )
    st.stop()

DISMISS_CODES = reason_codes["dismiss"]
ESCALATION_CODES = reason_codes["escalation"]

# --- load the worksheet ---------------------------------------------------

try:
    worksheet = _get(f"/cases/{case_id}/worksheet").json()
except requests.RequestException as exc:
    st.error(f"Couldn't load case {case_id!r}: {exc}")
    st.stop()

col_a, col_b, col_c = st.columns(3)
col_a.metric("State", worksheet["state"])
col_b.metric("Coverage basis", worksheet["coverage_basis"])
col_c.metric("Statutory deadline", worksheet["statutory_deadline"] or "—")

if st.button("Re-run reconciliation", disabled=not _actions_enabled):
    with st.spinner("Reconciling declaration against public records…"):
        try:
            result = _post(f"/cases/{case_id}/reconcile", {}, timeout=600).json()
            st.success(
                f"{result['finding_count']} finding(s) across "
                f"{', '.join(result['discovery_sources'])}."
            )
            st.rerun()
        except requests.RequestException as exc:
            st.error(f"Reconciliation failed: {exc}")

st.divider()

rows = worksheet["rows"]
if not rows:
    st.info("No findings. Run reconciliation from the button above.")
    st.stop()

st.subheader(
    f"{len(rows)} discrepancy row(s) — "
    f"{worksheet['unactioned_count']} unactioned"
)
if worksheet["unactioned_count"] > 0:
    st.warning(
        "The case cannot leave the worksheet until **every** row has an analyst "
        "action (use-case-01 Section 8's closure rule)."
    )
else:
    st.success("Every row is actioned — the worksheet can close.")

# --- the worksheet table ------------------------------------------------

BASIS_LABEL = {
    "absent_from_in_scope_source": "gap in an in-scope source",
    "absent_outside_all_source_scopes": "outside every source's scope",
    "partial_match_below_threshold": "partial match to a declared item",
}

table = pd.DataFrame(
    [
        {
            "finding_id": r["finding"]["finding_id"],
            "source": r["finding"]["discovered"]["source"],
            "institution": r["finding"]["discovered"]["institution_name"],
            "country": r["finding"]["discovered"]["country"] or "—",
            "observed": " – ".join(
                x for x in (
                    r["finding"]["discovered"]["first_observed"],
                    r["finding"]["discovered"]["last_observed"],
                ) if x
            ) or "—",
            "records": r["finding"]["discovered"]["record_count"],
            "why it surfaced": BASIS_LABEL.get(
                r["finding"]["factual_basis"], r["finding"]["factual_basis"]
            ),
            "in scope of": ", ".join(
                s["source_kind"] for s in r["finding"]["declaration_search"] if s["covers_this_item"]
            ) or "(none)",
            "concern hit": ", ".join(
                h["list_name"] for h in r["finding"]["concern_list_evidence"]
            ) or "—",
            "action": (r["action"] or {}).get("action", "— unactioned —"),
            "reason": (r["action"] or {}).get("reason_code", ""),
            "by": (r["action"] or {}).get("actor", ""),
        }
        for r in rows
    ]
)
st.dataframe(table, width="stretch", hide_index=True)

# --- disposition ------------------------------------------------------

st.subheader("Disposition")
tab_single, tab_bulk = st.tabs(["One finding", "Bulk (a class at once)"])

with tab_single:
    labels = {
        f"{r['finding']['discovered']['institution_name']} "
        f"({r['finding']['discovered']['source']})": r["finding"]["finding_id"]
        for r in rows
    }
    picked = st.selectbox("Finding", list(labels), key="single_pick")
    fid = labels[picked]
    finding = next(r["finding"] for r in rows if r["finding"]["finding_id"] == fid)

    with st.expander("Evidence for this finding", expanded=True):
        st.json(finding)

    action = st.selectbox(
        "Action",
        ["dismiss", "request_clarification", "escalate", "certification_required"],
        key="single_action",
    )
    codes = DISMISS_CODES if action == "dismiss" else ESCALATION_CODES
    code = st.selectbox("Reason code", list(codes), format_func=lambda c: f"{c} — {codes[c]}", key="single_code")
    note = st.text_area("Reason note (free text — the analyst's own words)", key="single_note")
    if st.button("Record action", disabled=not _actions_enabled, key="single_btn"):
        try:
            _post(
                f"/cases/{case_id}/findings/{fid}/action",
                {"action": action, "reason_code": code, "reason_note": note, "actor": actor},
            )
            st.success("Recorded.")
            st.rerun()
        except requests.RequestException as exc:
            st.error(f"Failed: {exc}")

with tab_bulk:
    st.caption(
        "Select a class — e.g. every 'outside every source's scope' row — and "
        "disposition it with one reason. One batch, one act, one stated basis."
    )
    basis_filter = st.multiselect(
        "Rows where 'why it surfaced' is",
        sorted({r["finding"]["factual_basis"] for r in rows}),
        format_func=lambda b: BASIS_LABEL.get(b, b),
    )
    selected = [
        r["finding"]["finding_id"]
        for r in rows
        if not basis_filter or r["finding"]["factual_basis"] in basis_filter
    ]
    st.write(f"{len(selected)} row(s) selected.")
    bulk_action = st.selectbox("Action", ["dismiss", "escalate"], key="bulk_action")
    bulk_codes = DISMISS_CODES if bulk_action == "dismiss" else ESCALATION_CODES
    bulk_code = st.selectbox(
        "Reason code", list(bulk_codes), format_func=lambda c: f"{c} — {bulk_codes[c]}", key="bulk_code"
    )
    bulk_note = st.text_area("Reason note", key="bulk_note")
    if st.button("Apply to the selected class", disabled=not _actions_enabled, key="bulk_btn"):
        try:
            _post(
                f"/cases/{case_id}/worksheet/actions",
                {
                    "finding_ids": selected,
                    "action": bulk_action,
                    "reason_code": bulk_code,
                    "reason_note": bulk_note,
                    "actor": actor,
                },
            )
            st.success(f"Applied to {len(selected)} row(s).")
            st.rerun()
        except requests.RequestException as exc:
            st.error(f"Failed: {exc}")

# --- certification, adjudication, outcome, export --------------------

st.divider()
st.subheader("Adjudication and the investigative file")

with st.expander("§51B.153 department-head certification (for a disregarded non-disclosure)"):
    cert_fid = st.selectbox("Finding", list(labels), key="cert_pick")
    substance = st.text_area("Substance of the failure to disclose", key="cert_substance")
    reasons = st.text_area("Reasons for disregarding it", key="cert_reasons")
    head = st.text_input("Department head (or designee)", key="cert_head")
    if st.button("Record certification", disabled=not _actions_enabled, key="cert_btn"):
        try:
            _post(
                f"/cases/{case_id}/certifications",
                {
                    "finding_id": labels[cert_fid],
                    "substance_of_failure": substance,
                    "reasons_for_disregarding": reasons,
                    "department_head": head,
                },
            )
            st.success("Certification recorded — it will appear in the investigative file.")
        except requests.RequestException as exc:
            st.error(f"Failed: {exc}")

can_close = worksheet["can_close"]
if worksheet["state"] == "worksheet":
    if st.button("Close the worksheet → adjudication", disabled=not (_actions_enabled and can_close)):
        try:
            _post(f"/cases/{case_id}/transition", {"target_state": "adjudication"})
            st.rerun()
        except requests.RequestException as exc:
            st.error(f"Failed: {exc}")

if worksheet["state"] == "adjudication":
    assessment = st.text_area("Assessment", key="adj_assessment")
    recommendation = st.text_area("Recommendation", key="adj_recommendation")
    if st.button("Record adjudication", disabled=not _actions_enabled, key="adj_btn"):
        try:
            _post(
                f"/cases/{case_id}/adjudication",
                {"assessment": assessment, "recommendation": recommendation, "actor": actor},
            )
            st.success("Adjudication recorded.")
            st.rerun()
        except requests.RequestException as exc:
            st.error(f"Failed: {exc}")

st.markdown("**Export the investigative file** (redacted by default — classified subject fields removed):")
c1, c2 = st.columns(2)
if c1.button("Prepare JSON"):
    try:
        st.session_state["if_json"] = _get(f"/cases/{case_id}/investigative-file.json").content
    except requests.RequestException as exc:
        st.error(f"Export failed: {exc}")
if c2.button("Prepare Excel"):
    try:
        st.session_state["if_xlsx"] = _get(f"/cases/{case_id}/investigative-file.xlsx").content
    except requests.RequestException as exc:
        st.error(f"Export failed: {exc}")
if "if_json" in st.session_state:
    st.download_button("Download investigative file (JSON)", st.session_state["if_json"],
                       file_name="investigative_file.json", mime="application/json")
if "if_xlsx" in st.session_state:
    st.download_button("Download investigative file (Excel)", st.session_state["if_xlsx"],
                       file_name="investigative_file.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

st.divider()
with st.expander("This institution's accumulated dismissal bases (Section 4.1)"):
    try:
        summary = _get("/cases/dismissal-basis-summary").json()
        if summary["by_reason_code"]:
            st.dataframe(pd.DataFrame(summary["by_reason_code"]), hide_index=True)
        else:
            st.caption("No dismissals recorded yet.")
    except requests.RequestException as exc:
        st.caption(f"(unavailable: {exc})")
