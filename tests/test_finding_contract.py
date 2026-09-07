"""The fact/judgment boundary, checked directly (use-case-01 Section 4).

The observation types -- Finding (the Sec. 51B.153 omission test) and
ConcernTie (the Sec. 51B.151(b) tie test) -- and every type in their graphs
state observable facts and never evaluate them. This is the same class of
guarantee as MatchStatus's single member, and it is enforced the same way:
structurally, with a CI check, not by documentation. These tests fail if a
future change adds an evaluative field anywhere in a graph, or weakens the
synthetic-only guard on the PII-bearing types.
"""
from __future__ import annotations

from dataclasses import fields

import pytest

from entity_screening.common.schema import (
    _FORBIDDEN_OBSERVATION_FIELD_TOKENS,
    _OBSERVATION_GRAPH_ALLOWED_FIELDS,
    ConcernTie,
    CoverageBasis,
    Declaration,
    DeclarationSearch,
    DiscoveredAffiliation,
    Finding,
    NearestDeclared,
    Subject,
)

OBSERVATION_GRAPH = {
    "Finding": Finding,
    "ConcernTie": ConcernTie,
    "DiscoveredAffiliation": DiscoveredAffiliation,
    "DeclarationSearch": DeclarationSearch,
    "NearestDeclared": NearestDeclared,
}


@pytest.mark.parametrize("type_name,dc", list(OBSERVATION_GRAPH.items()))
def test_observation_type_matches_its_frozen_allowlist(type_name, dc):
    actual = {f.name for f in fields(dc)}
    assert actual == _OBSERVATION_GRAPH_ALLOWED_FIELDS[type_name], (
        f"{type_name}'s fields changed without a deliberate edit to "
        "_OBSERVATION_GRAPH_ALLOWED_FIELDS"
    )


@pytest.mark.parametrize("type_name,dc", list(OBSERVATION_GRAPH.items()))
def test_no_observation_type_carries_an_evaluative_field(type_name, dc):
    for f in fields(dc):
        for token in _FORBIDDEN_OBSERVATION_FIELD_TOKENS:
            assert token not in f.name.lower(), (
                f"{type_name}.{f.name} reads as an evaluative claim about a person"
            )


def test_the_51b151b_conclusion_words_are_forbidden_field_tokens():
    # "would prevent ... security or integrity" is the analyst's judgment,
    # recorded on a TieAction -- never a field ConcernTie can hold.
    for token in ("prevent", "impair", "disqualif", "risk"):
        assert token in _FORBIDDEN_OBSERVATION_FIELD_TOKENS


def test_a_would_prevent_style_field_on_concern_tie_would_fail_the_guard():
    hypothetical = {f.name for f in fields(ConcernTie)} | {"would_prevent_security"}
    forbidden = {
        n for n in hypothetical for t in _FORBIDDEN_OBSERVATION_FIELD_TOKENS if t in n.lower()
    }
    assert "would_prevent_security" in forbidden


def test_finding_has_no_disposition_or_evidence_field():
    # The human's decision is a separate WorksheetAction; concern-list /
    # ownership evidence moved to ConcernTie.
    allowed = _OBSERVATION_GRAPH_ALLOWED_FIELDS["Finding"]
    assert "disposition" not in allowed
    assert "concern_list_evidence" not in allowed
    assert "ownership_evidence" not in allowed


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
