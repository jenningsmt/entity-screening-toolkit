"""DuckDB persistence for the case model.

The tables themselves are declared in common/storage.py's SCHEMA_DDL (so
storage.connect() creates them like every other table); this module is only
the row <-> dataclass marshalling, kept out of common/storage.py to stop
that file growing without bound. Nested structures are stored as JSON
columns -- a Declaration's sources/affiliations, a Finding's discovered
fact / declaration-search trail / evidence -- because each is always read
and written as a whole, the same call scored_entities.factors already makes.

Lifecycle per table (docs/plans/2026-09-06-use-case-01-implementation.md
Section 4.3):
- subjects / declarations / cases: current-state, replaced on re-save.
- findings: current-state per case -- replace_findings deletes
  WHERE case_id = ? first, then inserts. Re-running reconciliation (or
  re-opening a case and reconciling again) replaces the current finding
  set. The immutable history lives elsewhere: adjudications (append-only)
  and exported investigative files (one immutable file per export, each
  capturing findings + adjudication as they stood). `run_id` is stored on
  each row for cross-reference to the ReconciliationManifest, not as a
  scoping key.
- worksheet_actions: append-only history; the latest row per finding_id is
  the effective action.
- adjudications: append-only, PRIMARY KEY (case_id, seq); a re-open appends
  seq + 1.
- certifications: append-only.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date

import duckdb

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

# --------------------------------------------------------------------------
# Subjects
# --------------------------------------------------------------------------


def save_subject(conn: duckdb.DuckDBPyConnection, subject: Subject) -> None:
    conn.execute("DELETE FROM subjects WHERE subject_id = ?", [subject.subject_id])
    conn.execute(
        "INSERT INTO subjects VALUES (?, ?, ?, ?, ?)",
        [
            subject.subject_id,
            subject.display_name,
            subject.coverage_basis.value if subject.coverage_basis is not None else None,
            subject.synthetic,
            json.dumps(subject.classified_fields, default=str),
        ],
    )


def load_subject(conn: duckdb.DuckDBPyConnection, subject_id: str) -> Subject | None:
    row = conn.execute(
        "SELECT subject_id, display_name, coverage_basis, synthetic, classified_fields "
        "FROM subjects WHERE subject_id = ?",
        [subject_id],
    ).fetchone()
    if row is None:
        return None
    subject_id, display_name, coverage_basis, synthetic, classified_fields = row
    return Subject(
        subject_id=subject_id,
        display_name=display_name,
        coverage_basis=CoverageBasis(coverage_basis) if coverage_basis is not None else None,
        synthetic=bool(synthetic),
        classified_fields=json.loads(classified_fields),
    )


# --------------------------------------------------------------------------
# Declarations
# --------------------------------------------------------------------------


def _source_to_dict(source: DeclarationSource) -> dict:
    return {
        "source_id": source.source_id,
        "kind": source.kind,
        "present": source.present,
        "scope_kind": source.scope_kind.value,
        "scope_descriptor": source.scope_descriptor,
    }


def _source_from_dict(data: dict) -> DeclarationSource:
    return DeclarationSource(
        source_id=data["source_id"],
        kind=data["kind"],
        present=data["present"],
        scope_kind=ScopeKind(data["scope_kind"]),
        scope_descriptor=data["scope_descriptor"],
    )


def _affiliation_to_dict(affiliation: DeclaredAffiliation) -> dict:
    return {
        "affiliation_id": affiliation.affiliation_id,
        "source_id": affiliation.source_id,
        "institution_name": affiliation.institution_name,
        "country": affiliation.country,
        "role": affiliation.role,
        "start_date": affiliation.start_date,
        "end_date": affiliation.end_date,
        "activity_kind": affiliation.activity_kind,
    }


def _affiliation_from_dict(data: dict) -> DeclaredAffiliation:
    return DeclaredAffiliation(
        affiliation_id=data["affiliation_id"],
        source_id=data["source_id"],
        institution_name=data["institution_name"],
        country=data.get("country"),
        role=data.get("role"),
        start_date=data.get("start_date"),
        end_date=data.get("end_date"),
        activity_kind=data.get("activity_kind"),
    )


def save_declaration(conn: duckdb.DuckDBPyConnection, declaration: Declaration) -> None:
    conn.execute(
        "DELETE FROM declarations WHERE declaration_id = ?", [declaration.declaration_id]
    )
    conn.execute(
        "INSERT INTO declarations VALUES (?, ?, ?, ?, ?)",
        [
            declaration.declaration_id,
            declaration.subject_id,
            declaration.synthetic,
            json.dumps([_source_to_dict(s) for s in declaration.sources]),
            json.dumps([_affiliation_to_dict(a) for a in declaration.affiliations]),
        ],
    )


def _row_to_declaration(row: tuple) -> Declaration:
    declaration_id, subject_id, synthetic, sources, affiliations = row
    return Declaration(
        declaration_id=declaration_id,
        subject_id=subject_id,
        synthetic=bool(synthetic),
        sources=tuple(_source_from_dict(d) for d in json.loads(sources)),
        affiliations=tuple(_affiliation_from_dict(d) for d in json.loads(affiliations)),
    )


def load_declaration(
    conn: duckdb.DuckDBPyConnection, declaration_id: str
) -> Declaration | None:
    row = conn.execute(
        "SELECT declaration_id, subject_id, synthetic, sources, affiliations "
        "FROM declarations WHERE declaration_id = ?",
        [declaration_id],
    ).fetchone()
    return _row_to_declaration(row) if row is not None else None


def load_declaration_for_subject(
    conn: duckdb.DuckDBPyConnection, subject_id: str
) -> Declaration | None:
    row = conn.execute(
        "SELECT declaration_id, subject_id, synthetic, sources, affiliations "
        "FROM declarations WHERE subject_id = ?",
        [subject_id],
    ).fetchone()
    return _row_to_declaration(row) if row is not None else None


# --------------------------------------------------------------------------
# Cases
# --------------------------------------------------------------------------


_CASE_COLUMNS = (
    "case_id, subject_id, declaration_id, trigger, access_scope, coverage_basis, "
    "synthetic, case_kind, state, statutory_deadline, office_id"
)


def save_case(conn: duckdb.DuckDBPyConnection, case: Case) -> None:
    """Columns are named explicitly (not `INSERT INTO cases VALUES (...)`) so
    a DuckDB file created before declaration_id/case_kind existed still
    works: ALTER TABLE ADD COLUMN appends new columns at the end of the
    physical row layout, not wherever this tuple lists them, and a
    positional INSERT would silently misalign every value on such a file
    (the same reason replace_findings/replace_ties name their columns)."""
    conn.execute("DELETE FROM cases WHERE case_id = ?", [case.case_id])
    conn.execute(
        f"INSERT INTO cases ({_CASE_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            case.case_id,
            case.subject_id,
            case.declaration_id,
            case.trigger,
            case.access_scope,
            case.coverage_basis.value if case.coverage_basis is not None else None,
            case.synthetic,
            case.case_kind.value,
            case.state.value,
            case.statutory_deadline,
            case.office_id,
        ],
    )


def load_case(conn: duckdb.DuckDBPyConnection, case_id: str) -> Case | None:
    row = conn.execute(
        f"SELECT {_CASE_COLUMNS} FROM cases WHERE case_id = ?",
        [case_id],
    ).fetchone()
    if row is None:
        return None
    (
        case_id,
        subject_id,
        declaration_id,
        trigger,
        access_scope,
        coverage_basis,
        synthetic,
        case_kind,
        state,
        statutory_deadline,
        office_id,
    ) = row
    return Case(
        case_id=case_id,
        subject_id=subject_id,
        declaration_id=declaration_id,
        trigger=trigger,
        access_scope=access_scope,
        coverage_basis=CoverageBasis(coverage_basis) if coverage_basis is not None else None,
        synthetic=bool(synthetic),
        case_kind=CaseKind(case_kind),
        state=CaseState(state),
        statutory_deadline=(
            statutory_deadline
            if isinstance(statutory_deadline, date) or statutory_deadline is None
            else date.fromisoformat(str(statutory_deadline))
        ),
        office_id=office_id,
    )


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------


def _discovered_to_dict(discovered: DiscoveredAffiliation) -> dict:
    return {
        "source": discovered.source,
        "institution_name": discovered.institution_name,
        "country": discovered.country,
        "country_on_adversary_list": discovered.country_on_adversary_list,
        "adversary_list_version": discovered.adversary_list_version,
        "first_observed": discovered.first_observed,
        "last_observed": discovered.last_observed,
        "record_count": discovered.record_count,
        "role": discovered.role,
        "source_refs": list(discovered.source_refs),
    }


def _discovered_from_dict(data: dict) -> DiscoveredAffiliation:
    return DiscoveredAffiliation(
        source=data["source"],
        institution_name=data["institution_name"],
        country=data.get("country"),
        country_on_adversary_list=data.get("country_on_adversary_list"),
        adversary_list_version=data.get("adversary_list_version"),
        first_observed=data.get("first_observed"),
        last_observed=data.get("last_observed"),
        record_count=data.get("record_count", 0),
        role=data.get("role"),
        source_refs=tuple(data.get("source_refs", [])),
    )


def _search_to_dict(search: DeclarationSearch) -> dict:
    return {
        "source_kind": search.source_kind,
        "present": search.present,
        "scope_kind": search.scope_kind.value,
        "scope_descriptor": search.scope_descriptor,
        "covers_this_item": search.covers_this_item,
    }


def _search_from_dict(data: dict) -> DeclarationSearch:
    return DeclarationSearch(
        source_kind=data["source_kind"],
        present=data["present"],
        scope_kind=ScopeKind(data["scope_kind"]),
        scope_descriptor=data["scope_descriptor"],
        covers_this_item=data["covers_this_item"],
    )


def _nearest_to_dict(nearest: NearestDeclared) -> dict:
    return {
        "declared_affiliation_id": nearest.declared_affiliation_id,
        "institution_name": nearest.institution_name,
        "best_confidence": nearest.best_confidence,
        "match_basis": nearest.match_basis,
        "cleared_name": nearest.cleared_name,
        "scope_compatible": nearest.scope_compatible,
    }


def _nearest_from_dict(data: dict) -> NearestDeclared:
    return NearestDeclared(
        declared_affiliation_id=data["declared_affiliation_id"],
        institution_name=data["institution_name"],
        best_confidence=data["best_confidence"],
        match_basis=data["match_basis"],
        cleared_name=data["cleared_name"],
        scope_compatible=data["scope_compatible"],
    )


def _hit_to_dict(hit: ScreeningHit) -> dict:
    return {
        "entity_id": hit.entity_id,
        "list_name": hit.list_name,
        "matched_variant": hit.matched_variant,
        "matched_field": hit.matched_field,
        "confidence": hit.confidence,
        "evidence": hit.evidence,
        "status": hit.status.value,
        "producer": hit.producer,
    }


def _hit_from_dict(data: dict) -> ScreeningHit:
    return ScreeningHit(
        entity_id=data["entity_id"],
        list_name=data["list_name"],
        matched_variant=data["matched_variant"],
        matched_field=data["matched_field"],
        confidence=data["confidence"],
        evidence=data["evidence"],
        status=MatchStatus(data["status"]),
        producer=data.get("producer", "direct_name"),
    )


def _flag_to_dict(flag: ForeignControlFlag) -> dict:
    return {
        "entity_id": flag.entity_id,
        "entity_lei": flag.entity_lei,
        "entity_jurisdiction": flag.entity_jurisdiction,
        "ultimate_parent_lei": flag.ultimate_parent_lei,
        "ultimate_parent_name": flag.ultimate_parent_name,
        "ultimate_parent_jurisdiction": flag.ultimate_parent_jurisdiction,
        "relationship_path": list(flag.relationship_path),
        "match_confidence": flag.match_confidence,
        "evidence": flag.evidence,
        "status": flag.status.value,
    }


def _flag_from_dict(data: dict) -> ForeignControlFlag:
    return ForeignControlFlag(
        entity_id=data["entity_id"],
        entity_lei=data["entity_lei"],
        entity_jurisdiction=data["entity_jurisdiction"],
        ultimate_parent_lei=data["ultimate_parent_lei"],
        ultimate_parent_name=data["ultimate_parent_name"],
        ultimate_parent_jurisdiction=data["ultimate_parent_jurisdiction"],
        relationship_path=tuple(data.get("relationship_path", [])),
        match_confidence=data["match_confidence"],
        evidence=data["evidence"],
        status=MatchStatus(data["status"]),
    )


_FINDING_COLUMNS = (
    "finding_id, case_id, run_id, discovered, declaration_search, "
    "factual_basis, nearest_declared"
)


def replace_findings(
    conn: duckdb.DuckDBPyConnection,
    case_id: str,
    findings: Iterable[Finding],
) -> None:
    """Current-state per case: deletes this case's findings, then inserts.
    Re-running reconciliation replaces the set. `run_id` on each Finding is
    kept as a column for cross-reference to the ReconciliationManifest, not
    as a scoping key.

    Columns are named explicitly so a DuckDB file created before the
    concern_list_evidence / ownership_evidence columns were dropped still
    works -- those vestigial columns just default to NULL and are never
    read."""
    conn.execute("DELETE FROM findings WHERE case_id = ?", [case_id])
    rows = [
        (
            f.finding_id,
            f.case_id,
            f.run_id,
            json.dumps(_discovered_to_dict(f.discovered), default=str),
            json.dumps([_search_to_dict(s) for s in f.declaration_search], default=str),
            f.factual_basis.value,
            json.dumps([_nearest_to_dict(n) for n in f.nearest_declared], default=str),
        )
        for f in findings
    ]
    if rows:
        conn.executemany(
            f"INSERT INTO findings ({_FINDING_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)", rows
        )


def load_findings(conn: duckdb.DuckDBPyConnection, case_id: str) -> list[Finding]:
    rows = conn.execute(
        f"SELECT {_FINDING_COLUMNS} FROM findings WHERE case_id = ? ORDER BY finding_id",
        [case_id],
    ).fetchall()
    findings = []
    for (
        finding_id,
        case_id,
        run_id,
        discovered,
        declaration_search,
        factual_basis,
        nearest_declared,
    ) in rows:
        findings.append(
            Finding(
                finding_id=finding_id,
                case_id=case_id,
                run_id=run_id,
                discovered=_discovered_from_dict(json.loads(discovered)),
                declaration_search=tuple(
                    _search_from_dict(d) for d in json.loads(declaration_search)
                ),
                factual_basis=FactualBasis(factual_basis),
                nearest_declared=tuple(
                    _nearest_from_dict(d) for d in json.loads(nearest_declared)
                ),
            )
        )
    return findings


# --------------------------------------------------------------------------
# Concern ties (Sec. 51B.151(b))
# --------------------------------------------------------------------------

_TIE_COLUMNS = (
    "tie_id, case_id, run_id, tie_kind, anchor_affiliation_id, related_finding_id, "
    "concern_entity_name, country, country_on_adversary_list, adversary_list_version, "
    "first_observed, last_observed, record_count, concern_list_evidence, ownership_evidence"
)


def replace_ties(
    conn: duckdb.DuckDBPyConnection, case_id: str, ties: Iterable[ConcernTie]
) -> None:
    """Current-state per case, same as replace_findings."""
    conn.execute("DELETE FROM concern_ties WHERE case_id = ?", [case_id])
    rows = [
        (
            t.tie_id,
            t.case_id,
            t.run_id,
            t.tie_kind.value,
            t.anchor_affiliation_id,
            t.related_finding_id,
            t.concern_entity_name,
            t.country,
            t.country_on_adversary_list,
            t.adversary_list_version,
            t.first_observed,
            t.last_observed,
            t.record_count,
            json.dumps([_hit_to_dict(h) for h in t.concern_list_evidence], default=str),
            json.dumps([_flag_to_dict(fl) for fl in t.ownership_evidence], default=str),
        )
        for t in ties
    ]
    if rows:
        conn.executemany(
            f"INSERT INTO concern_ties ({_TIE_COLUMNS}) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )


def load_ties(conn: duckdb.DuckDBPyConnection, case_id: str) -> list[ConcernTie]:
    rows = conn.execute(
        f"SELECT {_TIE_COLUMNS} FROM concern_ties WHERE case_id = ? ORDER BY tie_id",
        [case_id],
    ).fetchall()
    ties = []
    for (
        tie_id,
        case_id,
        run_id,
        tie_kind,
        anchor_affiliation_id,
        related_finding_id,
        concern_entity_name,
        country,
        country_on_adversary_list,
        adversary_list_version,
        first_observed,
        last_observed,
        record_count,
        concern_list_evidence,
        ownership_evidence,
    ) in rows:
        ties.append(
            ConcernTie(
                tie_id=tie_id,
                case_id=case_id,
                run_id=run_id,
                tie_kind=TieKind(tie_kind),
                anchor_affiliation_id=anchor_affiliation_id,
                related_finding_id=related_finding_id,
                concern_entity_name=concern_entity_name,
                country=country,
                country_on_adversary_list=(
                    None if country_on_adversary_list is None else bool(country_on_adversary_list)
                ),
                adversary_list_version=adversary_list_version,
                first_observed=first_observed,
                last_observed=last_observed,
                record_count=int(record_count) if record_count is not None else 0,
                concern_list_evidence=tuple(
                    _hit_from_dict(d) for d in json.loads(concern_list_evidence)
                ),
                ownership_evidence=tuple(
                    _flag_from_dict(d) for d in json.loads(ownership_evidence)
                ),
            )
        )
    return ties


# --------------------------------------------------------------------------
# Worksheet actions
# --------------------------------------------------------------------------


def append_worksheet_action(
    conn: duckdb.DuckDBPyConnection, case_id: str, action: WorksheetAction
) -> None:
    conn.execute(
        "INSERT INTO worksheet_actions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            action.finding_id,
            case_id,
            action.action.value,
            action.reason_code,
            action.reason_note,
            action.actor,
            action.recorded_at,
            action.batch_id,
        ],
    )


def _row_to_action(row: tuple) -> WorksheetAction:
    finding_id, action, reason_code, reason_note, actor, recorded_at, batch_id = row
    return WorksheetAction(
        finding_id=finding_id,
        action=WorksheetActionKind(action),
        reason_code=reason_code,
        reason_note=reason_note,
        actor=actor,
        recorded_at=recorded_at,
        batch_id=batch_id,
    )


def load_worksheet_actions(
    conn: duckdb.DuckDBPyConnection, case_id: str
) -> list[WorksheetAction]:
    rows = conn.execute(
        "SELECT finding_id, action, reason_code, reason_note, actor, recorded_at, batch_id "
        "FROM worksheet_actions WHERE case_id = ? ORDER BY recorded_at",
        [case_id],
    ).fetchall()
    return [_row_to_action(r) for r in rows]


def effective_actions(
    conn: duckdb.DuckDBPyConnection, case_id: str
) -> dict[str, WorksheetAction]:
    """The latest action per finding_id -- the effective disposition."""
    effective: dict[str, WorksheetAction] = {}
    for action in load_worksheet_actions(conn, case_id):
        effective[action.finding_id] = action
    return effective


# --------------------------------------------------------------------------
# Tie actions (mirror of worksheet actions, keyed to tie_id)
# --------------------------------------------------------------------------


def append_tie_action(
    conn: duckdb.DuckDBPyConnection, case_id: str, action: TieAction
) -> None:
    conn.execute(
        "INSERT INTO tie_actions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            action.tie_id,
            case_id,
            action.action.value,
            action.reason_code,
            action.reason_note,
            action.actor,
            action.recorded_at,
            action.batch_id,
        ],
    )


def load_tie_actions(conn: duckdb.DuckDBPyConnection, case_id: str) -> list[TieAction]:
    rows = conn.execute(
        "SELECT tie_id, action, reason_code, reason_note, actor, recorded_at, batch_id "
        "FROM tie_actions WHERE case_id = ? ORDER BY recorded_at",
        [case_id],
    ).fetchall()
    return [
        TieAction(
            tie_id=tie_id,
            action=WorksheetActionKind(action),
            reason_code=reason_code,
            reason_note=reason_note,
            actor=actor,
            recorded_at=recorded_at,
            batch_id=batch_id,
        )
        for tie_id, action, reason_code, reason_note, actor, recorded_at, batch_id in rows
    ]


def effective_tie_actions(
    conn: duckdb.DuckDBPyConnection, case_id: str
) -> dict[str, TieAction]:
    effective: dict[str, TieAction] = {}
    for action in load_tie_actions(conn, case_id):
        effective[action.tie_id] = action
    return effective


# --------------------------------------------------------------------------
# Demo-fixture version marker
# --------------------------------------------------------------------------


def demo_meta_get(conn: duckdb.DuckDBPyConnection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM demo_meta WHERE key = ?", [key]).fetchone()
    return None if row is None else row[0]


def demo_meta_set(conn: duckdb.DuckDBPyConnection, key: str, value: str) -> None:
    conn.execute("DELETE FROM demo_meta WHERE key = ?", [key])
    conn.execute("INSERT INTO demo_meta VALUES (?, ?)", [key, value])


# --------------------------------------------------------------------------
# Adjudications
# --------------------------------------------------------------------------


def next_adjudication_seq(conn: duckdb.DuckDBPyConnection, case_id: str) -> int:
    row = conn.execute(
        "SELECT max(seq) FROM adjudications WHERE case_id = ?", [case_id]
    ).fetchone()
    return 0 if row is None or row[0] is None else int(row[0]) + 1


def append_adjudication(
    conn: duckdb.DuckDBPyConnection, adjudication: Adjudication
) -> None:
    conn.execute(
        "INSERT INTO adjudications VALUES (?, ?, ?, ?, ?, ?)",
        [
            adjudication.case_id,
            adjudication.seq,
            adjudication.assessment,
            adjudication.recommendation,
            adjudication.actor,
            adjudication.recorded_at,
        ],
    )


def load_adjudications(
    conn: duckdb.DuckDBPyConnection, case_id: str
) -> list[Adjudication]:
    rows = conn.execute(
        "SELECT case_id, seq, assessment, recommendation, actor, recorded_at "
        "FROM adjudications WHERE case_id = ? ORDER BY seq",
        [case_id],
    ).fetchall()
    return [
        Adjudication(
            case_id=case_id,
            seq=int(seq),
            assessment=assessment,
            recommendation=recommendation,
            actor=actor,
            recorded_at=recorded_at,
        )
        for case_id, seq, assessment, recommendation, actor, recorded_at in rows
    ]


# --------------------------------------------------------------------------
# Certifications
# --------------------------------------------------------------------------


def append_certification(
    conn: duckdb.DuckDBPyConnection, certification: Certification
) -> None:
    conn.execute(
        "INSERT INTO certifications VALUES (?, ?, ?, ?, ?, ?)",
        [
            certification.case_id,
            certification.finding_id,
            certification.substance_of_failure,
            certification.reasons_for_disregarding,
            certification.department_head,
            certification.recorded_at,
        ],
    )


def load_certifications(
    conn: duckdb.DuckDBPyConnection, case_id: str
) -> list[Certification]:
    rows = conn.execute(
        "SELECT case_id, finding_id, substance_of_failure, reasons_for_disregarding, "
        "department_head, recorded_at FROM certifications WHERE case_id = ? ORDER BY recorded_at",
        [case_id],
    ).fetchall()
    return [
        Certification(
            case_id=case_id,
            finding_id=finding_id,
            substance_of_failure=substance_of_failure,
            reasons_for_disregarding=reasons_for_disregarding,
            department_head=department_head,
            recorded_at=recorded_at,
        )
        for (
            case_id,
            finding_id,
            substance_of_failure,
            reasons_for_disregarding,
            department_head,
            recorded_at,
        ) in rows
    ]
