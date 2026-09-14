# Sidebar navigation: real labels, positioned as buttons under the logo

*Plan as approved via Claude Code plan mode, 2026-09-14. Historical record — read
`git log` for what actually shipped.*

---

## Context

Two related sidebar UX problems: (1) the page switcher shows "app" instead of a
descriptive name — confirmed root cause: classic `pages/` auto-discovery derives the
nav label from the filename via a regex, nothing else. (2) the native switcher always
renders as plain-text links at the very top of the sidebar, above the logo, with no
supported way to move or restyle it in classic auto-discovery mode. Both are fixed by
the same migration: `st.navigation()` + `st.Page(title=...)` + custom
`st.sidebar.button()` widgets calling `st.switch_page()`.

## Real-world verification done before designing this (not assumed from docs)

Every claim below was checked directly against the installed `streamlit==1.63.0`
package source, or empirically prototyped in a throwaway multi-page app (scratchpad,
not the repo) and run for real through `streamlit.testing.v1.AppTest` — not taken on
faith from documentation, matching this project's own established discipline.

**Confirmed from source, exactly as stated in the request:**
- `source_util.py:PAGE_FILENAME_REGEX = re.compile(r"([0-9]*)[_ -]*(.*)\.py")` and
  `page_icon_and_name()` — confirms the filename-derivation root cause precisely:
  `app.py` → label "app"; `1_Restricted_Party_Screening.py` → "Restricted Party
  Screening".
- `st.navigation(pages, *, position='sidebar'|'hidden'|'top', expanded=False)`,
  `st.Page(page, *, title=, icon=, url_path=, default=False, visibility=)`,
  `st.switch_page(page: str|Path|Page, *, query_params=None)` — signatures match
  exactly.
- `st.navigation`'s own docstring, verbatim: *"As soon as any session of your app
  executes the `st.navigation` command, your app will ignore the `pages/` directory
  (across all sessions)."* — a clean, supported migration, not a workaround.
- `st.button(..., type: 'primary'|'secondary'|'tertiary' = 'secondary', ...,
  width: Width = 'content', ...)` — `type` and `width` (this codebase already prefers
  `width="stretch"` over the deprecated `use_container_width`, per `app.py`'s own
  existing comment) both confirmed present.

**Verified empirically, beyond what was asked, because they're real correctness
risks a competent implementation has to resolve — not hand-waved:**

1. **Does `tests/test_rps_ui.py` break?** No — verified directly. `AppTest.from_file()`
   pointed straight at a page script (today's pattern, bypassing any router) continues
   to execute that script standalone and correctly, *regardless* of whether the page
   is also registered via `st.navigation()` in a sibling router file. Confirmed with a
   real prototype: the exact same page file rendered identically whether invoked
   through `AppTest.from_file(page_path)` directly or through the router +
   `switch_page`. **No change needed to `test_rps_ui.py`.** (`AppTest`'s own docstring
   does warn generally about multipage `AppTest` usage — the warning is about testing
   *page-to-page navigation itself*, which this test doesn't do; it opens one page
   directly, exactly as today.)
2. **Does `ui_common.render_sidebar_config()` need to move into the router, with `cfg`
   threaded through `st.session_state` for pages to read?** No — verified unnecessary.
   Prototyped calling sidebar content from the router (logo + nav buttons) *and* from
   the page (via `pg.run()`) in the same rerun, and inspected the actual rendered
   sidebar element order: `Logo → nav buttons (router) → Header/TextInput (page's own
   `render_sidebar_config()` call)` — Streamlit's sidebar composes strictly in call
   order regardless of which file made the call. **Each page keeps calling
   `render_sidebar_config()` itself, completely unchanged** — this gets the requested
   visual order (nav under the logo, page-specific fields below that) for free, with
   zero risk to existing widget behavior/keys and zero code churn in either page's own
   logic.
3. **Does a page's own `st.set_page_config()` call conflict with the router's?** No —
   verified empirically: router calls `st.set_page_config()` once, the routed page
   (executed via `pg.run()`) calls its own `st.set_page_config()` again with a
   different `page_title=`, no exception. **Both existing pages keep their own
   per-page `st.set_page_config()` calls, unchanged** (still useful for a per-page
   browser-tab title).
4. **Can `st.navigation()` itself live inside a `ui_common.py` helper, or must it be
   called literally inline in `app.py`?** Verified it can be encapsulated in a helper
   function — "entrypoint file" means *which script `streamlit run` was pointed at*,
   not lexical call-site. Prototyped `ui_common.render_navigation()` calling
   `st.navigation()` internally, called from `app.py`; full page-switch cycle worked
   correctly through `AppTest`.
5. **`default=True` — is it required?** Not strictly: `st.Page`'s own docstring states
   *"if no default page is passed to `st.navigation` and this is the first page, this
   page will become the default page"* — so list order alone would work. **Recommend
   setting it explicitly anyway** on the HB127 page: robust against the list ever being
   reordered later, self-documenting, and confirmed via prototype to produce the
   expected empty `url_path`.
6. **Active-page highlighting**: confirmed via prototype that `pg is candidate_page`
   (identity comparison against the `Page` object `st.navigation()` returns) correctly
   identifies the current page and drives `type="primary"` vs. `"secondary"` with no
   extra bookkeeping.

## Design

### 1. `app.py` becomes a thin router

```python
import streamlit as st
import ui_common

st.set_page_config(page_title="Monops", layout="wide")
pg = ui_common.render_navigation()
pg.run()
```

No `cd`/rename/Dockerfile/compose/README impact — `app.py` is still the file
`streamlit run` is pointed at everywhere those are configured; it just does less now.

### 2. `pages/0_HB127_Case_Worksheet.py` (new) — the HB127 worksheet, moved verbatim

Everything currently in `app.py` below the imports/router boilerplate (the case
worksheet's title, explainer, sidebar "Case" section, `_get`/`_post`, the
discrepancies/concern-ties sections, adjudication/export) moves here unchanged,
**except**: its `ui_common.render_logo()` call is removed (the router now renders the
logo exactly once, before the nav buttons — calling it again from the page would
render it twice). Its own `render_sidebar_config()` call and `st.set_page_config()`
call stay, per the verified findings above. Numbered `0_` purely for file-listing
convention — display order is fully controlled by the explicit list passed to
`st.navigation()` now, not the filename, since `st.navigation()` ignores `pages/`
auto-discovery entirely once called.

### 3. `pages/1_Restricted_Party_Screening.py` — one line removed

Same treatment: drop its own `ui_common.render_logo()` call (router's job now); every
other line is unchanged.

### 4. `ui_common.py` gains `render_navigation()`

```python
def render_navigation() -> st.Page:
    hb127 = st.Page("pages/0_HB127_Case_Worksheet.py", title="HB 127 Case Worksheet", default=True)
    rps = st.Page("pages/1_Restricted_Party_Screening.py", title="Restricted Party Screening")
    pg = st.navigation([hb127, rps], position="hidden")

    render_logo()  # now called exactly once, here
    with st.sidebar:
        if st.button(
            "HB 127 Case Worksheet", key="nav_hb127", width="stretch",
            type="primary" if pg is hb127 else "secondary",
        ):
            st.switch_page(hb127)
        if st.button(
            "Restricted Party Screening", key="nav_rps", width="stretch",
            type="primary" if pg is rps else "secondary",
        ):
            st.switch_page(rps)
    return pg
```

Plain text labels, no icons, per the request. `render_logo()` stays a separate
function (still useful factoring, now called from exactly one place instead of two).

**Bug found and fixed during implementation-time verification** (not present in the
original design above, which used `on_click=st.switch_page, args=(page,)`): invoking
`st.switch_page` from an `on_click` callback — rather than from a plain
`if st.button(...):` check in the main script body — caused the *next* rerun to fail
to re-render the router's own sidebar content (the logo and both nav buttons vanished
entirely). Reproduced empirically via `streamlit.testing.v1.AppTest` clicking through
a live page switch, and confirmed fixed by switching to the plain `if st.button(...):
st.switch_page(...)` form (Streamlit's own documented pattern for page-switch
buttons). The design and the actual `ui_common.py` implementation both use this form.

Separately, verification also surfaced that the "API base URL" sidebar field resets
to its default value on every page switch (it has no explicit `key=`, so each page
script's call to `render_sidebar_config()` is a distinct widget instance). Checked
directly against the pre-migration code (commit `c5b00be`, classic `pages/`
auto-discovery) using the same `AppTest` click-through: the reset happens there too,
identically. This is pre-existing behavior, unrelated to and unchanged by this
migration — out of scope here.

## Explicit scope boundary

- No visual/behavioral change to either page's actual content — only how the app
  boots and how the switcher looks/sits.
- No change to `Dockerfile.streamlit`, `docker-compose*.yml`, or the
  `streamlit run app.py` instructions anywhere — same entrypoint file, confirmed.
- No change to `ui_common.render_sidebar_config()`, `get()`, or `post()` — untouched.
- No change to `tests/test_rps_ui.py` — verified unnecessary, not just assumed.
- `st.navigation`'s `position="hidden"` means the *native* switcher renders nothing;
  only our own buttons appear — no dual switcher.

## Doc updates

- `docs/architecture.md`: the package/component table row describing `app.py` +
  `ui_common.py` + `pages/` updated — `app.py` is now explicitly a router, and the
  HB127 worksheet gets its own mention as `pages/0_HB127_Case_Worksheet.py`. The
  "how to run" section's commands stay identical; added a sentence noting the
  switcher is now custom-rendered via `st.navigation()`, not classic auto-discovery.
- `README.md` (~line 46, "Interactive review UI — the HB 127 case worksheet...")
  updated to mention both views are switchable from the sidebar.
- `docs/plans/README.md` — indexed this plan.

## Verification

1. `pytest -q` and `python -m entity_screening.cli validate` green, unchanged
   (301 passed; `validate` reports schema/rubric/list-registry/fixtures all sound).
2. `tests/test_rps_ui.py` passes unmodified (2/2) — the verified-unnecessary claim,
   checked for real, not just claimed.
3. Manual, via `streamlit.testing.v1.AppTest` against a live API (real `uvicorn`
   process, not a mock): confirmed both nav buttons render, the active one shows
   `type="primary"` and flips correctly on both directions of a switch (HB127 → RPS →
   HB127), the logo persists above both buttons across switches, and the main-area
   title updates per page. This is what surfaced and confirmed the `on_click` bug
   above — the first implementation attempt (using `on_click=st.switch_page,
   args=(page,)`, per the original design snippet) failed this exact check: the
   sidebar buttons and logo were both absent from a post-switch rerun. Fixed and
   re-verified with the plain `if st.button(...): st.switch_page(...)` form; the
   round-trip click-through then passed cleanly.
4. Manual, real `python -m streamlit run app.py`: server boots headless with no
   exceptions in the log and serves the app shell over HTTP 200. (Fully visual
   confirmation — button styling, exact pixel position under the logo — needs a
   real browser and wasn't performed by the agent; the `AppTest` checks in (3)
   already cover element identity, order, and type/highlighting.)

## Commit / doc sequencing

Copied this approved plan into `docs/plans/2026-09-14-sidebar-navigation.md`, indexed
it in `docs/plans/README.md`, applied the `docs/architecture.md`/`README.md`
touch-ups above. Commit message notes this is a UI-only restructure (no engine/API
changes), with the usual
`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` trailer.

## Open items for sign-off (resolved)

1. **Button labels** — used the suggested "HB 127 Case Worksheet" / "Restricted
   Party Screening" verbatim, plain text, no icons.
2. **`position="hidden"` vs. `position="top"`** — used `"hidden"` as explicitly
   asked (fully custom sidebar buttons, no native switcher at all). `"top"` remains
   a real option in this Streamlit version if a horizontal top-nav is ever wanted
   instead — not used here.
