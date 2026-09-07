"""Case lifecycle: the worksheet closure rule, bulk action, adjudication
append-only + re-open, and the Section 6 declaration-scope trap.
"""
from __future__ import annotations

import pytest

from entity_screening.case import demo, service, store
from entity_screening.case.service import CaseStateError
from entity_screening.common import storage
from entity_screening.common.schema import (
    CaseState,
    DeclaredAffiliation,
    Declaration,
    DeclarationSource,
    DiscoveredAffiliation,
    FactualBasis,
    ScopeKind,
    Subject,
    CoverageBasis,
    WorksheetActionKind,
)
from entity_screening.pipeline import reconcile_case
from entity_screening.reconciliation.reconcile import reconcile


def _demo_conn(tmp_path):
    db_path = tmp_path / "case.duckdb"
    conn = storage.connect(db_path)
    demo.build_demo_case(conn)
    conn.close()
    reconcile_case(
        demo.DEMO_CASE_ID,
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        works_fixture=demo.load_demo_works_fixture(),
        gleif_lei_file=demo.DEMO_GLEIF_LEI_FILE,
        gleif_relationships_file=demo.DEMO_GLEIF_RELATIONSHIPS_FILE,
    )
    return storage.connect(db_path)


def _action_all_findings(conn):
    for row in service.worksheet(conn, "demo").rows:
        service.record_action(
            conn, "demo", row.finding.finding_id, WorksheetActionKind.DISMISS,
            "analyst_judgment_not_material", "n/a", "analyst.a",
        )


def _action_all_ties(conn):
    for row in service.worksheet(conn, "demo").tie_rows:
        service.record_tie_action(
            conn, "demo", row.tie.tie_id, WorksheetActionKind.ESCALATE,
            "needs_counterintelligence_referral", "n/a", "analyst.a",
        )


def test_worksheet_cannot_close_while_a_row_of_either_type_is_unactioned(tmp_path):
    conn = _demo_conn(tmp_path)
    view = service.worksheet(conn, "demo")
    assert len(view.rows) == 2 and len(view.tie_rows) == 1
    assert view.can_close is False

    # Action every discrepancy row -- still cannot close: the tie is open.
    _action_all_findings(conn)
    with pytest.raises(CaseStateError):
        service.transition(conn, "demo", CaseState.ADJUDICATION)
    assert service.worksheet(conn, "demo").can_close is False

    # Action the concern tie too.
    _action_all_ties(conn)
    assert service.worksheet(conn, "demo").can_close is True
    service.transition(conn, "demo", CaseState.ADJUDICATION)
    assert store.load_case(conn, "demo").state == CaseState.ADJUDICATION
    conn.close()


def test_bulk_action_dispositions_a_class_with_one_reason_and_one_batch_id(tmp_path):
    conn = _demo_conn(tmp_path)
    view = service.worksheet(conn, "demo")
    ids = [r.finding.finding_id for r in view.rows]
    batch_id, actions = service.record_bulk_action(
        conn, "demo", ids, WorksheetActionKind.DISMISS,
        "analyst_judgment_not_material", "reviewed as a set; none material for this role",
        "analyst.a",
    )
    assert len({a.batch_id for a in actions}) == 1 == len({batch_id})
    effective = store.effective_actions(conn, "demo")
    assert all(effective[i].batch_id == batch_id for i in ids)
    # Findings done; the tie still blocks closure.
    assert service.worksheet(conn, "demo").can_close is False
    _action_all_ties(conn)
    assert service.worksheet(conn, "demo").can_close is True
    conn.close()


def test_bulk_tie_action_shares_one_batch_id(tmp_path):
    conn = _demo_conn(tmp_path)
    tie_ids = [r.tie.tie_id for r in service.worksheet(conn, "demo").tie_rows]
    batch_id, actions = service.record_bulk_tie_action(
        conn, "demo", tie_ids, WorksheetActionKind.DISMISS,
        "historical_or_divested_relationship", "divested 2019", "analyst.a",
    )
    assert {a.batch_id for a in actions} == {batch_id}
    conn.close()


def test_tie_reason_code_must_be_in_the_tie_vocabulary(tmp_path):
    conn = _demo_conn(tmp_path)
    tie_id = service.worksheet(conn, "demo").tie_rows[0].tie.tie_id
    with pytest.raises(ValueError):
        # a discrepancy dismiss code, not a tie one
        service.record_tie_action(
            conn, "demo", tie_id, WorksheetActionKind.DISMISS,
            "outside_declaration_scope", "", "a",
        )
    conn.close()


def test_reason_code_must_be_in_the_controlled_vocabulary(tmp_path):
    conn = _demo_conn(tmp_path)
    fid = service.worksheet(conn, "demo").rows[0].finding.finding_id
    with pytest.raises(ValueError):
        service.record_action(
            conn, "demo", fid, WorksheetActionKind.DISMISS, "not_substantial_enough", "", "a"
        )
    conn.close()


def test_adjudication_is_append_only_and_reopening_keeps_the_prior_one(tmp_path):
    conn = _demo_conn(tmp_path)
    _action_all_findings(conn)
    _action_all_ties(conn)
    service.transition(conn, "demo", CaseState.ADJUDICATION)
    service.record_adjudication(conn, "demo", "No substantial omission.", "Clear to proceed.", "analyst.a")
    service.transition(conn, "demo", CaseState.OUTCOME)
    service.record_outcome(conn, "demo", "cleared", "analyst.a")
    service.transition(conn, "demo", CaseState.CLOSED)

    # New information -> re-open.
    service.reopen_case(conn, "demo")
    assert store.load_case(conn, "demo").state == CaseState.DISCOVERY
    conn.close()

    # Reconcile again, work the worksheet, adjudicate again.
    db_path = tmp_path / "case.duckdb"
    reconcile_case(
        "demo", db_path=db_path, runs_dir=tmp_path / "runs",
        works_fixture=demo.load_demo_works_fixture(),
        gleif_lei_file=demo.DEMO_GLEIF_LEI_FILE,
        gleif_relationships_file=demo.DEMO_GLEIF_RELATIONSHIPS_FILE,
    )
    conn = storage.connect(db_path)
    for row in service.worksheet(conn, "demo").rows:
        service.record_action(
            conn, "demo", row.finding.finding_id, WorksheetActionKind.ESCALATE,
            "needs_supervisor_review", "reassessing after new list release", "analyst.b",
        )
    _action_all_ties(conn)
    service.transition(conn, "demo", CaseState.ADJUDICATION)
    service.record_adjudication(conn, "demo", "Escalating on the new 1260H entry.", "Hold.", "analyst.b")

    adjudications = store.load_adjudications(conn, "demo")
    assert [a.seq for a in adjudications] == [0, 1]
    assert adjudications[0].assessment == "No substantial omission."  # prior intact
    assert adjudications[0].actor == "analyst.a"
    conn.close()


# --- Section 6 declaration-scope trap ---------------------------------------


def test_ds160_only_declaration_classifies_old_affiliations_as_outside_scope():
    """The Section 6 trap: a mid-career researcher with 15 years of
    affiliations and only a five-year DS-160 window. Older affiliations are
    absent only because the form's scope never reached them -- a distinct
    factual basis, selectable as one class for bulk dismissal."""
    decl = Declaration(
        declaration_id="d1",
        subject_id="s1",
        synthetic=True,
        sources=(
            DeclarationSource("ds160", "ds160", True, ScopeKind.TEMPORAL_WINDOW,
                              {"window_years": 5, "anchor": "2026-01-15", "category": "employment"}),
            # No CV attached yet -- a real intake gap.
            DeclarationSource("cv", "cv", False, ScopeKind.FULL_HISTORY, {}),
        ),
        affiliations=(
            DeclaredAffiliation("a1", "ds160", "Stanford University", "US", "postdoc",
                                "2022", "2025", "employment"),
        ),
    )
    discovered = [
        DiscoveredAffiliation("openalex", "Peking University", "CN", None, None,
                              "2009", "2012", 4, "publication_affiliation", ("W1",)),
        DiscoveredAffiliation("openalex", "Fudan University", "CN", None, None,
                              "2013", "2016", 3, "publication_affiliation", ("W2",)),
        DiscoveredAffiliation("openalex", "Stanford University", "US", None, None,
                              "2022", "2024", 5, "publication_affiliation", ("W3",)),
    ]
    findings = reconcile("c1", "r1", decl, discovered)
    # Stanford is declared -> no finding. The two pre-window affiliations are
    # findings, both outside every present source's scope.
    assert {f.discovered.institution_name for f in findings} == {"Peking University", "Fudan University"}
    assert all(f.factual_basis == FactualBasis.ABSENT_OUTSIDE_ALL_SOURCE_SCOPES for f in findings)
    # And the trail shows *why*: the DS-160 window did not reach them.
    for f in findings:
        ds160 = next(s for s in f.declaration_search if s.source_kind == "ds160")
        assert ds160.covers_this_item is False


def test_declaration_model_functions_with_no_ds160_present():
    """A covered person under Sec. 51B.151(a)(2) -- a U.S. citizen with a
    foreign-adversary tie -- has no visa application. The model must work
    with the DS-160 absent."""
    subject = Subject("s1", "US Citizen Researcher", CoverageBasis.FOREIGN_ADVERSARY_TIE, True, {})
    assert subject.coverage_basis == CoverageBasis.FOREIGN_ADVERSARY_TIE
    decl = Declaration(
        declaration_id="d1", subject_id="s1", synthetic=True,
        sources=(
            DeclarationSource("ds160", "ds160", False, ScopeKind.TEMPORAL_WINDOW, {}),
            DeclarationSource("cv", "cv", True, ScopeKind.FULL_HISTORY, {}),
        ),
        affiliations=(
            DeclaredAffiliation("a1", "cv", "MIT", "US", "professor", "2015", None, "employment"),
        ),
    )
    discovered = [
        DiscoveredAffiliation("openalex", "Harbin Institute of Technology", "CN", None, None,
                              "2018", "2020", 2, "publication_affiliation", ("W1",)),
    ]
    findings = reconcile("c1", "r1", decl, discovered)
    assert len(findings) == 1
    # The CV (full history, present) covers it -- a genuine gap, not a scope artifact.
    assert findings[0].factual_basis == FactualBasis.ABSENT_FROM_IN_SCOPE_SOURCE
    trail = {s.source_kind: (s.present, s.covers_this_item) for s in findings[0].declaration_search}
    assert trail == {"ds160": (False, False), "cv": (True, True)}
