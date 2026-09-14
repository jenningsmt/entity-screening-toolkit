"""Streamlit UI smoke test for the restricted-party-screening page
(pages/1_Restricted_Party_Screening.py) -- Use Case 02, step 5.

A smoke test, not new end-to-end API coverage (tests/test_rps.py already
covers the API thoroughly): confirms the page script actually executes
against a real API (via the FastAPI TestClient's own ASGI transport, no
separately-run server needed) without an uncaught exception, and that a
full create -> screen -> disposition click-path works end to end through
real Streamlit widgets.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

PAGE_PATH = str(Path(__file__).parent.parent / "pages" / "1_Restricted_Party_Screening.py")


@pytest.fixture
def api_base_url(tmp_path, monkeypatch):
    """Runs the real FastAPI app in-process via TestClient and monkeypatches
    `requests` (which ui_common.py uses, matching app.py's own existing
    HTTP-client style) to route to it -- no separately-started uvicorn
    process needed for the test suite."""
    monkeypatch.setenv("ENTITY_SCREENING_DB_PATH", str(tmp_path / "test.duckdb"))
    monkeypatch.setenv("ENTITY_SCREENING_RUNS_DIR", str(tmp_path / "runs"))

    from fastapi.testclient import TestClient

    from entity_screening.api.main import app

    client = TestClient(app, base_url="http://rps-ui-test")
    import requests

    monkeypatch.setattr(requests, "get", client.get)
    monkeypatch.setattr(requests, "post", client.post)
    return "http://rps-ui-test"


def test_page_loads_without_exception(api_base_url):
    at = AppTest.from_file(PAGE_PATH, default_timeout=60)
    at.run()
    at.sidebar.text_input[0].set_value(api_base_url).run()
    assert not at.exception
    assert len(at.tabs) == 3


def test_create_screen_and_disposition_click_path(api_base_url):
    at = AppTest.from_file(PAGE_PATH, default_timeout=60)
    at.run()
    at.sidebar.text_input[0].set_value(api_base_url).run()
    assert not at.exception

    purchasing_tab = at.tabs[2]
    # A real CSL-sourced (US-BIS-EL) entity confirmed present in the demo
    # OpenSanctions fixture itself (tests/test_rps.py's
    # test_api_visiting_scholar_event_screens_against_real_demo_data) -- the
    # page always screens against that same bundled demo file, not
    # sample_us_trade_csl.csv's own single-row extraction.
    purchasing_tab.text_input[0].set_value("Shenzhen Huada Jiutianke Technology Co., Ltd.")
    purchasing_tab.text_input[1].set_value("cn")
    purchasing_tab.button[0].click().run()
    assert not at.exception
    assert at.session_state["open_event_id"]

    screen_buttons = [b for b in at.button if b.label == "Screen this event"]
    assert screen_buttons, "detail view did not render after creating an event"
    screen_buttons[0].click().run()
    assert not at.exception

    match_selects = [sb for sb in at.selectbox if sb.label == "Match"]
    assert match_selects, "no match rendered after screening a real BIS Entity List name"

    action_select = next(sb for sb in at.selectbox if sb.label == "Action")
    action_select.set_value("escalate").run()
    code_select = next(sb for sb in at.selectbox if sb.label == "Reason code")
    code_select.set_value(list(code_select.options)[0]).run()
    note = next(ta for ta in at.text_area if "Reason note" in ta.label)
    note.set_value("End-to-end UI smoke test.")

    record_button = next(b for b in at.button if b.label == "Record disposition")
    record_button.click().run()
    assert not at.exception
