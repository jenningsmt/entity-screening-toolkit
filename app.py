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

import pandas as pd
import requests
import streamlit as st

import ui_common

st.set_page_config(page_title="HB 127 Researcher Screening", layout="wide")

# The brand mark, pinned to the very top of the sidebar: must run before any
# other `st.sidebar` call, so it lands above "API base URL" once
# ui_common.render_sidebar_config() runs below. See ui_common.render_logo's
# docstring / this project's history for the full sizing/theme rationale
# (why width="stretch" not st.logo(), why the asset is opaque, why the theme
# is pinned dark) -- unchanged by this refactor, just relocated.
ui_common.render_logo()

DEMO_CASE_ID = "demo"

# Written for a non-specialist evaluating the project, not for a research
# security practitioner. Open on arrival (expanded=True) but collapsible; it
# reappears each new session because Streamlit has no cross-session memory, and
# that is accepted rather than papered over with session_state/query-param
# machinery. The fact/judgment sentence and the synthetic-data note used to live
# in a caption under the title -- they are in here now, and the caption is gone,
# so the point is made once.
#
# Rendered BELOW the State/Coverage/Deadline metric row, not above it: the panel
# height is set by the column width, so at any short viewport an above-metrics
# panel pushed the "this runs" signal off the first screen. Below the metrics it
# is still open and unmissable, and the metric row clears the fold everywhere.
_EXPLAINER = """\
**What you're looking at**

Texas HB 127 requires public universities to screen prospective foreign
researchers before hiring, using the passport and visa application (DS-160) the
applicant submits. The statutory bar is narrow: employment is barred where the
applicant **failed to disclose** a substantial educational, employment, or
research activity — not where someone judges them risky. The disqualifying
condition is an omission. This page works that reconciliation as a case: it
compares what a researcher declared against public records — publication and
affiliation history, corporate ownership chains, government concern lists — and
surfaces every place the declaration doesn't account for what the record shows.

**What it will not do.** It never scores a person, never rules an omission
"substantial," never says a tie should prevent someone from working as a
researcher. Those are the analyst's judgments and the law's. The system puts
facts on the table with their provenance attached — and that boundary is
enforced in the data model, not just the interface: there is no field capable of
holding a risk score.

**Reading the worksheet.** Two sections, one per statutory test. *Discrepancies*
(§51B.153) are items in the record and absent from the declaration, each labeled
with why it surfaced and which source's scope window it falls in — a DS-160
covers five years of employment, so an older item is a scope gap, not a
concealment. *Concern ties* (§51B.151(b)) are links to listed entities,
including ones no name check would reach: a declared employer whose ultimate
parent sits on the DoD 1260H list. Every row needs an analyst action and a
stated reason before the case can close.

**Live versus demo.** The screening queries live sources — publication and
affiliation history comes from OpenAlex at run time. This public demo
deliberately doesn't: the case shown is built from bundled fixtures so it
renders identically for everyone and nobody's clicking fires queries on their
behalf, and the action controls are locked behind a secret. The live path is the
same code with the fixtures left out. All demo data is synthetic.

**Scope.** HB 127 researcher screening is one due-diligence workflow.
Restricted-party screening — a related but structurally different check (a
name-against-list match, not a declaration-vs-record diff) — is now its own page,
reachable from the sidebar switcher. Conflict-of-interest review is the same shape
of problem as this page and remains an intended next use case. Case intake and
queue routing would come from the office's existing workflow rather than being
rebuilt here.

*Full specification: docs/use-case-01-hb127-researcher-screening.md.*
"""

st.title("HB 127 Researcher Screening — case worksheet")
_subject_slot = st.empty()  # the subject line -- filled once the worksheet loads

cfg = ui_common.render_sidebar_config()
api_base_url = cfg.api_base_url  # kept as a module-level alias -- read in a few places below
actor = cfg.actor
_actions_enabled = cfg.actions_enabled

with st.sidebar:
    st.header("Case")
    case_id = st.text_input("Case ID", value=DEMO_CASE_ID)


def _get(path: str, **params) -> requests.Response:
    return ui_common.get(cfg, path, **params)


def _post(path: str, payload: dict, timeout: int = 120) -> requests.Response:
    return ui_common.post(cfg, path, payload, timeout=timeout)


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

# The subject line, rendered back up under the page title (via the placeholder
# reserved there). An analyst working a queue has to see whose file is open at a
# glance: display name prominent, subject_id beside it in smaller type. The
# synthetic marker rides next to the name -- a fabricated person's name shown
# plainly beside a findings panel is what use-case-01 Section 4 guards against.
_subj_name = worksheet.get("subject_display_name") or "(subject name unavailable)"
_subj_id = worksheet.get("subject_id") or "—"
_subject_md = f"### {_subj_name} &nbsp;:gray-badge[{_subj_id}]"
if worksheet.get("subject_synthetic"):
    _subject_md += " &nbsp;:red-badge[⚠ SYNTHETIC — fabricated person]"
_subject_slot.markdown(_subject_md)

col_a, col_b, col_c = st.columns(3)
col_a.metric("State", worksheet["state"])
col_b.metric("Coverage basis", worksheet["coverage_basis"])
col_c.metric("Statutory deadline", worksheet["statutory_deadline"] or "—")

with st.expander("What am I looking at?", expanded=True):
    st.markdown(_EXPLAINER)

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
