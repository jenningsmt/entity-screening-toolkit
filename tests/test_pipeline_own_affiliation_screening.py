"""B4: concern-list screening of the subject's own discovered affiliations
(`ties_from_own_affiliations`) has no GLEIF dependency and must run for
every case, not just the two demo cases that happen to supply GLEIF files.
Before this fix, `pipeline.reconcile_case` only called it inside the
`if gleif_lei_file and gleif_relationships_file:` block -- so any case
created via `POST /cases` (which never receives GLEIF files) got no
concern-list screening at all.
"""
from __future__ import annotations

from entity_screening.case import store as case_store
from entity_screening.common import storage
from entity_screening.common.schema import (
    Case,
    CaseKind,
    CaseState,
    CoverageBasis,
    DeclaredAffiliation,
    Declaration,
    DeclarationSource,
    DiscoveredAffiliation,
    ScopeKind,
    Subject,
    TieKind,
)
from entity_screening.ingestion.base import IngestionErrorLog
from entity_screening.ingestion.dod_1260h import DEFAULT_DATA_FILE as DEFAULT_DOD_1260H_FILE
from entity_screening.pipeline import _case_concern_lists, reconcile_case
from entity_screening.reconciliation.discover import ties_from_own_affiliations

NIO_NAME = "NIO, Inc."  # entity_screening/screening/data/dod_1260h.json:1640


def _real_dod_1260h_concern_lists(tmp_path):
    error_log = IngestionErrorLog(tmp_path / "ingestion_errors.jsonl")
    lists = _case_concern_lists(error_log, DEFAULT_DOD_1260H_FILE, None)
    error_log.close()
    return lists


def test_ties_from_own_affiliations_matches_a_real_1260h_entry_with_no_gleif(tmp_path):
    concern_lists = _real_dod_1260h_concern_lists(tmp_path)
    discovered = [
        DiscoveredAffiliation(
            source="openalex",
            institution_name=NIO_NAME,
            country="cn",
            country_on_adversary_list=None,
            adversary_list_version=None,
            first_observed="2021-01-01",
            last_observed="2022-01-01",
            record_count=3,
            role="researcher",
            source_refs=("W123",),
        )
    ]

    ties = ties_from_own_affiliations("case-1", "run-1", discovered, concern_lists)

    assert len(ties) == 1
    assert ties[0].tie_kind == TieKind.OWN_AFFILIATION_HISTORY
    assert ties[0].concern_entity_name == NIO_NAME


def _non_demo_case_with_discovered_affiliation(tmp_path, works_fixture):
    """Mirrors api/case_routes.py's create_case (DECLARATION_ASSEMBLY start
    state), but calls pipeline.reconcile_case directly with a works_fixture
    -- the route can't inject one for a non-demo case
    (works_fixture=demo.load_demo_works_fixture() if is_demo else None), so
    the end-to-end proof for this fix has to sit at this layer, the one the
    fix actually changes."""
    db_path = tmp_path / "case.duckdb"
    conn = storage.connect(db_path)
    subject = Subject(
        subject_id="s1",
        display_name="Test Subject",
        synthetic=True,
        coverage_basis=CoverageBasis.FOREIGN_NATIONAL_NO_PR,
        classified_fields={},
    )
    declaration = Declaration(
        declaration_id="case-1-declaration",
        subject_id="s1",
        synthetic=True,
        sources=(
            DeclarationSource(
                source_id="ds160",
                kind="ds160",
                present=True,
                scope_kind=ScopeKind.TEMPORAL_WINDOW,
                scope_descriptor={"window_years": 5, "anchor": "2026-01-15"},
            ),
        ),
        affiliations=(
            DeclaredAffiliation(
                affiliation_id="aff-1",
                source_id="ds160",
                institution_name="Ordinary University",
                country="us",
                role="researcher",
                start_date="2018-01-01",
                end_date=None,
                activity_kind="employment",
            ),
        ),
    )
    case = Case(
        case_id="case-1",
        subject_id="s1",
        declaration_id="case-1-declaration",
        trigger="hb127",
        access_scope="data",
        coverage_basis=CoverageBasis.FOREIGN_NATIONAL_NO_PR,
        synthetic=True,
        case_kind=CaseKind.HB127_RESEARCHER_SCREENING,
        state=CaseState.DECLARATION_ASSEMBLY,
        statutory_deadline=None,
        office_id=None,
    )
    case_store.save_subject(conn, subject)
    case_store.save_declaration(conn, declaration)
    case_store.save_case(conn, case)
    conn.close()

    return reconcile_case(
        "case-1",
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        works_fixture=works_fixture,
        gleif_lei_file=None,
        gleif_relationships_file=None,
    )


def test_non_demo_case_with_no_gleif_still_screens_a_discovered_affiliation(tmp_path):
    works_fixture = [
        {
            "id": "https://openalex.org/W999",
            "publication_date": "2022-06-01",
            "authorships": [
                {
                    "author_position": "middle",
                    "author": {"id": "https://openalex.org/A1", "display_name": "Test Subject"},
                    "institutions": [{"display_name": NIO_NAME, "country_code": "CN"}],
                }
            ],
        }
    ]

    manifest, findings, ties = _non_demo_case_with_discovered_affiliation(tmp_path, works_fixture)

    own_affiliation_ties = [t for t in ties if t.tie_kind == TieKind.OWN_AFFILIATION_HISTORY]
    assert own_affiliation_ties, "expected an own-affiliation-history tie with no GLEIF supplied"
    assert own_affiliation_ties[0].concern_entity_name == NIO_NAME
    assert "dod_section_1260h" in manifest.discovery_sources
    assert "gleif_ownership" not in manifest.discovery_sources
