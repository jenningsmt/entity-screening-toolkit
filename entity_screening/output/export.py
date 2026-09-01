"""CSV/Excel export of candidate matches with their evidence trail (Epic G)."""
from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from pathlib import Path

from entity_screening.common.schema import ScoredEntity

FIELDNAMES = (
    "run_id",
    "entity_id",
    "canonical_name",
    "status",
    "total_score",
    "score_factors",
    "screening_hits",
)


def _serialize_row(scored: ScoredEntity) -> dict:
    hits = [
        {
            "list_name": hit.list_name,
            "matched_variant": hit.matched_variant,
            "confidence": hit.confidence,
            "evidence": hit.evidence,
            "status": hit.status.value,
        }
        for hit in scored.screening_hits
    ]
    return {
        "run_id": scored.run_id,
        "entity_id": scored.entity_id,
        "canonical_name": scored.canonical_name,
        "status": "candidate_match" if hits else "no_hit",
        "total_score": scored.score.total,
        "score_factors": json.dumps(scored.score.factors, sort_keys=True),
        "screening_hits": json.dumps(hits, sort_keys=True),
    }


def export_csv(scored_entities: Iterable[ScoredEntity], out_path: Path | str) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        for scored in scored_entities:
            writer.writerow(_serialize_row(scored))
    return out_path


def export_excel(scored_entities: Iterable[ScoredEntity], out_path: Path | str) -> Path:
    import pandas as pd

    rows = [_serialize_row(s) for s in scored_entities]
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=list(FIELDNAMES)).to_excel(out_path, index=False)
    return out_path
