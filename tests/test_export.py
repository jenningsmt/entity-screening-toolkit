import csv
import json

from entity_screening.common.schema import (
    ForeignControlFlag,
    MatchStatus,
    ScoreBreakdown,
    ScoredEntity,
    ScreeningHit,
)
from entity_screening.output.export import export_csv


def _scored_entity() -> ScoredEntity:
    hit = ScreeningHit(
        entity_id="e1",
        list_name="opensanctions_consolidated",
        matched_variant="Acme",
        matched_field="name_variants",
        confidence=0.95,
        evidence={"entry_id": "os-1"},
        status=MatchStatus.CANDIDATE_MATCH,
    )
    return ScoredEntity(
        entity_id="e1",
        canonical_name="Acme Corp",
        score=ScoreBreakdown(total=47.5, factors={"screening_hit": 47.5}),
        screening_hits=(hit,),
        run_id="run-1",
    )


def test_export_csv_stamps_export_id_on_every_row(tmp_path):
    out_path = export_csv([_scored_entity()], tmp_path / "out.csv", export_id="export-abc")

    with out_path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    assert len(rows) == 1
    assert rows[0]["export_id"] == "export-abc"
    assert rows[0]["run_id"] == "run-1"
    assert rows[0]["status"] == "candidate_match"


def test_export_csv_two_calls_can_carry_different_export_ids(tmp_path):
    entity = _scored_entity()
    export_csv([entity], tmp_path / "a.csv", export_id="export-1")
    export_csv([entity], tmp_path / "b.csv", export_id="export-2")

    with (tmp_path / "a.csv").open(encoding="utf-8") as fh:
        row_a = next(csv.DictReader(fh))
    with (tmp_path / "b.csv").open(encoding="utf-8") as fh:
        row_b = next(csv.DictReader(fh))

    assert row_a["export_id"] == "export-1"
    assert row_b["export_id"] == "export-2"


def test_export_csv_reports_candidate_match_for_an_ownership_flag_with_no_screening_hit(tmp_path):
    """A foreign-control flag is a genuine finding even without a screening
    hit — status must not report "no_hit" for it (Epic C)."""
    flag = ForeignControlFlag(
        entity_id="e2",
        entity_lei="LEI-SUB",
        entity_jurisdiction="US",
        ultimate_parent_lei="LEI-ULTIMATE-DE",
        ultimate_parent_name="Fixture Ultimate Parent GmbH",
        ultimate_parent_jurisdiction="DE",
        relationship_path=("LEI-SUB", "LEI-ULTIMATE-DE"),
        match_confidence=1.0,
        evidence={"truncated": False},
        status=MatchStatus.CANDIDATE_MATCH,
    )
    scored = ScoredEntity(
        entity_id="e2",
        canonical_name="Fixture Subsidiary Corp",
        score=ScoreBreakdown(total=30.0, factors={"foreign_control": 30.0}),
        screening_hits=(),
        run_id="run-1",
        ownership_flags=(flag,),
    )

    out_path = export_csv([scored], tmp_path / "out.csv", export_id="export-abc")
    with out_path.open(encoding="utf-8") as fh:
        row = next(csv.DictReader(fh))

    assert row["status"] == "candidate_match"
    exported_flags = json.loads(row["ownership_flags"])
    assert len(exported_flags) == 1
    assert exported_flags[0]["ultimate_parent_jurisdiction"] == "DE"
