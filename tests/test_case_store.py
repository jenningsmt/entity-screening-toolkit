"""Round-trip persistence for the case model (entity_screening/case/store.py).

All new tables are additive -- storage.connect() creates them like every
other table, with no ALTER against a pre-existing DuckDB file.
"""
from __future__ import annotations

from datetime import date

from entity_screening.case import store
from entity_screening.common import storage
from entity_screening.common.schema import (
    Adjudication,
    Case,
    CaseState,
    Certification,
    CoverageBasis,
    DeclaredAffiliation,
    Declaration,
    DeclarationSearch,
    DeclarationSource,
    DiscoveredAffiliation,
    FactualBasis,
    Finding,
    ForeignControlFlag,
    MatchStatus,
    NearestDeclared,
    ScopeKind,
    ScreeningHit,
    Subject,
    WorksheetAction,
    WorksheetActionKind,
)


def _conn(tmp_path):
    return storage.connect(tmp_path / "case.duckdb")


def _subject() -> Subject:
    return Subject(
        subject_id="subj-1",
        display_name="Wei Chen (synthetic)",
        coverage_basis=CoverageBasis.FOREIGN_ADVERSARY_TIE,
        synthetic=True,
        classified_fields={"date_of_birth": "1980-01-01"},
    )


def _declaration() -> Declaration:
    return Declaration(
        declaration_id="decl-1",
        subject_id="subj-1",
        synthetic=True,
        sources=(
            DeclarationSource(
                source_id="ds160-1",
                kind="ds160",
                present=True,
                scope_kind=ScopeKind.TEMPORAL_WINDOW,
                scope_descriptor={"window_years": 5, "anchor": "2026-01-01"},
            ),
            DeclarationSource(
                source_id="cv-1",
                kind="cv",
                present=True,
                scope_kind=ScopeKind.FULL_HISTORY,
                scope_descriptor={},
            ),
        ),
        affiliations=(
            DeclaredAffiliation(
                affiliation_id="aff-1",
                source_id="cv-1",
                institution_name="Tsinghua University",
                country="CN",
                role="postdoc",
                start_date="2012-01-01",
                end_date="2014-01-01",
                activity_kind="employment",
            ),
        ),
    )


def _case() -> Case:
    return Case(
        case_id="case-1",
        subject_id="subj-1",
        trigger="visiting scholar appointment",
        access_scope="research data, lab systems",
        coverage_basis=CoverageBasis.FOREIGN_ADVERSARY_TIE,
        synthetic=True,
        state=CaseState.INTAKE,
        statutory_deadline=date(2026, 10, 1),
    )


def _finding() -> Finding:
    return Finding(
        finding_id="find-1",
        case_id="case-1",
        run_id="run-1",
        discovered=DiscoveredAffiliation(
            source="gleif_ownership",
            institution_name="Synthetic Subsidiary Co., Ltd.",
            country="CN",
            country_on_adversary_list=None,
            adversary_list_version=None,
            first_observed=None,
            last_observed=None,
            record_count=1,
            role="declared_employer_parent",
            source_refs=("LEI-AAA", "LEI-BBB"),
        ),
        declaration_search=(
            DeclarationSearch(
                source_kind="cv",
                present=True,
                scope_kind=ScopeKind.FULL_HISTORY,
                scope_descriptor={},
                covers_this_item=True,
            ),
        ),
        factual_basis=FactualBasis.ABSENT_FROM_IN_SCOPE_SOURCE,
        nearest_declared=(
            NearestDeclared(
                declared_affiliation_id="aff-1",
                institution_name="Tsinghua University",
                best_confidence=0.41,
                match_basis="fuzzy_token_sort",
                cleared_name=False,
                scope_compatible=True,
            ),
        ),
        concern_list_evidence=(
            ScreeningHit(
                entity_id="find-1",
                list_name="dod_section_1260h",
                matched_variant="Real Parent Corp",
                matched_field="ownership_ultimate_parent",
                confidence=1.0,
                evidence={"entry_id": "1260h-7", "source_attribution": {"attribution": "x", "license": "y"}},
                status=MatchStatus.CANDIDATE_MATCH,
                producer="ownership_parent",
            ),
        ),
        ownership_evidence=(
            ForeignControlFlag(
                entity_id="find-1",
                entity_lei="LEI-AAA",
                entity_jurisdiction="CN",
                ultimate_parent_lei="LEI-BBB",
                ultimate_parent_name="Real Parent Corp",
                ultimate_parent_jurisdiction="CN",
                relationship_path=("LEI-AAA", "LEI-BBB"),
                match_confidence=0.95,
                evidence={"truncated": False, "source_attribution": {"attribution": "GLEIF", "license": "CC0"}},
                status=MatchStatus.CANDIDATE_MATCH,
            ),
        ),
    )


def test_subject_declaration_case_round_trip(tmp_path):
    conn = _conn(tmp_path)
    store.save_subject(conn, _subject())
    store.save_declaration(conn, _declaration())
    store.save_case(conn, _case())

    assert store.load_subject(conn, "subj-1") == _subject()
    assert store.load_declaration(conn, "decl-1") == _declaration()
    assert store.load_declaration_for_subject(conn, "subj-1") == _declaration()
    assert store.load_case(conn, "case-1") == _case()
    conn.close()


def test_findings_are_current_state_per_case(tmp_path):
    conn = _conn(tmp_path)
    store.replace_findings(conn, "case-1", [_finding()])
    store.replace_findings(conn, "case-1", [_finding()])  # replace, not append
    assert len(store.load_findings(conn, "case-1")) == 1
    assert store.load_findings(conn, "case-1")[0] == _finding()

    # Re-running reconciliation replaces the set rather than accumulating.
    store.replace_findings(conn, "case-1", [_finding(), _finding()])
    assert len(store.load_findings(conn, "case-1")) == 2
    conn.close()


def test_worksheet_actions_append_and_effective_is_latest(tmp_path):
    conn = _conn(tmp_path)
    store.append_worksheet_action(
        conn,
        "case-1",
        WorksheetAction("find-1", WorksheetActionKind.ESCALATE, "needs_review", "", "analyst.a", "2026-09-06T10:00:00Z"),
    )
    store.append_worksheet_action(
        conn,
        "case-1",
        WorksheetAction("find-1", WorksheetActionKind.DISMISS, "outside_scope", "older than DS-160 window", "analyst.a", "2026-09-06T11:00:00Z"),
    )
    assert len(store.load_worksheet_actions(conn, "case-1")) == 2
    effective = store.effective_actions(conn, "case-1")
    assert effective["find-1"].action == WorksheetActionKind.DISMISS
    conn.close()


def test_adjudications_are_append_only_with_incrementing_seq(tmp_path):
    conn = _conn(tmp_path)
    assert store.next_adjudication_seq(conn, "case-1") == 0
    store.append_adjudication(conn, Adjudication("case-1", 0, "clear", "proceed", "analyst.a", "2026-09-06T12:00:00Z"))
    assert store.next_adjudication_seq(conn, "case-1") == 1
    store.append_adjudication(conn, Adjudication("case-1", 1, "reassess", "hold", "analyst.a", "2026-10-01T09:00:00Z"))
    adj = store.load_adjudications(conn, "case-1")
    assert [a.seq for a in adj] == [0, 1]
    assert adj[0].assessment == "clear"  # prior adjudication intact
    conn.close()


def test_certifications_round_trip(tmp_path):
    conn = _conn(tmp_path)
    store.append_certification(
        conn,
        Certification("case-1", "find-1", "undisclosed 2013 postdoc", "peer-reviewed, publicly listed", "Dr. Head", "2026-09-20T09:00:00Z"),
    )
    certs = store.load_certifications(conn, "case-1")
    assert len(certs) == 1 and certs[0].department_head == "Dr. Head"
    conn.close()
