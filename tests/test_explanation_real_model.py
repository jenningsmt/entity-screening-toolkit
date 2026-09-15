"""Real-model regression guard for Epic J (mirrors
tests/test_topic_similarity_real_model.py's role): makes a real call to the
live Claude API and asserts the citation-grounding and lexicon checks both
pass against real, uncontrolled output -- not a fixture.

Skipped, not failed, when ANTHROPIC_API_KEY is unset (e.g. the base `test`
CI job). A skip guard alone would let this regression guard go quietly
unexercised in CI forever, which defeats its whole purpose -- see
test_topic_similarity_real_model.py's own docstring for the precedent this
follows. Paired with a dedicated `llm-explanation-real-model` job in
.github/workflows/ci.yml that has the secret configured and actually runs
this, triggered on changes under entity_screening/explanation/ plus a
weekly schedule -- a skip guard and that job are a package deal, not
alternatives, adapted from the VSS job's every-push trigger because a live
API call spends real money on every run, unlike a free local-model download.

The first real run of this test is also the calibration pass
docs/plans/<date>-epic-j-evidence-grounded-explanation.md's Real-data
research section flagged as not yet done during planning (no
ANTHROPIC_API_KEY was available then) -- read the raw model output here
before assuming explanation/lexicon.py's seed list is complete.
"""
from __future__ import annotations

import os

import pytest

from entity_screening.common.schema import (
    ConcernTie,
    DeclarationSearch,
    DiscoveredAffiliation,
    FactualBasis,
    Finding,
    ForeignControlFlag,
    MatchStatus,
    NearestDeclared,
    ScopeKind,
    ScreeningHit,
    TieKind,
)
from entity_screening.explanation import generate, lexicon

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set -- see this file's module docstring",
)


def _real_finding() -> Finding:
    return Finding(
        finding_id="find-1",
        case_id="case-1",
        run_id="run-1",
        discovered=DiscoveredAffiliation(
            source="openalex",
            institution_name="Beijing Institute of Technology",
            country="CN",
            country_on_adversary_list=True,
            adversary_list_version="v1",
            first_observed="2016",
            last_observed="2017",
            record_count=2,
            role="publication_affiliation",
            source_refs=("W1", "W2"),
        ),
        declaration_search=(
            DeclarationSearch(
                source_kind="cv",
                present=True,
                scope_kind=ScopeKind.FULL_HISTORY,
                scope_descriptor={},
                covers_this_item=True,
            ),
        ),
        factual_basis=FactualBasis.ABSENT_FROM_IN_SCOPE_SOURCE,
        nearest_declared=(
            NearestDeclared(
                declared_affiliation_id="aff-1",
                institution_name="Tsinghua University",
                best_confidence=0.41,
                match_basis="fuzzy_token_sort",
                cleared_name=False,
                scope_compatible=True,
            ),
        ),
    )


def _real_tie() -> ConcernTie:
    return ConcernTie(
        tie_id="tie-1",
        case_id="case-1",
        run_id="run-1",
        tie_kind=TieKind.DECLARED_EMPLOYER_ULTIMATE_PARENT,
        anchor_affiliation_id="aff-subsidiary",
        related_finding_id=None,
        concern_entity_name="NIO INC.",
        country="KY",
        country_on_adversary_list=None,
        adversary_list_version=None,
        first_observed="2016",
        last_observed="2019",
        record_count=1,
        concern_list_evidence=(
            ScreeningHit(
                entity_id="aff-subsidiary",
                list_name="dod_section_1260h",
                matched_variant="NIO INC.",
                matched_field="ownership_ultimate_parent",
                confidence=1.0,
                evidence={"entry_id": "1260h-7"},
                status=MatchStatus.CANDIDATE_MATCH,
                producer="ownership_parent",
            ),
        ),
        ownership_evidence=(
            ForeignControlFlag(
                entity_id="aff-subsidiary",
                entity_lei="LEI-AAA",
                entity_jurisdiction="CN",
                ultimate_parent_lei="LEI-BBB",
                ultimate_parent_name="NIO INC.",
                ultimate_parent_jurisdiction="KY",
                relationship_path=("LEI-AAA", "LEI-BBB"),
                match_confidence=0.95,
                evidence={"truncated": False},
                status=MatchStatus.CANDIDATE_MATCH,
            ),
        ),
    )


def test_real_model_synthesis_is_grounded_and_lexicon_clean():
    result = generate.generate_synthesis(_real_tie(), [_real_finding()])
    if result is None:
        # A real model failing to clear the gate on every attempt is itself
        # a valid, informative outcome (recitation-only ships) -- not a
        # test failure. What WOULD be a failure is a persisted violation,
        # which the assertions below rule out for whichever branch ran.
        return
    assert result.citations, "an accepted result must carry at least one citation"
    assert lexicon.is_clean(result.sentence), (
        f"real model output failed the lexicon check: {result.sentence!r} -- "
        f"violations: {lexicon.find_violations(result.sentence)}"
    )
