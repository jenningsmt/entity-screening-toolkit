"""CSV/Excel export of candidate matches with their evidence trail (Epic G)."""
from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from pathlib import Path

from entity_screening.common.schema import ScoredEntity

FIELDNAMES = (
    "export_id",
    "run_id",
    "entity_id",
    "canonical_name",
    "status",
    "total_score",
    "score_factors",
    "screening_hits",
    "ownership_flags",
)


def _serialize_row(scored: ScoredEntity, export_id: str) -> dict:
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
    ownership_flags = [
        {
            "entity_lei": flag.entity_lei,
            "entity_jurisdiction": flag.entity_jurisdiction,
            "ultimate_parent_lei": flag.ultimate_parent_lei,
            "ultimate_parent_name": flag.ultimate_parent_name,
            "ultimate_parent_jurisdiction": flag.ultimate_parent_jurisdiction,
            "match_confidence": flag.match_confidence,
            "evidence": flag.evidence,
            "status": flag.status.value,
        }
        for flag in scored.ownership_flags
    ]
    # A foreign-control flag is a genuine candidate finding even with no
    # screening-list hit — "no_hit" would misreport a real result as nothing
    # found (Epic C).
    status = "candidate_match" if (hits or ownership_flags) else "no_hit"
    return {
        "export_id": export_id,
        "run_id": scored.run_id,
        "entity_id": scored.entity_id,
        "canonical_name": scored.canonical_name,
        "status": status,
        "total_score": scored.score.total,
        "score_factors": json.dumps(scored.score.factors, sort_keys=True),
        "screening_hits": json.dumps(hits, sort_keys=True),
        "ownership_flags": json.dumps(ownership_flags, sort_keys=True),
    }


def export_csv(
    scored_entities: Iterable[ScoredEntity], out_path: Path | str, export_id: str
) -> Path:
    """`export_id` ties every row back to the ExportManifest (see
    common/manifest.py) that records exactly which rubric produced these
    score values — never assume that's the same rubric as the source run's
    original RunManifest (see docs/methodology.md)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        for scored in scored_entities:
            writer.writerow(_serialize_row(scored, export_id))
    return out_path


def export_excel(
    scored_entities: Iterable[ScoredEntity], out_path: Path | str, export_id: str
) -> Path:
    import pandas as pd

    rows = [_serialize_row(s, export_id) for s in scored_entities]
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=list(FIELDNAMES)).to_excel(out_path, index=False)
    return out_path
