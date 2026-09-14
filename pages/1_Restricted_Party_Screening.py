"""Streamlit review UI -- restricted-party screening (Use Case 02, step 5).

A thin HTTP client of entity_screening/api/rps_routes.py, on the same terms
as app.py's HB127 worksheet is a thin client of api/case_routes.py -- no
direct engine imports, everything shown here arrived over HTTP.

**A deliberately separate page from the HB127 case worksheet, not a section
added to app.py.** entity_screening/screening/rps_schema.py's own module
docstring states RPS is "a deliberately separate object graph" from the
HB127 case model; this file is that separation showing up in the UI too.
Reached via app.py's router (ui_common.render_navigation) -- no change to
this page's own content from that migration, beyond no longer rendering the
logo itself (the router renders it exactly once, before the nav buttons).

Run alongside app.py (same API, same two terminals):
    uvicorn entity_screening.api.main:app --reload
    streamlit run app.py     # both pages are reachable from the sidebar switcher
"""
from __future__ import annotations

import pandas as pd
import requests
import streamlit as st

import ui_common

st.set_page_config(page_title="Restricted-Party Screening", layout="wide")

cfg = ui_common.render_sidebar_config(actor_default="analyst.demo")

st.title("Restricted-party screening")

st.warning(
    "⚠ **SYNTHETIC DEMO DATA ONLY.** Every event created on this page is recorded "
    "as `synthetic=True` and cannot be otherwise — `ScreeningEvent` rejects any other "
    "value by construction (entity_screening/screening/rps_schema.py), the same "
    "guard the HB127 case worksheet's subjects and declarations already carry. "
    "This page handles no real screening data of any kind.",
    icon="⚠️",
)

with st.expander("What am I looking at?", expanded=True):
    st.markdown(
        """
**What this checks.** A name — a person or an organization — against the U.S.
government's restricted/denied/debarred-party lists (via OpenSanctions' consolidated
data, including the U.S. Trade Consolidated Screening List: BIS's Denied Persons,
Entity, and Unverified Lists; State's AECA Debarred Parties and Nonproliferation
Sanctions; and OFAC's Specially Designated Nationals List). A candidate match is
always confidence-scored and evidence-carrying, never a bare yes/no.

**What this does not check.** Whether an item or piece of technology is
export-controlled, whether a license is required, or whether the Fundamental
Research Exclusion applies — those are an export control officer's determination,
not a fact this system states. It also never checks a party's *country* against
OFAC's embargoed-country list (Cuba, Iran, North Korea, Syria, Venezuela) — country
is shown for evidence only, and is never a screening gate here.

**Three trigger events**, each with its own creation form below: a Foreign Person
hire, a visiting-scholar invitation, and a purchasing/financial transaction. A hire
or visiting-scholar event may optionally reference an existing HB127 case
(display-only — it never becomes a shared worksheet row). A purchasing event never
does; it has no case-shaped counterpart at all.

*Full specification: docs/use-case-02-restricted-party-screening.md. Implementation
plan: docs/plans/2026-09-14-restricted-party-screening.md.*
"""
    )

try:
    reason_codes = ui_common.get(cfg, "/screening-events/reason-codes").json()
except requests.RequestException as exc:
    st.error(
        f"Can't reach the API at {cfg.api_base_url}: {exc}\n\n"
        "Start it with `uvicorn entity_screening.api.main:app --reload`."
    )
    st.stop()

DISMISS_CODES = reason_codes["dismiss"]
ESCALATION_CODES = reason_codes["escalate"]

TRIGGER_LABEL = {
    "foreign_person_hire": "Foreign Person hire",
    "visiting_scholar": "Visiting scholar",
    "purchasing_financial": "Purchasing / financial",
}


def _repeatable_party_rows(state_key: str, label: str) -> list[dict]:
    """A small, session-state-backed repeatable-row widget for the Hire tab's
    optional prior-affiliations/references lists -- chosen over
    st.data_editor for a short, occasionally-empty list of simple fields,
    where a data_editor's empty-row/type-coercion edge cases buy nothing."""
    rows = st.session_state.setdefault(state_key, [])
    remove_index = None
    for i, row in enumerate(rows):
        c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
        row["name"] = c1.text_input(f"{label} name", value=row.get("name", ""), key=f"{state_key}_{i}_name")
        row["country"] = c2.text_input("Country", value=row.get("country", ""), key=f"{state_key}_{i}_country")
        row["kind"] = c3.selectbox(
            "Kind", ["organization", "person"],
            index=["organization", "person"].index(row.get("kind", "organization")),
            key=f"{state_key}_{i}_kind",
        )
        if c4.button("Remove", key=f"{state_key}_{i}_remove"):
            remove_index = i
    if remove_index is not None:
        rows.pop(remove_index)
        st.rerun()
    if st.button(f"+ Add {label.lower()}", key=f"{state_key}_add"):
        rows.append({})
        st.rerun()
    return [r for r in rows if r.get("name")]


# --- Creation: one tab per trigger, since the DTOs genuinely differ --------

st.divider()
st.header("Start a new screening event")

tab_hire, tab_visit, tab_purchase = st.tabs(
    ["Foreign Person hire", "Visiting scholar", "Purchasing / financial"]
)

with tab_hire:
    st.caption(
        "TAMU's own documented practice screens the person, their current employer, "
        "and — going back five years — prior affiliations and references, each "
        "independently (docs/plans/2026-09-14-restricted-party-screening.md)."
    )
    h_case_id = st.text_input("HB127 case ID (optional, display-only)", value="", key="h_case_id")
    c1, c2 = st.columns(2)
    h_subject_name = c1.text_input("Subject name *", key="h_subject_name")
    h_subject_country = c2.text_input("Subject country", key="h_subject_country")
    c3, c4 = st.columns(2)
    h_employer_name = c3.text_input("Current employer *", key="h_employer_name")
    h_employer_country = c4.text_input("Employer country", key="h_employer_country")

    st.markdown("**Prior affiliations** (optional)")
    h_prior = _repeatable_party_rows("h_prior_rows", "Prior affiliation")
    st.markdown("**References** (optional)")
    h_refs = _repeatable_party_rows("h_ref_rows", "Reference")

    if st.button("Create hire event", disabled=not cfg.actions_enabled, key="h_create"):
        if not h_subject_name or not h_employer_name:
            st.error("Subject name and employer name are both required.")
        else:
            try:
                resp = ui_common.post(
                    cfg,
                    "/screening-events/hire",
                    {
                        "requested_by": cfg.actor,
                        "synthetic": True,
                        "case_id": h_case_id or None,
                        "subject_name": h_subject_name,
                        "subject_country": h_subject_country or None,
                        "employer_name": h_employer_name,
                        "employer_country": h_employer_country or None,
                        "prior_affiliations": [
                            {**r, "role_in_event": "prior_affiliation"} for r in h_prior
                        ],
                        "references": [{**r, "role_in_event": "reference"} for r in h_refs],
                    },
                )
                st.session_state["open_event_id"] = resp.json()["event_id"]
                st.success(f"Created event {resp.json()['event_id']} — opened below.")
                st.rerun()
            except requests.RequestException as exc:
                st.error(f"Failed: {exc}")

with tab_visit:
    v_case_id = st.text_input("HB127 case ID (optional, display-only)", value="", key="v_case_id")
    c1, c2 = st.columns(2)
    v_visitor_name = c1.text_input("Visitor name *", key="v_visitor_name")
    v_visitor_country = c2.text_input("Visitor country", key="v_visitor_country")
    c3, c4 = st.columns(2)
    v_institution_name = c3.text_input("Institution *", key="v_institution_name")
    v_institution_country = c4.text_input("Institution country", key="v_institution_country")

    if st.button("Create visiting-scholar event", disabled=not cfg.actions_enabled, key="v_create"):
        if not v_visitor_name or not v_institution_name:
            st.error("Visitor name and institution are both required.")
        else:
            try:
                resp = ui_common.post(
                    cfg,
                    "/screening-events/visiting-scholar",
                    {
                        "requested_by": cfg.actor,
                        "synthetic": True,
                        "case_id": v_case_id or None,
                        "visitor_name": v_visitor_name,
                        "visitor_country": v_visitor_country or None,
                        "institution_name": v_institution_name,
                        "institution_country": v_institution_country or None,
                    },
                )
                st.session_state["open_event_id"] = resp.json()["event_id"]
                st.success(f"Created event {resp.json()['event_id']} — opened below.")
                st.rerun()
            except requests.RequestException as exc:
                st.error(f"Failed: {exc}")

with tab_purchase:
    st.caption(
        "A one-off transaction with a counterparty — no case-like structure, and "
        "no HB127 case ID field at all: the API never accepts one for this trigger."
    )
    c1, c2, c3 = st.columns(3)
    p_name = c1.text_input("Counterparty name *", key="p_name")
    p_country = c2.text_input("Counterparty country", key="p_country")
    p_kind = c3.selectbox("Counterparty kind", ["organization", "person"], key="p_kind")

    if st.button("Create purchasing event", disabled=not cfg.actions_enabled, key="p_create"):
        if not p_name:
            st.error("Counterparty name is required.")
        else:
            try:
                resp = ui_common.post(
                    cfg,
                    "/screening-events/purchasing",
                    {
                        "requested_by": cfg.actor,
                        "synthetic": True,
                        "counterparty_name": p_name,
                        "counterparty_country": p_country or None,
                        "counterparty_kind": p_kind,
                    },
                )
                st.session_state["open_event_id"] = resp.json()["event_id"]
                st.success(f"Created event {resp.json()['event_id']} — opened below.")
                st.rerun()
            except requests.RequestException as exc:
                st.error(f"Failed: {exc}")

# --- Browse ------------------------------------------------------------

st.divider()
st.header("Browse events")

trigger_filter = st.selectbox(
    "Trigger", ["(any)"] + list(TRIGGER_LABEL), format_func=lambda t: TRIGGER_LABEL.get(t, t),
    key="browse_trigger",
)
try:
    listing = ui_common.get(
        cfg, "/screening-events",
        **({"trigger": trigger_filter} if trigger_filter != "(any)" else {}),
    ).json()["events"]
except requests.RequestException as exc:
    st.error(f"Couldn't list events: {exc}")
    listing = []

if listing:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "event_id": e["event_id"],
                    "trigger": TRIGGER_LABEL.get(e["trigger"], e["trigger"]),
                    "case_id": e["case_id"] or "—",
                    "requested_by": e["requested_by"],
                    "requested_at": e["requested_at"],
                }
                for e in listing
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    _labels = {f"{e['event_id']} — {TRIGGER_LABEL.get(e['trigger'], e['trigger'])}": e["event_id"] for e in listing}
    _picked = st.selectbox("Open an event", ["(none)"] + list(_labels), key="browse_pick")
    if _picked != "(none)" and st.button("Open", key="browse_open"):
        st.session_state["open_event_id"] = _labels[_picked]
        st.rerun()
else:
    st.info("No events yet — create one above.")

# --- Detail: the opened event -------------------------------------------

open_event_id = st.session_state.get("open_event_id")
if open_event_id:
    st.divider()
    st.header(f"Event {open_event_id}")

    try:
        event = ui_common.get(cfg, f"/screening-events/{open_event_id}").json()
    except requests.RequestException as exc:
        st.error(f"Couldn't load event {open_event_id!r}: {exc}")
        st.stop()

    c1, c2, c3 = st.columns(3)
    c1.metric("Trigger", TRIGGER_LABEL.get(event["trigger"], event["trigger"]))
    c2.metric("Linked HB127 case", event["case_id"] or "—")
    c3.metric("Requested by", event["requested_by"])

    st.subheader("Parties")
    st.dataframe(
        pd.DataFrame(
            [
                {"name": p["name"], "kind": p["kind"], "country": p["country"] or "—", "role": p["role_in_event"]}
                for p in event["parties"]
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    _party_name = {p["party_id"]: p["name"] for p in event["parties"]}

    if st.button("Screen this event", disabled=not cfg.actions_enabled, key="screen_btn"):
        with st.spinner("Screening against restricted-party lists…"):
            try:
                # The demo/public deployment always screens against the bundled
                # demo OpenSanctions fixture -- the same file app.py's own demo
                # case uses -- rather than a free-text path field. A caller-
                # supplied path is still allowlist-checked server-side
                # (MONOPS_DATA_FILE_ALLOWLIST, entity_screening/api/deps.py), but
                # the UI shouldn't invite the attempt by offering a text box for it.
                resp = ui_common.post(
                    cfg,
                    f"/screening-events/{open_event_id}/screen",
                    {"opensanctions_file": "tests/fixtures/demo_opensanctions_targets.csv"},
                    timeout=600,
                )
                st.success(f"{resp.json()['match_count']} match(es) found.")
                st.rerun()
            except requests.RequestException as exc:
                st.error(f"Screening failed: {exc}")

    matches = event["matches"]
    st.subheader(f"Matches ({len(matches)})")
    if matches:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "party": _party_name.get(m["party_id"], m["party_id"]),
                        "matched entry": m["matched_variant"],
                        "confidence": round(m["confidence"], 3),
                        "list": m["list_name"],
                        "program id": m["evidence"].get("matched_entry_fields", {}).get("program_ids", "—"),
                        "disposition": (m["disposition"] or {}).get("action", "— unactioned —"),
                    }
                    for m in matches
                ]
            ),
            width="stretch",
            hide_index=True,
        )

        m_labels = {f"{_party_name.get(m['party_id'], m['party_id'])} — {m['matched_variant']}": m for m in matches}
        m_picked = st.selectbox("Match", list(m_labels), key="m_pick")
        m = m_labels[m_picked]

        with st.expander("Evidence (raw match)", expanded=False):
            st.json(m)

        m_action = st.selectbox("Action", ["dismiss", "escalate"], key="m_action")
        m_codes = DISMISS_CODES if m_action == "dismiss" else ESCALATION_CODES
        m_code = st.selectbox(
            "Reason code", list(m_codes), format_func=lambda c: f"{c} — {m_codes[c]}", key="m_code"
        )
        m_note = st.text_area("Reason note (the reviewer's own words)", key="m_note")
        if st.button("Record disposition", disabled=not cfg.actions_enabled, key="m_btn"):
            try:
                ui_common.post(
                    cfg,
                    f"/screening-events/{open_event_id}/matches/{m['match_id']}/disposition",
                    {"action": m_action, "reason_code": m_code, "reason_note": m_note, "actor": cfg.actor},
                )
                st.rerun()
            except requests.RequestException as exc:
                st.error(f"Failed: {exc}")
    else:
        st.info("No matches yet — screen the event above.")
