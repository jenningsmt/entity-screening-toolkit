"""Section 9, checked at the boundary: no personal data ever reaches a
manifest or a log. Manifests record dataset/case provenance only; `case_id`
is the sole join key back to the subject, whose data lives in the `subjects`
table with field-level classification and is redacted by default on export.

The investigative file itself legitimately names the subject -- it is the
file about them. Manifests and logs do not.
"""
from __future__ import annotations

import json

from entity_screening.case import demo, export, service
from entity_screening.common import storage
from entity_screening.common.schema import CaseState, WorksheetActionKind
from entity_screening.pipeline import reconcile_case

# Values from tests/fixtures/demo_case/subject.json that must never appear in
# a manifest or a log.
PII_STRINGS = ["Wei Chen", "SYNTH-000000", "1984-06-02", "000 Synthetic Ave"]


def test_no_pii_in_any_manifest_or_log_for_a_fully_worked_case(tmp_path):
    db_path = tmp_path / "case.duckdb"
    runs_dir = tmp_path / "runs"
    conn = storage.connect(db_path)
    demo.build_demo_case(conn)
    conn.close()

    reconcile_case(
        "demo",
        db_path=db_path,
        runs_dir=runs_dir,
        works_fixture=demo.load_demo_works_fixture(),
        gleif_lei_file=demo.DEMO_GLEIF_LEI_FILE,
        gleif_relationships_file=demo.DEMO_GLEIF_RELATIONSHIPS_FILE,
    )

    conn = storage.connect(db_path)
    for row in service.worksheet(conn, "demo").rows:
        service.record_action(
            conn, "demo", row.finding.finding_id, WorksheetActionKind.DISMISS,
            "analyst_judgment_not_material", "reviewed", "analyst.a",
        )
    for row in service.worksheet(conn, "demo").tie_rows:
        service.record_tie_action(
            conn, "demo", row.tie.tie_id, WorksheetActionKind.ESCALATE,
            "needs_counterintelligence_referral", "reviewed", "analyst.a",
        )
    service.transition(conn, "demo", CaseState.ADJUDICATION)
    service.record_adjudication(conn, "demo", "Cleared.", "Proceed.", "analyst.a")
    export.export_investigative_file(conn, "demo", fmt="json", runs_dir=runs_dir)
    conn.close()

    # Every manifest.json and every *.jsonl log under the runs dir.
    checked = 0
    for path in list(runs_dir.rglob("*.json")) + list(runs_dir.rglob("*.jsonl")):
        if path.name == "investigative_file.json":
            continue  # the file about the subject legitimately names them
        text = path.read_text(encoding="utf-8")
        for pii in PII_STRINGS:
            assert pii not in text, f"{pii!r} leaked into {path}"
        checked += 1
    assert checked > 0, "expected at least a reconciliation manifest to check"

    # The reconciliation manifest specifically: case_id, counts, threshold -- no subject.
    recon = json.loads((runs_dir / "cases" / "demo" / "reconciliation.json").read_text())
    assert recon["case_id"] == "demo"
    assert set(recon) >= {"discovery_sources", "finding_count", "tie_count", "reconciliation_threshold"}
