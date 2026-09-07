"""Streamlit review UI -- the HB 127 case worksheet (Use Case 01).

A thin HTTP client of the FastAPI layer (entity_screening/api/case_routes.py).
No direct imports from the engine; everything shown here arrived over HTTP,
exactly as any other API consumer would see it.

This is the only visitor-facing view. The corpus-screening batch path
(docs/requirements.md Section 9c) stays reachable through the CLI and the
/runs/* API routes, unadvertised -- it is not a second front door here.

The worksheet has two sections, one per statutory test: **discrepancies**
(Sec. 51B.153, failure to disclose) and **concern ties** (Sec. 51B.151(b),
the background check). Each has its own disposition control and its own
reason vocabulary; a case cannot close while any row of either type is
unactioned.

Run with (two terminals):
    uvicorn entity_screening.api.main:app --reload
    streamlit run app.py
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="HB 127 Researcher Screening", layout="wide")

# Pinned to the top of the sidebar, above every other sidebar element, and it
# survives reruns. Resolve relative to this file, not the working directory --
# `streamlit run app.py` runs from the repo root locally, the container runs
# from /app. The asset lives under assets/ (an app-owned path COPY'd into the
# image) rather than docs/, which is a documentation folder. Absent-file guard
# so a missing asset can't take the whole page down.
#
# The asset is a PNG but NOT transparent -- verified: it is a solid, opaque
# dark-navy (~#001020) rectangle, alpha 255 everywhere except a couple of
# anti-aliased corner pixels. So the theme behaviour is unchanged in kind
# from the earlier JPEG: in dark mode the navy is close enough to Streamlit's
# dark sidebar to pass; in light mode it reads as a dark-navy block on the
# light-grey panel. `size="medium"` keeps that block from dominating. A
# genuinely transparent logo is still the real fix.
_LOGO = Path(__file__).resolve().parent / "assets" / "monops-logo.png"
if _LOGO.exists():
    st.logo(str(_LOGO), size="medium")

DEMO_CASE_ID = "demo"

st.title("HB 127 Researcher Screening — case worksheet")
st.caption(
    "Portfolio project. Every row below is an **observed fact**, never an evaluation: "
    "the system never says whether an omission is *substantial* or whether a tie "
    "*would prevent* someone maintaining research security — those judgments are the "
    "analyst's. Demo data is **synthetic**; no real declaration data is handled "
    "(see docs/use-case-01-hb127-researcher-screening.md)."
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
        "Running reconciliation, dispositioning rows, adjudicating and certifying are "
        "gated on the public demo. Viewing the worksheet and exporting the "
        "investigative file stay open."
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
TIE_DISMISS_CODES = reason_codes["tie_dismiss"]
TIE_ESCALATION_CODES = reason_codes["tie_escalation"]

# --- load the worksheet ---------------------------------------------------

try:
    worksheet = _get(f"/cases/{case_id}/worksheet").json()
except requests.RequestException as exc:
    st.error(f"Couldn't load case {case_id!r}: {exc}")
    st.stop()

rows = worksheet["rows"]
tie_rows = worksheet["tie_rows"]

col_a, col_b, col_c = st.columns(3)
col_a.metric("State", worksheet["state"])
col_b.metric("Coverage basis", worksheet["coverage_basis"])
col_c.metric("Statutory deadline", worksheet["statutory_deadline"] or "—")

if st.button("Re-run reconciliation", disabled=not _actions_enabled):
    with st.spinner("Reconciling declaration against public records…"):
        try:
            result = _post(f"/cases/{case_id}/reconcile", {}, timeout=600).json()
            st.success(
                f"{result['finding_count']} discrepancy row(s), "
                f"{result.get('tie_count', 0)} concern tie(s), across "
                f"{', '.join(result['discovery_sources'])}."
            )
            st.rerun()
        except requests.RequestException as exc:
            st.error(f"Reconciliation failed: {exc}")

if not rows and not tie_rows:
    st.info("No observations yet. Run reconciliation from the button above.")
    st.stop()

# --- combined closure indicator ---------------------------------------

unactioned_findings = sum(1 for r in rows if r["action"] is None)
unactioned_ties = sum(1 for r in tie_rows if r["action"] is None)
st.subheader(
    f"{len(rows)} discrepancy row(s) · {len(tie_rows)} concern-tie row(s) — "
    f"{worksheet['unactioned_count']} unactioned"
)
if worksheet["unactioned_count"] > 0:
    st.warning(
        f"The case cannot leave the worksheet until **every** row of both kinds has "
        f"an analyst action (use-case-01 Section 8's closure rule). "
        f"Outstanding: {unactioned_findings} discrepancy, {unactioned_ties} concern tie."
    )
else:
    st.success("Every discrepancy and every concern tie is actioned — the worksheet can close.")

BASIS_LABEL = {
    "absent_from_in_scope_source": "gap in an in-scope source",
    "absent_outside_all_source_scopes": "outside every source's scope",
    "partial_match_below_threshold": "partial match to a declared item",
}
TIE_KIND_LABEL = {
    "declared_employer_ultimate_parent": "declared employer's ultimate parent",
    "declared_affiliation_direct": "a declared institution is itself listed",
    "own_affiliation_history": "the subject's own affiliation history",
}

# map finding_id -> a short label, for cross-referencing ties
_finding_label = {
    r["finding"]["finding_id"]: r["finding"]["discovered"]["institution_name"] for r in rows
}


def _action_cells(action):
    action = action or {}
    return {
        "action": action.get("action", "— unactioned —"),
        "reason": action.get("reason_code", ""),
        "by": action.get("actor", ""),
    }


# --- Section A: discrepancies -----------------------------------------

st.divider()
st.header("Discrepancies — undisclosed items (§51B.153)")
st.caption("A discovered affiliation the declaration does not account for. The bar is a *failure to disclose*, not a risk.")

if rows:
    st.dataframe(
        pd.DataFrame(
            [
                {
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
                        s["source_kind"]
                        for s in r["finding"]["declaration_search"]
                        if s["covers_this_item"]
                    ) or "(none)",
                    **_action_cells(r["action"]),
                }
                for r in rows
            ]
        ),
        width="stretch",
        hide_index=True,
    )

    tab_one, tab_bulk = st.tabs(["One row", "Bulk (a class at once)"])
    with tab_one:
        labels = {
            f"{r['finding']['discovered']['institution_name']}": r["finding"]["finding_id"]
            for r in rows
        }
        picked = st.selectbox("Discrepancy", list(labels), key="f_pick")
        fid = labels[picked]
        with st.expander("Evidence (declaration-search trail)", expanded=False):
            st.json(next(r["finding"] for r in rows if r["finding"]["finding_id"] == fid))
        f_action = st.selectbox(
            "Action", ["dismiss", "request_clarification", "escalate", "certification_required"],
            key="f_action",
        )
        f_codes = DISMISS_CODES if f_action == "dismiss" else ESCALATION_CODES
        f_code = st.selectbox("Reason code", list(f_codes), format_func=lambda c: f"{c} — {f_codes[c]}", key="f_code")
        f_note = st.text_area("Reason note (the analyst's own words)", key="f_note")
        if st.button("Record", disabled=not _actions_enabled, key="f_btn"):
            try:
                _post(
                    f"/cases/{case_id}/findings/{fid}/action",
                    {"action": f_action, "reason_code": f_code, "reason_note": f_note, "actor": actor},
                )
                st.rerun()
            except requests.RequestException as exc:
                st.error(f"Failed: {exc}")
    with tab_bulk:
        st.caption(
            "Select a class — e.g. every 'outside every source's scope' row (the §6 "
            "mid-career trap) — and disposition it with one reason. One batch, one act."
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
        b_action = st.selectbox("Action", ["dismiss", "escalate"], key="fb_action")
        b_codes = DISMISS_CODES if b_action == "dismiss" else ESCALATION_CODES
        b_code = st.selectbox("Reason code", list(b_codes), format_func=lambda c: f"{c} — {b_codes[c]}", key="fb_code")
        b_note = st.text_area("Reason note", key="fb_note")
        if st.button("Apply to the selected class", disabled=not _actions_enabled, key="fb_btn"):
            try:
                _post(
                    f"/cases/{case_id}/worksheet/actions",
                    {"finding_ids": selected, "action": b_action, "reason_code": b_code,
                     "reason_note": b_note, "actor": actor},
                )
                st.rerun()
            except requests.RequestException as exc:
                st.error(f"Failed: {exc}")
else:
    st.info("No discrepancy rows.")

# --- Section B: concern ties ----------------------------------------

st.divider()
st.header("Concern ties — foreign-adversary background check (§51B.151(b))")
st.caption(
    "A tie between the subject (or a declared employer) and a concern-listed entity. "
    "Not a non-disclosure. Whether a tie *would prevent* someone maintaining research "
    "security is the analyst's call — the system only states the tie."
)

if tie_rows:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "how": TIE_KIND_LABEL.get(r["tie"]["tie_kind"], r["tie"]["tie_kind"]),
                    "concern entity": r["tie"]["concern_entity_name"],
                    "concern list": ", ".join(h["list_name"] for h in r["tie"]["concern_list_evidence"]),
                    "confidence": round(
                        max((h["confidence"] for h in r["tie"]["concern_list_evidence"]), default=0.0), 3
                    ),
                    "country": r["tie"]["country"] or "—",
                    "adversary-list": (
                        "not yet checked" if r["tie"]["country_on_adversary_list"] is None
                        else str(r["tie"]["country_on_adversary_list"])
                    ),
                    "also an omission": (
                        _finding_label.get(r["tie"]["related_finding_id"], "—")
                        if r["tie"]["related_finding_id"] else "—"
                    ),
                    **_action_cells(r["action"]),
                }
                for r in tie_rows
            ]
        ),
        width="stretch",
        hide_index=True,
    )

    tab_t_one, tab_t_bulk = st.tabs(["One tie", "Bulk"])
    with tab_t_one:
        t_labels = {r["tie"]["concern_entity_name"]: r["tie"]["tie_id"] for r in tie_rows}
        t_picked = st.selectbox("Concern tie", list(t_labels), key="t_pick")
        tid = t_labels[t_picked]
        _picked_tie = next(r["tie"] for r in tie_rows if r["tie"]["tie_id"] == tid)
        if _picked_tie["related_finding_id"]:
            st.info(
                f"This affiliation is **also flagged as an undisclosed discrepancy** "
                f"({_finding_label.get(_picked_tie['related_finding_id'], '?')}). "
                "Dismissing the omission does not dispose of the tie — action both."
            )
        with st.expander("Evidence (traversal path, matched entry, attribution)", expanded=False):
            st.json(_picked_tie)
        t_action = st.selectbox(
            "Action", ["dismiss", "request_clarification", "escalate", "certification_required"],
            key="t_action",
        )
        t_codes = TIE_DISMISS_CODES if t_action == "dismiss" else TIE_ESCALATION_CODES
        t_code = st.selectbox("Reason code", list(t_codes), format_func=lambda c: f"{c} — {t_codes[c]}", key="t_code")
        t_note = st.text_area("Reason note", key="t_note")
        if st.button("Record", disabled=not _actions_enabled, key="t_btn"):
            try:
                _post(
                    f"/cases/{case_id}/ties/{tid}/action",
                    {"action": t_action, "reason_code": t_code, "reason_note": t_note, "actor": actor},
                )
                st.rerun()
            except requests.RequestException as exc:
                st.error(f"Failed: {exc}")
    with tab_t_bulk:
        st.caption("Concern-tie rows are usually few; bulk is a convenience, not the norm.")
        t_selected = [r["tie"]["tie_id"] for r in tie_rows]
        tb_action = st.selectbox("Action", ["dismiss", "escalate"], key="tb_action")
        tb_codes = TIE_DISMISS_CODES if tb_action == "dismiss" else TIE_ESCALATION_CODES
        tb_code = st.selectbox("Reason code", list(tb_codes), format_func=lambda c: f"{c} — {tb_codes[c]}", key="tb_code")
        tb_note = st.text_area("Reason note", key="tb_note")
        if st.button(f"Apply to all {len(t_selected)} concern tie(s)", disabled=not _actions_enabled, key="tb_btn"):
            try:
                _post(
                    f"/cases/{case_id}/ties/actions",
                    {"tie_ids": t_selected, "action": tb_action, "reason_code": tb_code,
                     "reason_note": tb_note, "actor": actor},
                )
                st.rerun()
            except requests.RequestException as exc:
                st.error(f"Failed: {exc}")
else:
    st.success("No concern ties for this case.")

# --- certification, close, adjudication, export --------------------

st.divider()
st.header("Adjudication and the investigative file")

with st.expander("§51B.153 department-head certification (for a disregarded non-disclosure)"):
    if rows:
        cert_labels = {r["finding"]["discovered"]["institution_name"]: r["finding"]["finding_id"] for r in rows}
        cert_pick = st.selectbox("Discrepancy", list(cert_labels), key="cert_pick")
        substance = st.text_area("Substance of the failure to disclose", key="cert_substance")
        reasons = st.text_area("Reasons for disregarding it", key="cert_reasons")
        head = st.text_input("Department head (or designee)", key="cert_head")
        if st.button("Record certification", disabled=not _actions_enabled, key="cert_btn"):
            try:
                _post(
                    f"/cases/{case_id}/certifications",
                    {"finding_id": cert_labels[cert_pick], "substance_of_failure": substance,
                     "reasons_for_disregarding": reasons, "department_head": head},
                )
                st.success("Certification recorded — it will appear in the investigative file.")
            except requests.RequestException as exc:
                st.error(f"Failed: {exc}")
    else:
        st.caption("No discrepancy rows to certify.")

if worksheet["state"] == "worksheet":
    if st.button(
        "Close the worksheet → adjudication",
        disabled=not (_actions_enabled and worksheet["can_close"]),
    ):
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
        for label, key in (("Discrepancies", "discrepancy"), ("Concern ties", "concern_tie")):
            st.markdown(f"**{label}**")
            rows_ = summary[key]["by_reason_code"]
            if rows_:
                st.dataframe(pd.DataFrame(rows_), hide_index=True)
            else:
                st.caption("None recorded yet.")
    except requests.RequestException as exc:
        st.caption(f"(unavailable: {exc})")
