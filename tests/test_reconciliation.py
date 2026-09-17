"""Reconciliation engine (entity_screening/reconciliation/) -- the
declaration-versus-record diff at the heart of Use Case 01.
"""
from __future__ import annotations

import datetime
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
    TieKind,
)
from entity_screening.ingestion.base import IngestionErrorLog
from entity_screening.ingestion.dod_1260h import DoD1260HIngester
from entity_screening.ownership.ingest import load_gleif_level1, load_gleif_level2
from entity_screening.pipeline import reconcile_case
from entity_screening.reconciliation.discover import (
    discover_from_publications,
    tie_from_ownership,
    ties_from_declared_affiliations,
)
from entity_screening.screening.adversary_list import load_adversary_list
from entity_screening.screening.lists import DoD1260HList
from entity_screening.reconciliation.match import (
    RECONCILIATION_THRESHOLD,
    best_declared_match,
)
from entity_screening.reconciliation.reconcile import (
    _overlaps_temporal_window,
    build_finding,
    reconcile,
)

FIXTURES = Path(__file__).parent / "fixtures" / "demo_case"
FIXTURES_DIR = Path(__file__).parent / "fixtures"


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
    discovered = discover_from_publications(
        "Wei Chen", "Texas A&M University", load_adversary_list(), works_fixture=works
    )
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


# --- S4/M4: scope_compatible computed for real; category gates TEMPORAL_WINDOW --


def test_overlaps_temporal_window_rejects_a_publication_role_under_an_employment_category():
    """S4/M4: fails on the unmodified tree first -- before this fix, only
    the date check ran, so an OpenAlex-sourced item's dates alone could
    fall inside an employment window even though a publication
    co-affiliation is not evidence of employment."""
    discovered = _discovered("Some University", "2022", "2023")  # role=publication_affiliation
    descriptor = {"window_years": 5, "anchor": "2026-01-15", "category": "employment"}
    assert _overlaps_temporal_window(discovered, descriptor) is False


def test_overlaps_temporal_window_still_covers_a_matching_category_inside_the_window():
    discovered = _discovered("Some University", "2022", "2023", role="employment")
    descriptor = {"window_years": 5, "anchor": "2026-01-15", "category": "employment"}
    assert _overlaps_temporal_window(discovered, descriptor) is True


def test_scope_compatible_is_computed_against_the_demos_own_near_miss_candidate():
    """The demo's own near-miss data point (Beijing Institute of Technology
    vs Tsinghua University, already a fixture in test_case_store.py/
    test_explanation.py) -- Tsinghua is declared under a FULL_HISTORY cv
    source, which admits anything, so scope_compatible must read True even
    though the name match itself doesn't clear."""
    decl = _declaration(
        [DeclarationSource("cv", "cv", True, ScopeKind.FULL_HISTORY, {})],
        [_declared("Tsinghua University", "cv", "2010", "2015")],
    )
    finding = build_finding(
        "c1", "r1", decl, _discovered("Beijing Institute of Technology", "2016", "2017")
    )
    (nearest,) = finding.nearest_declared
    assert nearest.institution_name == "Tsinghua University"
    assert 0.3 <= nearest.best_confidence < 0.5
    assert nearest.scope_compatible is True


def test_scope_compatible_is_false_when_the_declaring_sources_scope_does_not_admit_the_item():
    """The DS-160 Section 6 trap, but for scope_compatible specifically: a
    TEMPORAL_WINDOW source whose window the item's dates fall outside must
    read scope_compatible=False on the near-miss candidate, not the
    hard-coded True the field used to always carry."""
    decl = _declaration(
        [DeclarationSource("ds160", "ds160", True, ScopeKind.TEMPORAL_WINDOW,
                           {"window_years": 5, "anchor": "2026-01-15"})],
        [_declared("University of Texas at Austin", "ds160", "2021", "2025")],
    )
    finding = build_finding(
        "c1", "r1", decl, _discovered("University of Texas at Dallas", "2011", "2013")
    )
    (nearest,) = finding.nearest_declared
    assert nearest.institution_name == "University of Texas at Austin"
    assert nearest.scope_compatible is False


# --- ties_from_declared_affiliations: a declared entity itself listed (S2) --


def test_ties_from_declared_affiliations_ties_a_directly_listed_declared_entity(tmp_path):
    """S2: a declared affiliation with a real DoD 1260H entity (Aviation
    Industry Corporation of China Ltd., already used elsewhere in this
    suite for the same reason -- a real, curated list entry, not an
    invented name) produces a DECLARED_AFFILIATION_DIRECT tie when that
    entity is not independently matched by any discovered item."""
    error_log = IngestionErrorLog(tmp_path / "errors.jsonl")
    dod_list = DoD1260HList(list(DoD1260HIngester(error_log).stream_records()))
    error_log.close()

    declared = [
        DeclaredAffiliation(
            "aff-1", "cv", "Aviation Industry Corporation of China Ltd.", "CN",
            "board_membership", "2020", "2021", "membership",
        )
    ]
    ties = ties_from_declared_affiliations("case-1", "run-1", declared, [dod_list])

    assert len(ties) == 1
    tie = ties[0]
    assert tie.tie_kind == TieKind.DECLARED_AFFILIATION_DIRECT
    assert tie.concern_entity_name == "Aviation Industry Corporation of China Ltd."
    assert tie.related_finding_id is None
    assert tie.concern_list_evidence[0].list_name == "dod_section_1260h"


def test_ties_from_declared_affiliations_produces_zero_new_ties_for_either_demo_case(tmp_path):
    """S2's own binding acceptance criterion: wiring the producer in must
    not change either demo case's tie count -- confirmed, not assumed."""
    db_path = tmp_path / "case.duckdb"
    conn = storage.connect(db_path)
    demo.build_demo_case(conn)
    demo.build_demo_coi_case(conn)
    conn.close()

    for case_id in (demo.DEMO_CASE_ID, demo.DEMO_COI_CASE_ID):
        _, _, ties = reconcile_case(
            case_id,
            db_path=db_path,
            runs_dir=tmp_path / "runs" / case_id,
            works_fixture=demo.load_demo_works_fixture(),
            gleif_lei_file=demo.DEMO_GLEIF_LEI_FILE,
            gleif_relationships_file=demo.DEMO_GLEIF_RELATIONSHIPS_FILE,
        )
        assert len(ties) == 1  # unchanged: the one real ownership tie, still the only tie
        assert ties[0].tie_kind.value == "declared_employer_ultimate_parent"


# --- tie_from_ownership: a real traversal, not a fabricated path (S1) --


def test_tie_from_ownership_walks_a_real_multi_hop_chain(tmp_path):
    """S1: the ownership tie's evidence is a real traversal via
    `parent_chain`, not a fabricated 2-tuple -- MID must appear in the
    resulting ForeignControlFlag's relationship_path, and record_count
    must reflect the real 2-link chain (SUB -> MID -> ULTIMATE), not a
    hard-coded 1."""
    conn = storage.connect(tmp_path / "test.duckdb")
    error_log = IngestionErrorLog(tmp_path / "errors.jsonl")
    load_gleif_level1(
        conn, FIXTURES_DIR / "multi_hop_gleif_lei.csv", datetime.date(2026, 9, 17), error_log
    )
    load_gleif_level2(
        conn, FIXTURES_DIR / "multi_hop_gleif_relationships.csv", datetime.date(2026, 9, 17), error_log
    )
    dod_list = DoD1260HList(list(DoD1260HIngester(error_log).stream_records()))
    error_log.close()

    declared = [
        DeclaredAffiliation(
            "aff-sub", "cv", "Multihop Fixture Subsidiary Co", "US", "engineer",
            "2020", "2021", "employment",
        )
    ]
    ties = tie_from_ownership(
        "case-1", "run-1", declared, conn, [dod_list], load_adversary_list()
    )
    conn.close()

    assert len(ties) == 1
    tie = ties[0]
    assert tie.record_count == 2  # SUB->MID, MID->ULTIMATE: 2 real links
    assert len(tie.ownership_evidence) == 1
    flag = tie.ownership_evidence[0]
    assert flag.relationship_path == ("LEI-MULTIHOP-SUB", "LEI-MULTIHOP-MID", "LEI-MULTIHOP-ULT")


def test_tie_from_ownership_still_ties_a_same_jurisdiction_listed_parent(tmp_path):
    """The regression the first Phase 4 plan draft would have introduced:
    delegating to flag_from_match would silently skip a same-jurisdiction
    ultimate parent before it was ever screened against a concern list.
    A same-jurisdiction, concern-listed parent must still produce a
    ConcernTie -- just with no ForeignControlFlag attached, since it isn't
    foreign control (Epic C's own definition)."""
    lei_csv = tmp_path / "gleif_lei.csv"
    lei_csv.write_text(
        "LEI,Entity.LegalName,Entity.LegalJurisdiction,Entity.HeadquartersAddress.Country,"
        "Entity.EntityStatus,Entity.EntityCategory\n"
        "LEI-SAMEJUR-SUB,Samejur Fixture Subsidiary Co,CN,CN,ACTIVE,GENERAL\n"
        "LEI-SAMEJUR-ULT,Aviation Industry Corporation of China Ltd.,CN,CN,ACTIVE,GENERAL\n",
        encoding="utf-8",
    )
    rr_csv = tmp_path / "gleif_relationships.csv"
    rr_csv.write_text(
        "Relationship.StartNode.NodeID,Relationship.EndNode.NodeID,"
        "Relationship.RelationshipType,Relationship.RelationshipStatus\n"
        "LEI-SAMEJUR-SUB,LEI-SAMEJUR-ULT,IS_DIRECTLY_CONSOLIDATED_BY,ACTIVE\n",
        encoding="utf-8",
    )

    conn = storage.connect(tmp_path / "test.duckdb")
    error_log = IngestionErrorLog(tmp_path / "errors.jsonl")
    load_gleif_level1(conn, lei_csv, datetime.date(2026, 9, 17), error_log)
    load_gleif_level2(conn, rr_csv, datetime.date(2026, 9, 17), error_log)
    dod_list = DoD1260HList(list(DoD1260HIngester(error_log).stream_records()))
    error_log.close()

    declared = [
        DeclaredAffiliation(
            "aff-sub", "cv", "Samejur Fixture Subsidiary Co", "CN", "engineer",
            "2020", "2021", "employment",
        )
    ]
    ties = tie_from_ownership(
        "case-1", "run-1", declared, conn, [dod_list], load_adversary_list()
    )
    conn.close()

    assert len(ties) == 1
    tie = ties[0]
    assert tie.concern_list_evidence  # screened and matched despite same jurisdiction
    assert tie.ownership_evidence == ()  # not foreign control -- same jurisdiction
    assert tie.record_count == 1  # one real link, SUB -> ULT
    assert tie.country == "CN"
    assert tie.country_on_adversary_list is True
    assert tie.hq_country == "CN"
    assert tie.hq_country_on_adversary_list is True


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
    ownership_ties = [t for t in ties if t.tie_kind.value == "declared_employer_ultimate_parent"]
    assert len(nio_findings) == 1
    assert len(own_ties) == 1
    assert own_ties[0].related_finding_id == nio_findings[0].finding_id

    # S5: this is the real, not hypothetical, natural-key collision the
    # deterministic tie_id scheme has to survive -- two ties on the exact
    # same concern_entity_name ("NIO INC."), different tie_kind, in the
    # same run. tie_kind must be part of the id, or these would collide.
    assert own_ties[0].concern_entity_name == ownership_ties[0].concern_entity_name == "NIO INC."
    assert own_ties[0].tie_id != ownership_ties[0].tie_id


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

    # S5: not just the same counts -- the identical finding_id/tie_id set,
    # both times. This is what lets an analyst action survive a re-run.
    assert {f.finding_id for f in first_f} == {f.finding_id for f in second_f}
    assert {t.tie_id for t in first_t} == {t.tie_id for t in second_t}
    conn.close()
