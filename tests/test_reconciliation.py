"""Reconciliation engine (entity_screening/reconciliation/) -- the
declaration-versus-record diff at the heart of Use Case 01.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from entity_screening.case import demo, store
from entity_screening.common import storage
from entity_screening.common.schema import (
    CaseState,
    DeclaredAffiliation,
    Declaration,
    DeclarationSource,
    DiscoveredAffiliation,
    FactualBasis,
    ScopeKind,
)
from entity_screening.pipeline import reconcile_case
from entity_screening.reconciliation.discover import discover_from_publications
from entity_screening.reconciliation.match import (
    RECONCILIATION_THRESHOLD,
    best_declared_match,
)
from entity_screening.reconciliation.reconcile import reconcile

FIXTURES = Path(__file__).parent / "fixtures" / "demo_case"


def _declared(institution: str, source_id: str, start: str, end: str, kind: str = "employment"):
    return DeclaredAffiliation(
        affiliation_id=f"aff-{institution[:6].lower()}",
        source_id=source_id,
        institution_name=institution,
        country=None,
        role=kind,
        start_date=start,
        end_date=end,
        activity_kind=kind,
    )


def _discovered(institution: str, first: str, last: str, role: str = "publication_affiliation"):
    return DiscoveredAffiliation(
        source="openalex",
        institution_name=institution,
        country=None,
        country_on_adversary_list=None,
        adversary_list_version=None,
        first_observed=first,
        last_observed=last,
        record_count=2,
        role=role,
        source_refs=("W1", "W2"),
    )


def _declaration(sources, affiliations):
    return Declaration(
        declaration_id="d1",
        subject_id="s1",
        synthetic=True,
        sources=tuple(sources),
        affiliations=tuple(affiliations),
    )


# --- matching -------------------------------------------------------------


@pytest.mark.parametrize(
    "discovered_name,declared_name,expect_cleared",
    [
        ("University of Texas at Austin", "University of Texas at Austin", True),
        ("Massachusetts Inst. of Technology", "Massachusetts Institute of Technology", True),
        ("Zhejiang Univ", "Zhejiang University", True),
        ("Qinghua University", "Tsinghua University", True),  # transliteration variant
        # genuinely distinct pairs stay below the threshold -- a real omission
        # must not be silently absorbed.
        ("University of Science and Technology of China", "University of Science and Technology Beijing", False),
        ("Chinese Academy of Sciences", "Chinese Academy of Ordnance Science", False),
    ],
)
def test_reconciliation_threshold_separates_same_from_distinct(
    discovered_name, declared_name, expect_cleared
):
    match = best_declared_match(discovered_name, [_declared(declared_name, "cv", "2010", "2015")])
    assert match is not None
    assert match.cleared is expect_cleared


# --- the diff ------------------------------------------------------------


def test_declared_affiliation_produces_no_finding():
    decl = _declaration(
        [DeclarationSource("cv", "cv", True, ScopeKind.FULL_HISTORY, {})],
        [_declared("Nanjing University", "cv", "2011", "2016")],
    )
    findings = reconcile("c1", "r1", decl, [_discovered("Nanjing University", "2013", "2015")])
    assert findings == []


def test_undisclosed_affiliation_covered_by_full_history_cv_is_in_scope():
    decl = _declaration(
        [DeclarationSource("cv", "cv", True, ScopeKind.FULL_HISTORY, {})],
        [_declared("Nanjing University", "cv", "2011", "2016")],
    )
    findings = reconcile(
        "c1", "r1", decl, [_discovered("Beijing Institute of Technology", "2016", "2017")]
    )
    assert len(findings) == 1
    assert findings[0].factual_basis == FactualBasis.ABSENT_FROM_IN_SCOPE_SOURCE
    trail = {s.source_kind: s.covers_this_item for s in findings[0].declaration_search}
    assert trail == {"cv": True}


def test_old_affiliation_outside_a_ds160_only_declaration_is_outside_scope():
    # The Section 6 trap: DS-160 employment covers five years; a mid-career
    # affiliation older than that is absent only because the form's scope
    # never reached it -- a distinct factual basis, selectable as a class.
    decl = _declaration(
        [DeclarationSource("ds160", "ds160", True, ScopeKind.TEMPORAL_WINDOW,
                           {"window_years": 5, "anchor": "2026-01-15"})],
        [_declared("University of Texas at Austin", "ds160", "2021", "2025")],
    )
    findings = reconcile(
        "c1", "r1", decl, [_discovered("Harbin Engineering University", "2012", "2013")]
    )
    assert len(findings) == 1
    assert findings[0].factual_basis == FactualBasis.ABSENT_OUTSIDE_ALL_SOURCE_SCOPES


def test_near_match_is_classified_as_partial_not_a_stark_omission():
    decl = _declaration(
        [DeclarationSource("cv", "cv", True, ScopeKind.FULL_HISTORY, {})],
        [_declared("Leland Stanford Junior University", "cv", "2010", "2014")],
    )
    findings = reconcile("c1", "r1", decl, [_discovered("Stanford University", "2011", "2013")])
    assert len(findings) == 1
    assert findings[0].factual_basis == FactualBasis.PARTIAL_MATCH_BELOW_THRESHOLD
    assert findings[0].nearest_declared[0].institution_name == "Leland Stanford Junior University"
    assert 0.70 <= findings[0].nearest_declared[0].best_confidence < RECONCILIATION_THRESHOLD


# --- discovery from a fixture -------------------------------------------


def test_discover_from_publications_aggregates_the_fixture():
    works = json.loads((FIXTURES / "works_fixture.json").read_text())["works"]
    discovered = discover_from_publications("Wei Chen", "Texas A&M University", [], works_fixture=works)
    by_name = {d.institution_name: d for d in discovered}
    assert set(by_name) == {
        "University of Texas at Austin",
        "Nanjing University",
        "Beijing Institute of Technology",
        "Zhejiang University",
    }
    assert by_name["University of Texas at Austin"].record_count == 2
    assert by_name["Beijing Institute of Technology"].first_observed == "2016"
    assert by_name["Beijing Institute of Technology"].last_observed == "2017"


# --- pipeline end to end (fixture-driven, no network) ------------------


def test_reconcile_case_end_to_end_against_the_demo_fixtures(tmp_path):
    db_path = tmp_path / "case.duckdb"
    conn = storage.connect(db_path)
    demo.build_demo_case(conn)
    conn.close()

    manifest, findings = reconcile_case(
        demo.DEMO_CASE_ID,
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        works_fixture=demo.load_demo_works_fixture(),
    )

    # The two undisclosed institutions become findings; the two declared
    # ones do not.
    names = sorted(f.discovered.institution_name for f in findings)
    assert names == ["Beijing Institute of Technology", "Zhejiang University"]
    assert all(f.factual_basis == FactualBasis.ABSENT_FROM_IN_SCOPE_SOURCE for f in findings)

    # Manifest carries the opaque case_id and nothing that identifies the
    # subject.
    blob = json.dumps(manifest.to_dict())
    assert "Wei Chen" not in blob
    assert manifest.case_id == "demo"
    assert manifest.finding_count == 2

    # The case advanced to the worksheet.
    conn = storage.connect(db_path)
    assert store.load_case(conn, "demo").state == CaseState.WORKSHEET
    assert len(store.load_findings(conn, "demo")) == 2
    conn.close()


def test_reconcile_case_ownership_path_produces_the_section_10_headline_finding(tmp_path):
    db_path = tmp_path / "case.duckdb"
    conn = storage.connect(db_path)
    demo.build_demo_case(conn)
    conn.close()

    _, findings = reconcile_case(
        demo.DEMO_CASE_ID,
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        works_fixture=demo.load_demo_works_fixture(),
        gleif_lei_file=demo.DEMO_GLEIF_LEI_FILE,
        gleif_relationships_file=demo.DEMO_GLEIF_RELATIONSHIPS_FILE,
    )
    ownership = [f for f in findings if f.discovered.source == "gleif_ownership"]
    assert len(ownership) == 1
    finding = ownership[0]
    # The undisclosed ultimate parent, matched against the real 1260H list.
    assert finding.discovered.institution_name == "Aviation Industry Corporation of China Ltd."
    assert finding.factual_basis == FactualBasis.ABSENT_OUTSIDE_ALL_SOURCE_SCOPES
    assert [h.list_name for h in finding.concern_list_evidence] == ["dod_section_1260h"]

    hit = finding.concern_list_evidence[0]
    # AC 14: attribution + licence reach the finding's evidence, for both the
    # concern list and GLEIF.
    assert hit.evidence["source_attribution"]["attribution"]
    assert hit.evidence["source_attribution"]["license"]
    assert hit.evidence["ownership_path"]["source_attribution"]["license"]
    assert hit.evidence["ownership_path"]["declared_employer_name"] == "Nanjing Zhongke Robotics Co., Ltd."


def test_reconcile_case_is_current_state_not_append(tmp_path):
    db_path = tmp_path / "case.duckdb"
    conn = storage.connect(db_path)
    demo.build_demo_case(conn)
    conn.close()

    kwargs = dict(db_path=db_path, runs_dir=tmp_path / "runs", works_fixture=demo.load_demo_works_fixture())
    _, first = reconcile_case(demo.DEMO_CASE_ID, **kwargs)
    _, second = reconcile_case(demo.DEMO_CASE_ID, **kwargs)

    conn = storage.connect(db_path)
    assert len(store.load_findings(conn, "demo")) == len(first) == len(second) == 2
    conn.close()
