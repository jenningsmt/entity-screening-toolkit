"""Streamlit review UI: a scored, filterable, explainable candidate-match table
with adjustable rubric weights (docs/requirements.md Section 7 / Epic F).

Run with: streamlit run app.py
"""
from __future__ import annotations

from dataclasses import fields as dc_fields
from pathlib import Path

import pandas as pd
import streamlit as st

from entity_screening.cli import resolve_entities_from_nsf
from entity_screening.ingestion.base import IngestionErrorLog
from entity_screening.ingestion.nsf import NSFAwardIngester
from entity_screening.ingestion.opensanctions import OpenSanctionsTargetsIngester
from entity_screening.resolution.matcher import DEFAULT_THRESHOLD
from entity_screening.screening.lists import OpenSanctionsList
from entity_screening.screening.screen import screen_entity
from entity_screening.scoring.rubric import STOCK_RUBRIC, ScoringRubric
from entity_screening.scoring.score import score_entity

st.set_page_config(page_title="Entity & Research-Affiliation Screening Toolkit", layout="wide")

st.title("Entity & Research-Affiliation Screening Toolkit")
st.caption(
    "Portfolio project — every result below is a **scored candidate**, never a "
    "confirmed finding. See docs/requirements.md for non-goals and methodology."
)

with st.sidebar:
    st.header("Data sources")
    nsf_file = st.text_input("NSF awards JSON file", value="tests/fixtures/sample_nsf_awards.json")
    opensanctions_file = st.text_input(
        "OpenSanctions targets.simple.csv", value="tests/fixtures/sample_opensanctions_targets.csv"
    )

    st.header("Scoring rubric")
    st.caption("Adjust weights and re-score instantly — no code changes required.")
    rubric_kwargs = {}
    for f in dc_fields(STOCK_RUBRIC):
        default = getattr(STOCK_RUBRIC, f.name)
        rubric_kwargs[f.name] = st.slider(
            f.name.replace("_", " "), min_value=0.0, max_value=default * 3 or 10.0,
            value=default, step=max(default / 20, 0.1) if default else 1.0,
        )
    rubric = ScoringRubric(**rubric_kwargs)

    threshold = st.slider("Screening match threshold", 0.0, 1.0, DEFAULT_THRESHOLD, 0.01)
    run_button = st.button("Run screening", type="primary")


@st.cache_data(show_spinner=False)
def _load_and_screen(nsf_path: str, opensanctions_path: str, threshold: float):
    error_log = IngestionErrorLog(Path("data/processed/runs/_streamlit_scratch/ingestion_errors.jsonl"))
    nsf_records = list(
        NSFAwardIngester(error_log, local_file=nsf_path).stream_records()
    )
    os_records = list(
        OpenSanctionsTargetsIngester(error_log, csv_path=opensanctions_path).stream_records()
    )
    error_log.close()

    entities = resolve_entities_from_nsf(nsf_records)
    concern_list = OpenSanctionsList(os_records)

    results = []
    for entity in entities:
        hits = list(screen_entity(entity, [concern_list], threshold=threshold))
        results.append((entity, hits))
    return results


if run_button or "results" not in st.session_state:
    if not Path(nsf_file).exists() or not Path(opensanctions_file).exists():
        st.error("One or both data source files were not found. Check the sidebar paths.")
        st.stop()
    st.session_state["results"] = _load_and_screen(nsf_file, opensanctions_file, threshold)

results = st.session_state["results"]

rows = []
for entity, hits in results:
    breakdown = score_entity(entity, hits, rubric=rubric)
    rows.append(
        {
            "canonical_name": entity.canonical_name,
            "status": "candidate_match" if hits else "no_hit",
            "total_score": round(breakdown.total, 1),
            "factors": ", ".join(f"{k}={v:.1f}" for k, v in breakdown.factors.items()) or "—",
            "list_hits": ", ".join(sorted({h.list_name for h in hits})) or "—",
            "best_match_confidence": round(max((h.confidence for h in hits), default=0.0), 3),
            "_hits": hits,
        }
    )

df = pd.DataFrame(rows).sort_values("total_score", ascending=False)

st.subheader(f"{len(df)} entities screened — {sum(1 for r in rows if r['_hits'])} candidate matches")

show_hits_only = st.checkbox("Show only candidate matches", value=True)
display_df = df[df["status"] == "candidate_match"] if show_hits_only else df

st.dataframe(
    display_df.drop(columns=["_hits"]),
    width="stretch",
    hide_index=True,
)

st.subheader("Evidence trail")
selected_name = st.selectbox(
    "Inspect an entity's evidence",
    options=display_df["canonical_name"].tolist() if not display_df.empty else [],
)
if selected_name:
    matching_row = next(r for r in rows if r["canonical_name"] == selected_name)
    for hit in matching_row["_hits"]:
        st.json(
            {
                "list_name": hit.list_name,
                "matched_variant": hit.matched_variant,
                "confidence": hit.confidence,
                "evidence": hit.evidence,
                "status": hit.status.value,
            }
        )
    if not matching_row["_hits"]:
        st.info("No screening hits for this entity.")
