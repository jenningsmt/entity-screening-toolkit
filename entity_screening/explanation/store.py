"""DuckDB persistence for MatchExplanation. Columns are named explicitly in
every INSERT/SELECT (never `INSERT INTO explanations VALUES (...)` /
`SELECT *`), the same discipline `case/store.py`'s `_CASE_COLUMNS`/
`_FINDING_COLUMNS` use and for the same reason: a positional statement
silently misaligns the moment this table's column layout is ever migrated,
which a name-addressed one cannot (entity_screening/common/storage.py's
`cases` table migration, step 6, is the concrete precedent this guards
against repeating)."""
from __future__ import annotations

import json

import duckdb

from entity_screening.explanation.schema import Citation, MatchExplanation, ObservationKind

_EXPLANATION_COLUMNS = (
    "explanation_id, observation_kind, observation_id, case_id, recitation, "
    "synthesis_sentence, citations, evidence_hash, model, prompt_version, "
    "generated_at, synthetic"
)


def _citation_to_dict(c: Citation) -> dict:
    return {"cited_text": c.cited_text, "start_char": c.start_char, "end_char": c.end_char}


def _citation_from_dict(d: dict) -> Citation:
    return Citation(cited_text=d["cited_text"], start_char=d["start_char"], end_char=d["end_char"])


def save_explanation(conn: duckdb.DuckDBPyConnection, explanation: MatchExplanation) -> None:
    conn.execute(
        "DELETE FROM explanations WHERE observation_id = ? AND evidence_hash = ?",
        [explanation.observation_id, explanation.evidence_hash],
    )
    conn.execute(
        f"INSERT INTO explanations ({_EXPLANATION_COLUMNS}) VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            explanation.explanation_id,
            explanation.observation_kind.value,
            explanation.observation_id,
            explanation.case_id,
            explanation.recitation,
            explanation.synthesis_sentence,
            json.dumps([_citation_to_dict(c) for c in explanation.citations]),
            explanation.evidence_hash,
            explanation.model,
            explanation.prompt_version,
            explanation.generated_at,
            explanation.synthetic,
        ],
    )


def _row_to_explanation(row: tuple) -> MatchExplanation:
    (
        explanation_id,
        observation_kind,
        observation_id,
        case_id,
        recitation,
        synthesis_sentence,
        citations,
        evidence_hash,
        model,
        prompt_version,
        generated_at,
        synthetic,
    ) = row
    return MatchExplanation(
        explanation_id=explanation_id,
        observation_kind=ObservationKind(observation_kind),
        observation_id=observation_id,
        case_id=case_id,
        recitation=recitation,
        synthesis_sentence=synthesis_sentence,
        citations=tuple(_citation_from_dict(d) for d in json.loads(citations)),
        evidence_hash=evidence_hash,
        model=model,
        prompt_version=prompt_version,
        generated_at=generated_at,
        synthetic=bool(synthetic),
    )


def load_explanation(
    conn: duckdb.DuckDBPyConnection, observation_id: str, evidence_hash: str
) -> MatchExplanation | None:
    row = conn.execute(
        f"SELECT {_EXPLANATION_COLUMNS} FROM explanations "
        "WHERE observation_id = ? AND evidence_hash = ?",
        [observation_id, evidence_hash],
    ).fetchone()
    return _row_to_explanation(row) if row is not None else None
