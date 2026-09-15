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
    CaseKind,
    CaseState,
    Certification,
    ConcernTie,
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
    TieAction,
    TieKind,
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
        declaration_id="decl-1",
        trigger="visiting scholar appointment",
        access_scope="research data, lab systems",
        coverage_basis=CoverageBasis.FOREIGN_ADVERSARY_TIE,
        synthetic=True,
        case_kind=CaseKind.HB127_RESEARCHER_SCREENING,
        state=CaseState.INTAKE,
        statutory_deadline=date(2026, 10, 1),
    )


def _finding() -> Finding:
    return Finding(
        finding_id="find-1",
        case_id="case-1",
        run_id="run-1",
        discovered=DiscoveredAffiliation(
            source="openalex",
            institution_name="Beijing Institute of Technology",
            country="CN",
            country_on_adversary_list=None,
            adversary_list_version=None,
            first_observed="2015",
            last_observed="2017",
            record_count=3,
            role="publication_affiliation",
            source_refs=("W1", "W2"),
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
    )


def _tie() -> ConcernTie:
    return ConcernTie(
        tie_id="tie-1",
        case_id="case-1",
        run_id="run-1",
        tie_kind=TieKind.DECLARED_EMPLOYER_ULTIMATE_PARENT,
        anchor_affiliation_id="demo-aff-subsidiary",
        related_finding_id=None,
        concern_entity_name="Real Parent Corp",
        country="CN",
        country_on_adversary_list=None,
        adversary_list_version=None,
        first_observed=None,
        last_observed=None,
        record_count=1,
        concern_list_evidence=(
            ScreeningHit(
                entity_id="demo-aff-subsidiary",
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
                entity_id="demo-aff-subsidiary",
                entity_lei="LEI-AAA",
                entity_jurisdiction="CN",
                ultimate_parent_lei="LEI-BBB",
                ultimate_parent_name="Real Parent Corp",
                ultimate_parent_jurisdiction="DE",
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


def test_concern_ties_round_trip_and_are_current_state(tmp_path):
    conn = _conn(tmp_path)
    store.replace_ties(conn, "case-1", [_tie()])
    store.replace_ties(conn, "case-1", [_tie()])  # replace, not append
    loaded = store.load_ties(conn, "case-1")
    assert len(loaded) == 1
    assert loaded[0] == _tie()
    conn.close()


def test_two_declarations_for_one_subject_are_disambiguated_by_case(tmp_path):
    """Step 6's recurrence fix: a subject can have more than one Declaration
    over time (one per annual disclosure cycle). Each Case must resolve back
    to its OWN declaration via Case.declaration_id, not an arbitrary one
    picked by load_declaration_for_subject's un-ordered .fetchone()."""
    conn = _conn(tmp_path)
    store.save_subject(conn, _subject())

    decl_1 = _declaration()
    decl_2 = Declaration(
        declaration_id="decl-2",
        subject_id="subj-1",
        synthetic=True,
        sources=(),
        affiliations=(),
    )
    store.save_declaration(conn, decl_1)
    store.save_declaration(conn, decl_2)

    case_1 = _case()
    case_2 = Case(
        case_id="case-2",
        subject_id="subj-1",
        declaration_id="decl-2",
        trigger="Annual Outside-Interest disclosure, FY2027",
        access_scope="N/A -- annual compliance certification",
        coverage_basis=None,
        synthetic=True,
        case_kind=CaseKind.COI_ANNUAL_DISCLOSURE,
        state=CaseState.INTAKE,
    )
    store.save_case(conn, case_1)
    store.save_case(conn, case_2)

    loaded_1 = store.load_case(conn, "case-1")
    loaded_2 = store.load_case(conn, "case-2")
    assert store.load_declaration(conn, loaded_1.declaration_id) == decl_1
    assert store.load_declaration(conn, loaded_2.declaration_id) == decl_2
    assert store.load_declaration(conn, loaded_1.declaration_id) != store.load_declaration(
        conn, loaded_2.declaration_id
    )
    assert loaded_2.coverage_basis is None
    assert loaded_2.case_kind == CaseKind.COI_ANNUAL_DISCLOSURE
    conn.close()


def test_tie_actions_append_and_effective_is_latest(tmp_path):
    conn = _conn(tmp_path)
    store.append_tie_action(
        conn, "case-1",
        TieAction("tie-1", WorksheetActionKind.ESCALATE, "needs_supervisor_review", "", "a", "2026-09-06T10:00:00Z"),
    )
    store.append_tie_action(
        conn, "case-1",
        TieAction("tie-1", WorksheetActionKind.DISMISS, "historical_or_divested_relationship", "divested 2019", "a", "2026-09-06T11:00:00Z"),
    )
    assert len(store.load_tie_actions(conn, "case-1")) == 2
    assert store.effective_tie_actions(conn, "case-1")["tie-1"].action == WorksheetActionKind.DISMISS
    conn.close()


def test_load_findings_tolerates_a_pre_migration_row_with_the_two_dropped_columns(tmp_path):
    """A DuckDB file created before concern_list_evidence / ownership_evidence
    were dropped keeps those columns. load_findings names its columns
    explicitly, so it reads such a row cleanly."""
    conn = _conn(tmp_path)
    conn.execute("ALTER TABLE findings ADD COLUMN IF NOT EXISTS concern_list_evidence JSON")
    conn.execute("ALTER TABLE findings ADD COLUMN IF NOT EXISTS ownership_evidence JSON")
    store.replace_findings(conn, "case-1", [_finding()])
    loaded = store.load_findings(conn, "case-1")
    assert loaded == [_finding()]
    conn.close()


def test_demo_meta_round_trip(tmp_path):
    conn = _conn(tmp_path)
    assert store.demo_meta_get(conn, "fixture_version") is None
    store.demo_meta_set(conn, "fixture_version", "2")
    assert store.demo_meta_get(conn, "fixture_version") == "2"
    store.demo_meta_set(conn, "fixture_version", "3")
    assert store.demo_meta_get(conn, "fixture_version") == "3"
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
