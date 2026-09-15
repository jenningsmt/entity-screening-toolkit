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
    CaseKind,
    CaseState,
    CoverageBasis,
    DeclaredAffiliation,
    Declaration,
    DeclarationSource,
    ScopeKind,
    Subject,
)

DEMO_CASE_ID = "demo"

# Step 6: a second, annual COI/Outside-Interest disclosure cycle for the SAME
# synthetic subject as DEMO_CASE_ID -- the end-to-end proof that
# Case.declaration_id disambiguates two declarations for one subject rather
# than the two colliding (docs/plans/2026-09-15-step-6-coi-annual-disclosure-
# reuse.md).
DEMO_COI_CASE_ID = "demo-coi"

# Bumped whenever the demo fixtures OR the shape of what reconciliation
# produces changes, so a persistent data volume rebuilds the demo case
# instead of serving stale rows.
# v2: concern ties split out of Finding
# (docs/plans/2026-09-06-concern-ties-as-a-distinct-observation.md).
# v3: GLEIF fixture's ultimate parent replaced with a real, GLEIF-verified
# record on the real DoD 1260H list (docs/plans/2026-09-14-close-gleif-
# verification-gate.md); the declared subsidiary/employer stays fabricated.
# v4: Case.declaration_id/case_kind added, coverage_basis made optional, and
# the demo-coi second disclosure cycle added (step 6).
# v5: every finding/tie now gets a pre-generated, cached MatchExplanation
# (Epic J) as part of the demo build, so a visitor's first "Explain this
# match" click never triggers a live Claude API call.
DEMO_FIXTURE_VERSION = 5

_FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "demo_case"

# Hybrid two-node ownership chain -- see tests/fixtures/demo_case/gleif.NOTICE.md.
# The fabricated subsidiary/employer row and its edge are invented; the
# ultimate parent row is a real, GLEIF-verified LEI record whose legal name is
# a genuine match against a real DoD Section 1260H entity.
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


def demo_coi_case_exists(conn: duckdb.DuckDBPyConnection) -> bool:
    return store.load_case(conn, DEMO_COI_CASE_ID) is not None


_DEMO_CASE_TABLES = (
    "findings",
    "concern_ties",
    "worksheet_actions",
    "tie_actions",
    "adjudications",
    "certifications",
    "case_outcomes",
)


def build_demo_case(conn: duckdb.DuckDBPyConnection) -> Case:
    """Idempotent: safe to call whenever the demo case might be missing (a
    fresh deployment, a wiped data volume) or stale (a DEMO_FIXTURE_VERSION
    bump). Wipes any prior demo-case rows across every case table, then
    records the subject, declaration and case in Intake state; the caller
    runs reconciliation separately, the same as a real intake."""
    for table in _DEMO_CASE_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE case_id = ?", [DEMO_CASE_ID])
    subject = _subject_from_fixture(_load("subject.json"))
    declaration = _declaration_from_fixture(_load("declaration.json"))
    case = Case(
        case_id=DEMO_CASE_ID,
        subject_id=subject.subject_id,
        declaration_id=declaration.declaration_id,
        trigger="Visiting scholar appointment, Division of Research review (Form 5VS + HB 127)",
        access_scope="Research data and lab information systems",
        coverage_basis=subject.coverage_basis,
        synthetic=True,
        case_kind=CaseKind.HB127_RESEARCHER_SCREENING,
        state=CaseState.INTAKE,
        statutory_deadline=date(2026, 10, 1),
    )
    store.save_subject(conn, subject)
    store.save_declaration(conn, declaration)
    store.save_case(conn, case)
    return case


def build_demo_coi_case(conn: duckdb.DuckDBPyConnection) -> Case:
    """Step 6's demo: a second, annual COI/Outside-Interest disclosure cycle
    for the SAME synthetic subject as DEMO_CASE_ID, with its own Declaration
    (`coi_declaration.json`) whose TYPE_ENUMERATION scope (outside
    employment/board/consulting/foreign-government-affiliation) doesn't
    admit a bare publication-affiliation role at all -- so every
    OpenAlex-discovered institution not independently cleared by name
    (Nanjing University included, deliberately not declared here) surfaces
    as a genuine, scope-bounded discrepancy, a larger and independently
    derived set from DEMO_CASE_ID's own two. Idempotent, same pattern as
    build_demo_case."""
    for table in _DEMO_CASE_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE case_id = ?", [DEMO_COI_CASE_ID])
    subject = _subject_from_fixture(_load("subject.json"))
    declaration = _declaration_from_fixture(_load("coi_declaration.json"))
    case = Case(
        case_id=DEMO_COI_CASE_ID,
        subject_id=subject.subject_id,
        declaration_id=declaration.declaration_id,
        trigger=(
            "Annual Outside-Interest disclosure, TAMU System Regulation 15.01.03 "
            "(Financial Conflicts of Interest in Sponsored Research), FY2027"
        ),
        access_scope="N/A -- annual compliance certification, not an access-granting decision",
        coverage_basis=None,
        synthetic=True,
        case_kind=CaseKind.COI_ANNUAL_DISCLOSURE,
        state=CaseState.INTAKE,
        statutory_deadline=date(2027, 1, 31),
    )
    store.save_subject(conn, subject)
    store.save_declaration(conn, declaration)
    store.save_case(conn, case)
    return case
