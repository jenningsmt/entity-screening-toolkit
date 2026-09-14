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
        [_declared("University of Texas at Austin", "cv", "2010", "2014")],
    )
    findings = reconcile(
        "c1", "r1", decl, [_discovered("University of Texas at Dallas", "2011", "2013")]
    )
    assert len(findings) == 1
    assert findings[0].factual_basis == FactualBasis.PARTIAL_MATCH_BELOW_THRESHOLD
    assert findings[0].nearest_declared[0].institution_name == "University of Texas at Austin"
    assert 0.85 <= findings[0].nearest_declared[0].best_confidence < RECONCILIATION_THRESHOLD


def test_a_low_shared_word_match_is_a_stark_omission_not_a_partial():
    # "Fudan University" vs "Stanford University" share only "university" --
    # ~0.74 on token-sort, not a real near-match.
    decl = _declaration(
        [DeclarationSource("cv", "cv", True, ScopeKind.FULL_HISTORY, {})],
        [_declared("Stanford University", "cv", "2010", "2014")],
    )
    findings = reconcile("c1", "r1", decl, [_discovered("Fudan University", "2011", "2013")])
    assert len(findings) == 1
    assert findings[0].factual_basis == FactualBasis.ABSENT_FROM_IN_SCOPE_SOURCE


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

    manifest, findings, ties = reconcile_case(
        demo.DEMO_CASE_ID,
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        works_fixture=demo.load_demo_works_fixture(),
        gleif_lei_file=demo.DEMO_GLEIF_LEI_FILE,
        gleif_relationships_file=demo.DEMO_GLEIF_RELATIONSHIPS_FILE,
    )

    # Two undisclosed institutions become findings (the Sec. 51B.153 test).
    names = sorted(f.discovered.institution_name for f in findings)
    assert names == ["Beijing Institute of Technology", "Zhejiang University"]
    assert all(f.factual_basis == FactualBasis.ABSENT_FROM_IN_SCOPE_SOURCE for f in findings)
    assert all(f.discovered.source == "openalex" for f in findings)

    # Exactly one concern tie (the Sec. 51B.151(b) test): the declared
    # employer's ultimate parent on the real 1260H list.
    assert len(ties) == 1
    (tie,) = ties
    assert tie.tie_kind.value == "declared_employer_ultimate_parent"
    assert tie.concern_entity_name == "NIO INC."
    assert [h.list_name for h in tie.concern_list_evidence] == ["dod_section_1260h"]
    assert tie.related_finding_id is None  # an ownership tie has no corresponding finding

    # Manifest: opaque case_id, no subject identity.
    blob = json.dumps(manifest.to_dict())
    assert "Wei Chen" not in blob
    assert manifest.case_id == "demo"
    assert manifest.finding_count == 2
    assert manifest.tie_count == 1

    conn = storage.connect(db_path)
    assert store.load_case(conn, "demo").state == CaseState.WORKSHEET
    assert len(store.load_findings(conn, "demo")) == 2
    assert len(store.load_ties(conn, "demo")) == 1
    conn.close()


def test_ownership_tie_evidence_carries_attribution_for_both_the_list_and_gleif(tmp_path):
    db_path = tmp_path / "case.duckdb"
    conn = storage.connect(db_path)
    demo.build_demo_case(conn)
    conn.close()

    _, _, ties = reconcile_case(
        demo.DEMO_CASE_ID,
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        works_fixture=demo.load_demo_works_fixture(),
        gleif_lei_file=demo.DEMO_GLEIF_LEI_FILE,
        gleif_relationships_file=demo.DEMO_GLEIF_RELATIONSHIPS_FILE,
    )
    hit = ties[0].concern_list_evidence[0]
    assert hit.entity_id == "demo-aff-subsidiary"  # a stable id, not an entity name (also-fix)
    assert hit.evidence["source_attribution"]["attribution"]
    assert hit.evidence["source_attribution"]["license"]
    assert hit.evidence["ownership_path"]["source_attribution"]["license"]
    assert hit.evidence["ownership_path"]["declared_employer_name"] == "Nanjing Zhongke Robotics Co., Ltd."


def test_ownership_tie_is_emitted_even_when_the_parent_is_itself_declared(tmp_path):
    from entity_screening.common import storage as st
    from entity_screening.case import store as cs
    from entity_screening.common.schema import DeclaredAffiliation as DA

    db_path = tmp_path / "case.duckdb"
    conn = st.connect(db_path)
    demo.build_demo_case(conn)
    decl = cs.load_declaration_for_subject(conn, "demo-subject")
    # Add the ultimate parent as a declared affiliation of its own.
    decl = type(decl)(
        declaration_id=decl.declaration_id,
        subject_id=decl.subject_id,
        synthetic=True,
        sources=decl.sources,
        affiliations=decl.affiliations
        + (
            DA("demo-aff-avic", "demo-cv", "NIO INC.",
               "CN", "consultant", "2020", "2021", "employment"),
        ),
    )
    cs.save_declaration(conn, decl)
    conn.close()

    _, _, ties = reconcile_case(
        demo.DEMO_CASE_ID,
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        works_fixture=demo.load_demo_works_fixture(),
        gleif_lei_file=demo.DEMO_GLEIF_LEI_FILE,
        gleif_relationships_file=demo.DEMO_GLEIF_RELATIONSHIPS_FILE,
    )
    # The parent being declared does not suppress the Sec. 51B.151(b) tie.
    assert any(t.concern_entity_name == "NIO INC." for t in ties)


def test_both_at_once_produces_one_finding_and_one_tie_joined_by_id(tmp_path):
    """An affiliation that is BOTH undisclosed AND concern-listed produces a
    Finding (Sec. 51B.153) and a ConcernTie (Sec. 51B.151(b)) -- two
    artifacts, paired by tie.related_finding_id (a stored join, never a name
    match)."""
    db_path = tmp_path / "case.duckdb"
    conn = storage.connect(db_path)
    demo.build_demo_case(conn)
    conn.close()

    # The synthetic subject "published" while at a real 1260H entity that
    # their declaration never mentions.
    works = {
        "works": [
            {
                "id": "https://openalex.org/SYNTH-BOTH",
                "title": "Synthetic both-at-once paper",
                "publication_date": "2017-01-01",
                "authorships": [
                    {
                        "is_subject": True,
                        "author_position": "first",
                        "author": {"id": "https://openalex.org/SYNTH-A1", "display_name": "Wei Chen"},
                        "institutions": [
                            {
                                "id": "https://openalex.org/SYNTH-I-AVIC",
                                "display_name": "NIO INC.",
                                "country_code": "CN",
                            }
                        ],
                    }
                ],
            }
        ]
    }

    _, findings, ties = reconcile_case(
        demo.DEMO_CASE_ID,
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        works_fixture=works["works"],
        gleif_lei_file=demo.DEMO_GLEIF_LEI_FILE,
        gleif_relationships_file=demo.DEMO_GLEIF_RELATIONSHIPS_FILE,
    )

    nio_findings = [f for f in findings if "NIO" in f.discovered.institution_name]
    own_ties = [t for t in ties if t.tie_kind.value == "own_affiliation_history"]
    assert len(nio_findings) == 1
    assert len(own_ties) == 1
    assert own_ties[0].related_finding_id == nio_findings[0].finding_id


def test_reconcile_case_is_current_state_not_append(tmp_path):
    db_path = tmp_path / "case.duckdb"
    conn = storage.connect(db_path)
    demo.build_demo_case(conn)
    conn.close()

    kwargs = dict(
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        works_fixture=demo.load_demo_works_fixture(),
        gleif_lei_file=demo.DEMO_GLEIF_LEI_FILE,
        gleif_relationships_file=demo.DEMO_GLEIF_RELATIONSHIPS_FILE,
    )
    _, first_f, first_t = reconcile_case(demo.DEMO_CASE_ID, **kwargs)
    _, second_f, second_t = reconcile_case(demo.DEMO_CASE_ID, **kwargs)

    conn = storage.connect(db_path)
    assert len(store.load_findings(conn, "demo")) == len(first_f) == len(second_f) == 2
    assert len(store.load_ties(conn, "demo")) == len(first_t) == len(second_t) == 1
    conn.close()
