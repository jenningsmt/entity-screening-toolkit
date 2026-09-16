"""S8: `ui_common.get`/`.post` build every request URL by concatenating
`cfg.api_base_url` with a caller-supplied path -- these tests prove that
concatenation can't be turned into a request to a different host, even
when the path is built from an unvalidated, free-typed value (e.g. a
worksheet page's Case ID field). The pages themselves additionally
url-quote that value before building the path (belt-and-braces against a
`?`/`#` truncating the intended path) -- that's exercised at the page-UI
test level, not here.
"""
from __future__ import annotations

import ui_common


def _cfg(**overrides) -> ui_common.SidebarConfig:
    defaults = dict(
        api_base_url="http://localhost:8000",
        actor="analyst.demo",
        actions_enabled=True,
        headers={},
        gate_enabled=False,
    )
    defaults.update(overrides)
    return ui_common.SidebarConfig(**defaults)


def _install_recording_request(monkeypatch, status_code=200):
    calls = []

    class _Resp:
        def __init__(self, url):
            self.url = url
            self.status_code = status_code

        def raise_for_status(self):
            pass

    def fake_get(url, **kwargs):
        calls.append(url)
        return _Resp(url)

    def fake_post(url, **kwargs):
        calls.append(url)
        return _Resp(url)

    monkeypatch.setattr(ui_common.requests, "get", fake_get)
    monkeypatch.setattr(ui_common.requests, "post", fake_post)
    return calls


MALICIOUS_CASE_IDS = [
    "://evil.example",
    "../../etc/passwd",
    "//evil.example",
    "demo?redact=false",
]


def test_get_never_escapes_the_configured_host(monkeypatch):
    cfg = _cfg()
    calls = _install_recording_request(monkeypatch)
    for case_id in MALICIOUS_CASE_IDS:
        ui_common.get(cfg, f"/cases/{case_id}/worksheet")
    for url in calls:
        assert url.startswith(cfg.api_base_url), url


def test_post_never_escapes_the_configured_host(monkeypatch):
    cfg = _cfg()
    calls = _install_recording_request(monkeypatch)
    for case_id in MALICIOUS_CASE_IDS:
        ui_common.post(cfg, f"/cases/{case_id}/reconcile", {})
    for url in calls:
        assert url.startswith(cfg.api_base_url), url


def test_quoted_case_id_round_trips_for_the_ordinary_case(monkeypatch):
    import urllib.parse

    cfg = _cfg()
    calls = _install_recording_request(monkeypatch)
    quoted = urllib.parse.quote("demo-coi", safe="")
    ui_common.get(cfg, f"/cases/{quoted}/worksheet")
    assert calls == [f"{cfg.api_base_url}/cases/demo-coi/worksheet"]


def test_a_quoted_malicious_case_id_cannot_reintroduce_a_query_string_or_new_host():
    import urllib.parse

    for case_id in MALICIOUS_CASE_IDS:
        quoted = urllib.parse.quote(case_id, safe="")
        assert "?" not in quoted
        assert "//" not in quoted
        assert ":" not in quoted
