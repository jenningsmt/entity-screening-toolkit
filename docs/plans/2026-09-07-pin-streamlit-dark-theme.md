# Pin the Streamlit app to a dark theme

*Plan as approved via Claude Code plan mode, 2026-09-07. Historical record — read
`git log` for what actually shipped.*

---

## Context

The MONŌPS logo added in `c0b4d6d` (`assets/monops-logo.png`, rendered by `st.logo()` in
`app.py`) is an opaque dark-navy card (~#001020, cyan eye + light-grey wordmark), drawn for
a dark ground. On Streamlit's default **light** sidebar it reads as a pasted-on block; on
the **dark** sidebar (#0e1117) it is near-seamless. The logo asset is settled and is not
being revisited — cutting the mark onto true transparency is a lossy segmentation job and
would make *light* mode worse (light-grey wordmark on white ≈ invisible).

Which theme a visitor gets is currently decided by their OS/browser `prefers-color-scheme`,
so the app looks materially different from one machine to the next. Pinning the theme is
defensible on its own merits for a single-view public demo whose README carries a header
image and (later) screenshots: the app should present one way to everyone.

**Conclusion: the theme pin is the right call.** The narrow form — `base = "dark"`, no
hand-tuned palette, nothing else in the file. This fixes the logo-on-light problem, removes
the per-visitor variance, and carries no risk to the fact/judgment presentation that is the
point of the worksheet. `client.toolbarMode` is left alone (§Q4).

---

## Q1 — Mechanism: a checked-in `.streamlit/config.toml`

Create `./.streamlit/config.toml` at the repo root, committed. Of the three candidates
(checked-in `config.toml`, `STREAMLIT_THEME_*` env vars in `docker-compose.prod.yml`,
`--theme.*` CMD flags) `config.toml` is the canonical documented home: one file, at the
path every Streamlit reader looks first, applying identically to `streamlit run app.py`
locally, `scripts/compose-up.ps1`, and the deployed container. The env-var and flag options
both split the theme across two files and are invisible to anyone running the app locally;
`docker-compose.prod.yml` is also off-limits per the earlier bootstrap task.

**Container path:** `Dockerfile.streamlit` is `WORKDIR /app` + `COPY . .`, so
`./.streamlit/config.toml` → `/app/.streamlit/config.toml`, where Streamlit looks
(project-level config alongside `app.py`). The prod `command:` override keeps
`--server.baseUrlPath=monops` unchanged; `config.toml` is read regardless of launch args.

**`.gitignore` does not swallow it — verified, not assumed:** repo `.gitignore` "Env /
secrets" section is only `.env` / `*.key`; `.dockerignore` has no `.streamlit` entry;
`git check-ignore -v .streamlit/config.toml .streamlit/` → exit 1; `core.excludesfile`
unset. The common Python-template trap (ignoring `.streamlit/` because `secrets.toml` lives
there) does not apply — no such rule, no `secrets.toml`. The new file carries a comment
noting that a future `secrets.toml` must be ignored specifically, never the whole dir.

---

## Q2 — Version: read the running image, pin to exactly that

`requirements.txt` had a bare `streamlit` (unpinned). The served frontend fingerprinted the
deployed version as "1.62.x or adjacent" (byte-identical `rolldown-runtime.C0FnF6B9.js` and
many vendor chunks vs. local 1.62.0) — close but not exact, and the whole Q2/Q6 chain is
load-bearing on the exact number.

**Resolved by SSH to the Lightsail instance (Step 0 of implementation):**

```
$ docker exec <streamlit container> python -c "import streamlit; print(streamlit.__version__)"
1.63.0
```

The running image is on **streamlit 1.63.0**, not 1.62.0 — exactly the case the reviewer
flagged. `requirements.txt` is pinned to `streamlit==1.63.0` (the version already serving
the live demo, therefore known-good). Confirmed against that same running image that
`theme.base` and the full `[theme.dark]` / `[theme.sidebar]` subsection tree exist in
1.63.0, and that `client.toolbarMode` still defaults to `"auto"`.

**Tradeoff:** nothing else in `requirements.txt` is pinned, so one pinned line is
inconsistent with the file, and a full pin sweep is separate debt (noted in
`docs/how-this-was-built.md`). Done anyway because this change forces an image rebuild
(§Q6): an unpinned rebuild would resolve `streamlit` to whatever is newest on PyPI that
day, shipping a theme config validated against one version into an image running a
different, untested one — on the exact deploy where theme rendering is the point. Pinning
to the observed version makes the rebuild deterministic and keeps the frontend asset hashes
identical to what is already cached in visitors' browsers.

---

## Q3 — Palette scope: `base = "dark"` only

`[theme]` with `base = "dark"` and nothing else. Streamlit's built-in dark theme is
contrast-checked by its maintainers across every widget. A palette hand-tuned to the logo
card (~#001020, darker than Streamlit dark's #0e1117 / #262730) would put every rendered
surface at risk of a regression — the "makes the logo sit well but degrades the
fact/judgment presentation" net loss the brief warns against. The logo card against
Streamlit-dark's sidebar is already close enough; the theme does not need bending to meet
it.

**Surfaces enumerated** (to justify *not* tuning them, and as the browser-pass checklist):
both worksheet dataframes (discrepancies + concern ties — plain `pd.DataFrame`, **no
conditional colour styling**), the dismissal-basis summary dataframes, the `st.metric` row
(State / Coverage / Deadline), the two `st.json` evidence panels inside expanders, the
`st.expander` headers, `st.tabs`, every `st.success`/`st.warning`/`st.info`/`st.error`
callout (the closure indicator and the "also an omission" cross-reference ride on these),
the disabled gated buttons (`disabled=not _actions_enabled` — must stay visibly distinct),
selectboxes / multiselects / text areas / text inputs, the download buttons, and the
captions (the "observed fact, never an evaluation" caption is load-bearing text).

**No colour in the app distinguishes declared from observed values** — the tables are plain
pandas; the declared-vs-discovered distinction is carried by column semantics and text,
never cell colour. There is no custom-colour contract for a theme to break. `st.code` is
not used anywhere (`st.json` is, and it themes automatically).

---

## Q4 — Can a visitor still override it? Yes.

With the default toolbar, yes. `client.toolbarMode` defaults to `"auto"`; the theme toggle
is a *viewer* option. A visitor can open ⋮ → Settings → "Choose app theme" → Light and
override the pin. `"minimal"` is the only mode that removes the toggle, and it also removes
Print / Record-a-screencast / About.

**Decision: keep the toggle; do not touch `toolbarMode`.** The README / docs claim is
"defaults to dark," not "is dark." The determinism argument holds for the default every
visitor lands on; it is not enforcement.

`toolbarMode` is deliberately out of scope. `"auto"` already yields a viewer-only menu for
public visitors (the app is reached only through nginx at `mikejennings.dev`, and
`docker-compose.prod.yml` binds Streamlit to `127.0.0.1:8501`). The remaining case for
`"viewer"` is hypothetical. The browser pass checks what the live ⋮ menu actually offers;
if it finds Deploy / Rerun / Clear-cache exposed at `mikejennings.dev`, that is a real
finding and gets its own one-line commit — not bundled into "pin dark theme."

---

## Q5 — Blast radius outside `app.py`

- **`infra/placeholder/index.html`** — already dark (`color-scheme: dark`, `#0b1220`
  background, styled for the same logo PNG). No change; the holding page and the app now
  agree.
- **README header image** — renders on GitHub, honours the *viewer's* GitHub theme, not
  affected by this work. Out of scope (logo asset settled).
- **README screenshots** — none exist. Nothing to retake. One sentence added near the
  "Interactive review UI" section noting the app defaults to dark; a future demo
  screenshot/GIF must be captured in the pinned theme.
- **`app.py`** — the `st.logo()` block comment currently frames the light-mode "dark-navy
  block" as a live caveat; updated to say the theme is now pinned dark so the sidebar
  ground matches the card. Comment only — no logic/content change.

---

## Q6 — Deploy mechanics

**Rebuild, not just restart.** `config.toml` enters the image via `COPY . .`. On the
instance the day-2 deploy is `sudo git -C /opt/monops pull` + `sudo systemctl restart
monops`, and the unit's `ExecStart` runs `docker compose … up -d --build` — so the normal
restart *is* a rebuild. No special step.

**Asset-hash / cold-cache:** because `requirements.txt` is pinned to 1.63.0 — the version
already in the running image — the rebuilt image's `/monops/static/*` hashes match what is
being served now, so first-load caching is not disturbed. (An unpinned rebuild, or one
pinned to a guessed version, could cold-cache every visitor.)

**Confirm the `583a510` nginx work still holds — real browser, DevTools open (curl cannot
reproduce a burst):** load `https://mikejennings.dev/monops/` in a clean profile with the
Network tab open; confirm the first-paint flurry of `/monops/static/js/*.js` +
`/monops/static/media/*` all return 200/304, none 503 (i.e. `location /monops/static/` +
`limit_req … burst=100` absorb the burst); confirm `_stcore/stream` upgrades; confirm
`X-Robots-Tag: noindex, nofollow` is still on the responses. nginx config does not ship via
`git pull`, so this change cannot alter it — the check just confirms it still copes.

---

## Files changed

| File | Change |
| --- | --- |
| `.streamlit/config.toml` | New. `[theme]` with `base = "dark"` and nothing else; header comment on the pin and the `secrets.toml` caveat. No `[client]` section. |
| `requirements.txt` | `streamlit` → `streamlit==1.63.0`. |
| `app.py` | The `st.logo()` block comment only — no code change. |
| `README.md` | One sentence: the app defaults to a pinned dark theme (a visitor can still toggle it); future screenshots to be captured in it. |
| `docs/how-this-was-built.md` | Short entry — landed as a minor item *after* the substantive Phase 7 material, not as the phase's opening entry. |
| `docs/plans/2026-09-07-pin-streamlit-dark-theme.md` | This plan. |
| `docs/plans/README.md` | Index row. |

Not touched: `docker-compose.yml`, `docker-compose.prod.yml`, `Dockerfile.streamlit`,
`infra/**`, any engine/schema/test module.

---

## Verification

1. **Local, OS set to LIGHT mode**, with a counterfactual (Streamlit persists a viewer's
   theme choice client-side, so a browser previously used on this app can render dark for
   reasons unrelated to the file): config in place → dark; move `config.toml` aside +
   hard-reload → flips to light; restore + hard-reload → dark again. Run the flip in a
   fresh/incognito window so a persisted choice can't mask the light state.
2. **Clean browser profile**, OS still light: walk the demo worksheet, check every surface
   in the §Q3 list renders legibly.
3. ⋮ → Settings: "Choose app theme" present, defaults to the dark (custom) theme, switching
   to Light still works. Local-via-localhost shows developer options (expected `auto`
   behaviour); against `mikejennings.dev/monops` after deploy they must be absent for a
   plain visitor (else → separate `toolbarMode = "viewer"` commit).
4. `pytest -q` and `python -m entity_screening.cli validate` — both green (regression guard
   on the `requirements.txt` pin and the comment edit).
5. `scripts/compose-up.ps1` — containerised app also renders dark (proves the file landed
   at `/app/.streamlit/config.toml`).
6. **After deploy:** the §Q6 browser + DevTools pass — dark live, static burst absorbed
   with no 503s, websocket up, `noindex` header intact.

---

## Commit sequence

- **Step 0 (operator, no commit)** — SSH read of the running Streamlit version. Resolved:
  **1.63.0**.
- **P1** — this plan → `docs/plans/`, `docs/plans/README.md` row. Pushed before
  implementation.
- **C1** — `.streamlit/config.toml`; `requirements.txt` pinned to `1.63.0`; `app.py`
  comment; `README.md` sentence. `pytest -q` + `cli validate` green; the
  `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` trailer.
- **C2 (later, minor)** — the `docs/how-this-was-built.md` entry, landed after the Phase 7
  Use-Case-01 material rather than opening the phase with it. Its real content: the theme
  pin was the right call, but was argued properly only *after* a prior transparency claim
  (masking made ~40 corner pixels transparent and shipped an opaque card) was caught by
  the other session measuring the asset's alpha channel — a clean instance of the
  two-session factual-check split.
- Deploy is a separate operator step, bundled with the pending remediation-pass / HB 127 /
  ConcernTie deploy backlog (instance HEAD is `c24238d`, three commits behind master).

---

## Out of scope

- The logo asset itself (settled).
- Any hand-tuned theme palette, fonts, radii, chart colours.
- Any `client.toolbarMode` change (see §Q4).
- A full `requirements.txt` pin sweep (separate debt).
- `docker-compose*.yml`, `Dockerfile.streamlit`, nginx config.
- Retaking screenshots — none exist yet.
