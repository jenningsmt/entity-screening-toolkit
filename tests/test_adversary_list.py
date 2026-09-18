"""Foreign-adversary-country list: loader, wiring into the three discovery
call sites -- Use Case 01 Section 12 step 4.

Binding real-data verification (docs/plans/2026-09-14-foreign-adversary-list-
ingester.md): the curated snapshot's citations were checked against the
actual DNI Annual Threat Assessment PDFs, not assumed -- these tests cover
the *wiring* (a known adversary vs. a known non-adversary country produces
the right True/False/None, not silently reverting to None), not re-deriving
the list itself.
"""
from __future__ import annotations

import datetime
from pathlib import Path

from entity_screening.common import storage
from entity_screening.common.schema import DeclaredAffiliation
from entity_screening.ingestion.base import IngestionErrorLog
from entity_screening.ingestion.dod_1260h import DoD1260HIngester
from entity_screening.ownership.ingest import load_gleif_level1, load_gleif_level2
from entity_screening.reconciliation.discover import (
    discover_from_publications,
    tie_from_ownership,
)
from entity_screening.screening.adversary_list import load_adversary_list
from entity_screening.screening.lists import DoD1260HList

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_load_adversary_list_loads_the_bundled_four_dni_ata_countries():
    adversary_list = load_adversary_list()
    assert adversary_list.list_version
    assert set(adversary_list.countries) == {"CN", "RU", "IR", "KP"}
    for code in adversary_list.countries:
        assert adversary_list.countries[code]  # every entry cited


def test_contains_true_false_and_none():
    adversary_list = load_adversary_list()
    assert adversary_list.contains("CN") is True
    assert adversary_list.contains("US") is False
    assert adversary_list.contains(None) is None
    assert adversary_list.contains("") is None


def test_contains_normalizes_iso_3166_2_subdivision_codes():
    """GLEIF's legal_jurisdiction is occasionally ISO 3166-2 (e.g. a US
    state), confirmed during the GLEIF verification-gate work -- the country
    prefix must still resolve correctly."""
    adversary_list = load_adversary_list()
    assert adversary_list.contains("US-DE") is False
    assert adversary_list.contains("cn") is True  # case-insensitive too


def test_discover_from_publications_wires_a_real_adversary_country():
    works = {
        "works": [
            {
                "id": "https://openalex.org/W-TEST",
                "publication_date": "2020-01-01",
                "authorships": [
                    {
                        "is_subject": True,
                        "author": {"id": "https://openalex.org/A-TEST", "display_name": "Test Subject"},
                        "institutions": [
                            {"display_name": "A China Institution", "country_code": "CN"},
                            {"display_name": "A US Institution", "country_code": "US"},
                        ],
                    }
                ],
            }
        ]
    }
    adversary_list = load_adversary_list()
    discovered = discover_from_publications(
        "Test Subject", "Some University", adversary_list, works_fixture=works["works"]
    )
    by_name = {d.institution_name: d for d in discovered}
    assert by_name["A China Institution"].country_on_adversary_list is True
    assert by_name["A US Institution"].country_on_adversary_list is False
    for d in discovered:
        assert d.adversary_list_version == adversary_list.list_version


def test_tie_from_ownership_wires_a_real_adversary_country(tmp_path):
    """A synthetic subsidiary whose real ultimate parent's name matches a
    real DoD 1260H entry and whose jurisdiction is a real adversary country
    (CN) -- fabricated LEIs/edges, same convention as
    tests/test_ownership_match.py's fixture rows, not a shipped fixture."""
    lei_csv = tmp_path / "gleif_lei.csv"
    lei_csv.write_text(
        "LEI,Entity.LegalName,Entity.LegalJurisdiction,Entity.HeadquartersAddress.Country,"
        "Entity.EntityStatus,Entity.EntityCategory\n"
        "TESTSUB0000000000001,Test Subsidiary Co Ltd,CN,CN,ACTIVE,GENERAL\n"
        "TESTPARENT000000001,Aviation Industry Corporation of China Ltd.,CN,CN,ACTIVE,GENERAL\n",
        encoding="utf-8",
    )
    rr_csv = tmp_path / "gleif_relationships.csv"
    rr_csv.write_text(
        "Relationship.StartNode.NodeID,Relationship.EndNode.NodeID,"
        "Relationship.RelationshipType,Relationship.RelationshipStatus\n"
        "TESTSUB0000000000001,TESTPARENT000000001,IS_DIRECTLY_CONSOLIDATED_BY,ACTIVE\n"
        "TESTSUB0000000000001,TESTPARENT000000001,IS_ULTIMATELY_CONSOLIDATED_BY,ACTIVE\n",
        encoding="utf-8",
    )

    conn = storage.connect(tmp_path / "test.duckdb")
    error_log = IngestionErrorLog(tmp_path / "errors.jsonl")
    load_gleif_level1(conn, lei_csv, datetime.date(2026, 9, 14), error_log)
    load_gleif_level2(conn, rr_csv, datetime.date(2026, 9, 14), error_log)
    dod_list = DoD1260HList(list(DoD1260HIngester(error_log).stream_records()))
    error_log.close()

    declared = [
        DeclaredAffiliation(
            "aff-1", "cv", "Test Subsidiary Co Ltd", "CN", "engineer",
            "2020", "2021", "employment",
        )
    ]
    adversary_list = load_adversary_list()
    ties = tie_from_ownership(
        "case-1", "run-1", declared, conn, [dod_list], adversary_list
    )
    conn.close()

    assert len(ties) == 1
    assert ties[0].country_on_adversary_list is True
    assert ties[0].adversary_list_version == adversary_list.list_version
