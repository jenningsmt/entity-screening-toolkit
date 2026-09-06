"""The fact/judgment boundary, checked directly (use-case-01 Section 4).

The Finding graph -- Finding and every type it contains -- states observable
facts and never evaluates them. This is the same class of guarantee as
MatchStatus's single member, and it is enforced the same way: structurally,
with a CI check, not by documentation. These tests fail if a future change
adds an evaluative field anywhere in the graph, or weakens the
synthetic-only guard on the PII-bearing types.
"""
from __future__ import annotations

from dataclasses import fields

import pytest

from entity_screening.common.schema import (
    _FINDING_GRAPH_ALLOWED_FIELDS,
    _FORBIDDEN_FINDING_FIELD_TOKENS,
    CoverageBasis,
    Declaration,
    DeclarationSearch,
    DiscoveredAffiliation,
    Finding,
    NearestDeclared,
    Subject,
)

FINDING_GRAPH = {
    "Finding": Finding,
    "DiscoveredAffiliation": DiscoveredAffiliation,
    "DeclarationSearch": DeclarationSearch,
    "NearestDeclared": NearestDeclared,
}


@pytest.mark.parametrize("type_name,dc", list(FINDING_GRAPH.items()))
def test_finding_graph_type_matches_its_frozen_allowlist(type_name, dc):
    actual = {f.name for f in fields(dc)}
    assert actual == _FINDING_GRAPH_ALLOWED_FIELDS[type_name], (
        f"{type_name}'s fields changed without a deliberate edit to "
        "_FINDING_GRAPH_ALLOWED_FIELDS"
    )


@pytest.mark.parametrize("type_name,dc", list(FINDING_GRAPH.items()))
def test_no_finding_graph_type_carries_an_evaluative_field(type_name, dc):
    for f in fields(dc):
        for token in _FORBIDDEN_FINDING_FIELD_TOKENS:
            assert token not in f.name.lower(), (
                f"{type_name}.{f.name} reads as an evaluative claim about a person"
            )


def test_finding_has_no_disposition_field():
    # The human's decision is a separate WorksheetAction record; a Finding is
    # a pure observation.
    assert "disposition" not in _FINDING_GRAPH_ALLOWED_FIELDS["Finding"]


def test_subject_rejects_non_synthetic():
    with pytest.raises(ValueError):
        Subject(
            subject_id="s1",
            display_name="Real Person",
            coverage_basis=CoverageBasis.FOREIGN_NATIONAL_NO_PR,
            synthetic=False,
            classified_fields={},
        )


def test_declaration_rejects_non_synthetic():
    with pytest.raises(ValueError):
        Declaration(
            declaration_id="d1",
            subject_id="s1",
            synthetic=False,
            sources=(),
            affiliations=(),
        )
