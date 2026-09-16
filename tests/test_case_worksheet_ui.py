"""Streamlit UI smoke test for the HB 127 case worksheet page
(pages/0_HB127_Case_Worksheet.py) -- B2: the "Explain this match" expander
must show the demo's pre-generated explanation to an anonymous visitor
without anyone clicking "Generate explanation" (which stays gated).

Same in-process pattern as tests/test_rps_ui.py: the real FastAPI app runs
via TestClient, and `requests.get`/`.post` (which ui_common.py uses) are
monkeypatched to route to it -- no separately-started uvicorn needed.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

PAGE_PATH = str(Path(__file__).parent.parent / "pages" / "0_HB127_Case_Worksheet.py")


@pytest.fixture
def api_base_url(tmp_path, monkeypatch):
    monkeypatch.setenv("ENTITY_SCREENING_DB_PATH", str(tmp_path / "test.duckdb"))
    monkeypatch.setenv("ENTITY_SCREENING_RUNS_DIR", str(tmp_path / "runs"))

    from fastapi.testclient import TestClient

    from entity_screening.api.main import app

    client = TestClient(app, base_url="http://case-ui-test")
    import requests

    monkeypatch.setattr(requests, "get", client.get)
    monkeypatch.setattr(requests, "post", client.post)
    return "http://case-ui-test"


def test_page_loads_without_exception(api_base_url):
    at = AppTest.from_file(PAGE_PATH, default_timeout=60)
    at.run()
    at.sidebar.text_input[0].set_value(api_base_url).run()
    assert not at.exception


def test_api_base_url_widget_hidden_when_env_var_is_set(api_base_url, monkeypatch):
    """S8: on a deployed image API_BASE_URL is set, so no visitor should be
    able to repoint the app at an arbitrary URL. The widget must not render
    at all, and the page must still work using the env value directly."""
    monkeypatch.setenv("API_BASE_URL", api_base_url)
    at = AppTest.from_file(PAGE_PATH, default_timeout=60)
    at.run()
    assert not at.exception
    assert not any(ti.label == "API base URL" for ti in at.sidebar.text_input)


def test_explanation_expander_shows_the_cached_row_with_no_generate_click(api_base_url):
    at = AppTest.from_file(PAGE_PATH, default_timeout=60)
    at.run()
    at.sidebar.text_input[0].set_value(api_base_url).run()
    assert not at.exception

    finding_keys = [k for k in at.session_state.filtered_state if k.startswith("explain_finding_")]
    assert finding_keys, "no finding explanation session key was populated by the GET-first fetch"
    assert at.session_state[finding_keys[0]] is not None, (
        "expected the ungated GET to have populated a cached explanation "
        "without any button click (B2)"
    )

    tie_keys = [k for k in at.session_state.filtered_state if k.startswith("explain_tie_")]
    assert tie_keys, "no tie explanation session key was populated by the GET-first fetch"
    assert at.session_state[tie_keys[0]] is not None

    # No "Generate explanation" button should even need to exist yet -- a
    # cached row was found, so the expander renders text, not a button.
    generate_buttons = [b for b in at.button if b.label == "Generate explanation"]
    assert not generate_buttons
