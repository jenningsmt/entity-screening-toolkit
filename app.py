"""Streamlit entrypoint -- a thin router, not a page in its own right.

Every session executes this file on every rerun (st.navigation()'s own
contract); it renders the logo and the sidebar page switcher once via
ui_common.render_navigation(), then hands off to whichever page is current
via pg.run(). The actual page content lives under pages/:
pages/0_HB127_Case_Worksheet.py (the HB 127 case worksheet, Use Case 01,
default page) and pages/1_Restricted_Party_Screening.py (Use Case 02,
step 5).

This migrated off Streamlit's classic pages/ auto-discovery (which derives
the nav label from a script's filename and always renders a plain-link
switcher pinned above everything else, with no supported way to move or
restyle it) to st.navigation()/st.Page()/st.switch_page() specifically so
the switcher could get real page titles and sit as styled buttons under the
logo -- see docs/plans/2026-09-14-sidebar-navigation.md. Calling
st.navigation() makes Streamlit ignore the pages/ directory's own
auto-discovery from this point on (confirmed in st.navigation's docstring);
the pages/ directory is still where the page files themselves live, just no
longer auto-discovered by filename.

Run with (two terminals):
    uvicorn entity_screening.api.main:app --reload
    streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

import ui_common

st.set_page_config(page_title="Monops", layout="wide")

pg = ui_common.render_navigation()
pg.run()
