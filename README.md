# Entity & Research-Affiliation Screening Toolkit

**Status: early development. Working title — not yet renamed for public release.**

## What this is not, first

This is a public, non-classified, AI-assisted-development portfolio project. It is **not**:

- a production compliance or investigative tool
- a source of confirmed findings — every match this tool produces is a scored *candidate*, never a confirmed determination
- a system covering secrecy-jurisdiction ownership (BVI/Cayman/Panama-style structures) — that's a different, deliberately out-of-scope question from the foreign-ownership/affiliation screening this project does cover

See `docs/requirements.md` Section 3 (Non-Goals) for the full statement.

## What this is

An entity-resolution and foreign-affiliation due-diligence screening toolkit, built against open datasets (NSF award data, OpenSanctions, GLEIF, Section 117 foreign gift/contract disclosures, OpenAlex bibliometric data, and others), reproducing — at hobby scale — the kind of organizational due-diligence and affiliation-matching capability used in commercial research-security and compliance platforms.

Built the same way as this author's other independent projects ([ed-sector-surveyor](https://github.com/jenningsmt/ed-sector-surveyor), [ed-colony-scout](https://github.com/jenningsmt/ed-colony-scout), [ed-expedition-ledger](https://github.com/jenningsmt/ed-expedition-ledger), [ring-density-monitor](https://github.com/jenningsmt/ring-density-monitor)): Python, AI-assisted ("vibe coding") development with Claude, tested, packaged, and documented for public release.

## Documentation

- [`docs/requirements.md`](docs/requirements.md) — full requirements: data sources, functional requirements (epics/stories/acceptance criteria), technology stack, storage estimates, and deployment plan.
- [`docs/architecture.md`](docs/architecture.md) — pipeline-stage breakdown and module map.
- [`docs/methodology.md`](docs/methodology.md) — how to read a run's manifest, and this version's known limitations.
- [`docs/data_sources.md`](docs/data_sources.md) — per-source license and attribution terms.
- [`docs/plans/`](docs/plans/) — the design/implementation plans reviewed and approved before each major piece was built, kept as a historical record.

## Quickstart

Batch CLI (no server required):

```
pip install -r requirements.txt
python -m entity_screening.cli validate
python -m entity_screening.cli run \
    --nsf-file tests/fixtures/sample_nsf_awards.json \
    --opensanctions-file tests/fixtures/sample_opensanctions_targets.csv \
    --excel
pytest
```

Interactive review UI (two processes — the Streamlit app is a thin client of the API,
not a direct pipeline caller):

```
uvicorn entity_screening.api.main:app --reload
streamlit run app.py   # in a second terminal
```

Or the same two services as containers (the wrapper sets `GIT_COMMIT` from
your current checkout before building, so the "Run provenance" panel in the
UI shows a real commit hash instead of null — a bare `docker compose up
--build` will silently skip that):

```
scripts\compose-up.ps1
```

## Status

**V1 + Epic C built:** NSF Award Search + OpenSanctions ingestion, fuzzy name/alias
resolution, entity-of-concern screening against both OpenSanctions and DoD's Section
1260H list, a GLEIF-backed ownership graph with foreign-control (parent-jurisdiction)
flagging, an editable-weight scoring rubric, CSV/Excel export with a reproducibility
manifest, a FastAPI layer over the pipeline with a Streamlit UI as its thin client, CI
(GitHub Actions, including a real Docker Compose integration job), a two-container
Docker Compose setup (API + UI), and a pytest suite including a known-difficult-entity
regression set. Section 117 disclosures and the Seven Sons seed list (the rest of "V2"
per the roadmap's own text) and V3 (OpenAlex bibliometric layer, LLM-based
evidence-grounded explanations) are not yet built, per the phased roadmap in
`docs/requirements.md` Section 12 and the Section 9a addendum.
