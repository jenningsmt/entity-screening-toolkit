"""The self-healing demo case (Use Case 01).

Mirrors api/main.py:_ensure_demo_run_exists -- a fixed, well-known id so the
public demo's landing view finds the same case after a restart, built lazily
from bundled fixtures on first access, with zero live network calls (the
subject is synthetic and its 'publication record' is a clearly-labelled
fixture, per use-case-01 Section 10).

Fixtures live under tests/fixtures/demo_case/ -- the same place
_ensure_demo_run_exists reads its NSF/OpenSanctions demo files.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb

from entity_screening.case import store
from entity_screening.common.schema import (
    Case,
    CaseState,
    CoverageBasis,
    DeclaredAffiliation,
    Declaration,
    DeclarationSource,
    ScopeKind,
    Subject,
)

DEMO_CASE_ID = "demo"

_FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "demo_case"

# Fabricated three-node ownership chain -- see tests/fixtures/demo_case/gleif.NOTICE.md.
# The ultimate parent's name is that of a real DoD Section 1260H entity, so
# the concern-list match is against real reference data; only the GLEIF graph
# is synthetic.
DEMO_GLEIF_LEI_FILE = _FIXTURES_DIR / "gleif_lei.csv"
DEMO_GLEIF_RELATIONSHIPS_FILE = _FIXTURES_DIR / "gleif_relationships.csv"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES_DIR / name).read_text(encoding="utf-8"))


def load_demo_works_fixture() -> list[dict]:
    return _load("works_fixture.json")["works"]


def _subject_from_fixture(data: dict) -> Subject:
    return Subject(
        subject_id=data["subject_id"],
        display_name=data["display_name"],
        coverage_basis=CoverageBasis(data["coverage_basis"]),
        synthetic=data["synthetic"],
        classified_fields=data["classified_fields"],
    )


def _declaration_from_fixture(data: dict) -> Declaration:
    return Declaration(
        declaration_id=data["declaration_id"],
        subject_id=data["subject_id"],
        synthetic=data["synthetic"],
        sources=tuple(
            DeclarationSource(
                source_id=s["source_id"],
                kind=s["kind"],
                present=s["present"],
                scope_kind=ScopeKind(s["scope_kind"]),
                scope_descriptor=s["scope_descriptor"],
            )
            for s in data["sources"]
        ),
        affiliations=tuple(
            DeclaredAffiliation(
                affiliation_id=a["affiliation_id"],
                source_id=a["source_id"],
                institution_name=a["institution_name"],
                country=a.get("country"),
                role=a.get("role"),
                start_date=a.get("start_date"),
                end_date=a.get("end_date"),
                activity_kind=a.get("activity_kind"),
            )
            for a in data["affiliations"]
        ),
    )


def demo_case_exists(conn: duckdb.DuckDBPyConnection) -> bool:
    return store.load_case(conn, DEMO_CASE_ID) is not None


def build_demo_case(conn: duckdb.DuckDBPyConnection) -> Case:
    """Idempotent: safe to call whenever the demo case might be missing (a
    fresh deployment, a wiped data volume). Records the subject, declaration
    and case in Intake state; the caller runs reconciliation separately, the
    same as a real intake."""
    subject = _subject_from_fixture(_load("subject.json"))
    declaration = _declaration_from_fixture(_load("declaration.json"))
    case = Case(
        case_id=DEMO_CASE_ID,
        subject_id=subject.subject_id,
        trigger="Visiting scholar appointment, Division of Research review (Form 5VS + HB 127)",
        access_scope="Research data and lab information systems",
        coverage_basis=subject.coverage_basis,
        synthetic=True,
        state=CaseState.INTAKE,
        statutory_deadline=date(2026, 10, 1),
    )
    store.save_subject(conn, subject)
    store.save_declaration(conn, declaration)
    store.save_case(conn, case)
    return case
