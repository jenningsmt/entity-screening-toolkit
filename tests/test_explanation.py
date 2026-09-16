"""Epic J -- evidence-grounded explanation generation.

No live network call anywhere in this file: explanation/generate.py's `call`
parameter is always a fixture callable here, the same injectable-external-
service pattern this codebase already uses for OpenAlex/GLEIF (`fetch=`,
`works_fixture=`). The real-model regression guard lives in its own file,
tests/test_explanation_real_model.py, skip-guarded on ANTHROPIC_API_KEY.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from entity_screening.common import storage
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
from entity_screening.explanation import generate, lexicon, service, store
from entity_screening.explanation.schema import Citation, MatchExplanation, ObservationKind
from entity_screening.explanation.skeletons import recite

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _finding(basis: FactualBasis = FactualBasis.ABSENT_FROM_IN_SCOPE_SOURCE) -> Finding:
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
        factual_basis=basis,
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


def _tie(kind: TieKind = TieKind.DECLARED_EMPLOYER_ULTIMATE_PARENT) -> ConcernTie:
    return ConcernTie(
        tie_id="tie-1",
        case_id="case-1",
        run_id="run-1",
        tie_kind=kind,
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


def _fake_response(text: str, citations: list[tuple[str, int, int]]) -> SimpleNamespace:
    return SimpleNamespace(
        content=[
            SimpleNamespace(
                type="text",
                text=text,
                citations=[
                    SimpleNamespace(cited_text=c, start_char_index=s, end_char_index=e)
                    for c, s, e in citations
                ],
            )
        ]
    )


def _fake_multi_block_response(
    blocks: list[tuple[str, list[tuple[str, int, int]]]]
) -> SimpleNamespace:
    """Like `_fake_response`, but one caller-specified block per entry --
    B1 needs the per-block cited/uncited distinction a single-block
    response can't represent."""
    return SimpleNamespace(
        content=[
            SimpleNamespace(
                type="text",
                text=text,
                citations=[
                    SimpleNamespace(cited_text=c, start_char_index=s, end_char_index=e)
                    for c, s, e in citations
                ],
            )
            for text, citations in blocks
        ]
    )


def _real_citation(document_text: str, substring: str) -> tuple[str, int, int]:
    """A citation tuple whose offsets are computed from where `substring`
    actually appears in `document_text` -- never hand-typed, so a later
    change to recite()'s templated text can't silently leave a stale
    offset in a fixture."""
    start = document_text.index(substring)
    return substring, start, start + len(substring)


# --------------------------------------------------------------------------
# Lexicon
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "This is a concerning pattern.",
        "The tie is suspicious given the ownership chain.",
        "This clearly indicates undisclosed foreign influence.",
        "The analyst should treat this person with caution.",
        "This finding carries real risk for the institution.",
    ],
)
def test_lexicon_rejects_evaluative_sentences(sentence):
    assert not lexicon.is_clean(sentence)
    assert lexicon.find_violations(sentence)


def test_lexicon_accepts_a_clean_factual_sentence():
    sentence = (
        "This tie to NIO INC. and the undisclosed affiliation with Beijing "
        "Institute of Technology both involve entities located in the same "
        "country recorded in the declaration."
    )
    assert lexicon.is_clean(sentence)
    assert lexicon.find_violations(sentence) == []


@pytest.mark.parametrize(
    "word", ["Frankfurt", "frontier", "underscores", "brisk", "asterisk"]
)
def test_lexicon_does_not_false_positive_on_a_forbidden_token_as_a_substring(word):
    """S14: _FORBIDDEN_OBSERVATION_FIELD_TOKENS ('rank', 'tier', 'score',
    'risk', ...) must match whole words only -- 'rank' is a substring of
    'Frankfurt', 'tier' of 'frontier', 'score' of 'underscores', 'risk' of
    both 'brisk' and 'asterisk'."""
    sentence = f"The subject's institution is located near {word}."
    assert lexicon.is_clean(sentence), lexicon.find_violations(sentence)


@pytest.mark.parametrize("token", ["rank", "tier", "score", "risk"])
def test_lexicon_still_catches_a_forbidden_token_as_its_own_word(token):
    """The whole-word fix must not just silently stop matching altogether."""
    sentence = f"This item carries a {token} for the institution."
    assert not lexicon.is_clean(sentence)
    assert token in lexicon.find_violations(sentence)


def test_lexicon_catches_notably_without_a_trailing_comma():
    sentence = "Notably the two records name the same institution."
    assert not lexicon.is_clean(sentence)
    assert lexicon.find_violations(sentence)


# --------------------------------------------------------------------------
# Skeletons -- fully templated, no LLM
# --------------------------------------------------------------------------


@pytest.mark.parametrize("basis", list(FactualBasis))
def test_finding_recitation_contains_evidence_and_no_forbidden_lexicon(basis):
    f = _finding(basis)
    text = recite(f)
    assert f.discovered.institution_name in text
    assert f.discovered.country in text
    assert lexicon.is_clean(text)


@pytest.mark.parametrize("kind", list(TieKind))
def test_tie_recitation_contains_evidence_and_no_forbidden_lexicon(kind):
    t = _tie(kind)
    text = recite(t)
    assert t.concern_entity_name in text
    assert lexicon.is_clean(text)


def test_recite_rejects_an_unknown_type():
    with pytest.raises(TypeError):
        recite(object())  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# generate_synthesis -- injectable call, no network
# --------------------------------------------------------------------------


def test_generate_synthesis_accepts_a_grounded_clean_sentence():
    calls = []
    document_text = generate._build_document(_tie(), [_finding()])

    def fake_call(request):
        calls.append(request)
        return _fake_response(
            "The tie to NIO INC. and the affiliation with Beijing Institute of "
            "Technology both name entities based in China.",
            [
                _real_citation(document_text, "NIO INC."),
                _real_citation(document_text, "Beijing Institute of Technology"),
            ],
        )

    result = generate.generate_synthesis(_tie(), [_finding()], call=fake_call)
    assert result is not None
    assert result.citations
    assert len(calls) == 1  # accepted on the first attempt, no retry needed


def test_generate_synthesis_rejects_an_uncited_claim_and_falls_back_to_none():
    def fake_call(request):
        return _fake_response("This connects to a broader pattern.", [])

    result = generate.generate_synthesis(_tie(), [_finding()], call=fake_call)
    assert result is None


def test_generate_synthesis_rejects_a_lexicon_violation_and_falls_back_to_none():
    document_text = generate._build_document(_tie(), [_finding()])

    def fake_call(request):
        return _fake_response(
            "This tie is concerning given the ownership chain.",
            [_real_citation(document_text, "ownership chain")],
        )

    result = generate.generate_synthesis(_tie(), [_finding()], call=fake_call)
    assert result is None


def test_generate_synthesis_retries_within_the_bound_then_gives_up():
    calls = []
    document_text = generate._build_document(_tie(), [_finding()])

    def always_bad_call(request):
        calls.append(request)
        return _fake_response("concerning", [_real_citation(document_text, "NIO INC.")])

    result = generate.generate_synthesis(_tie(), [_finding()], call=always_bad_call)
    assert result is None
    assert len(calls) == generate.MAX_RETRIES + 1


def test_generate_synthesis_rejects_mixed_cited_and_uncited_blocks():
    """B1: a response with an interleaved cited and uncited text block is
    the expected real-Citations-API shape, not an edge case -- both blocks
    must be grounded, not just 'at least one citation exists anywhere'."""
    document_text = generate._build_document(_tie(), [_finding()])

    def fake_call(request):
        return _fake_multi_block_response(
            [
                ("NIO INC. is the ultimate parent.", [_real_citation(document_text, "NIO INC.")]),
                ("It also has extensive undisclosed ties elsewhere.", []),
            ]
        )

    result = generate.generate_synthesis(_tie(), [_finding()], call=fake_call)
    assert result is None


def test_generate_synthesis_rejects_a_citation_whose_offsets_dont_match_the_text():
    document_text = generate._build_document(_tie(), [_finding()])

    def fake_call(request):
        # A citation claiming to be "NIO INC." but pointing at the wrong
        # slice of document_text (and/or past its end) -- the SDK's own
        # citation object is not to be trusted verbatim.
        bad_start = len(document_text) - 2
        bad_end = bad_start + len("NIO INC.")
        return _fake_response(
            "NIO INC. is the ultimate parent.",
            [("NIO INC.", bad_start, bad_end)],
        )

    result = generate.generate_synthesis(_tie(), [_finding()], call=fake_call)
    assert result is None


def test_generate_synthesis_rejects_an_all_empty_response():
    """The 'no content at all' case today's `if not sentence or not
    citations` guard also covers -- must stay covered by the per-block
    rewrite, not fall through as an accepted empty SynthesisResult."""

    def empty_call(request):
        return _fake_response("", [])

    def whitespace_only_call(request):
        return _fake_response("   ", [])

    assert generate.generate_synthesis(_tie(), [_finding()], call=empty_call) is None
    assert generate.generate_synthesis(_tie(), [_finding()], call=whitespace_only_call) is None


# --------------------------------------------------------------------------
# MatchExplanation construction guard
# --------------------------------------------------------------------------


def test_match_explanation_rejects_a_dirty_synthesis_sentence():
    with pytest.raises(ValueError):
        MatchExplanation(
            explanation_id="x",
            observation_kind=ObservationKind.CONCERN_TIE,
            observation_id="tie-1",
            case_id="case-1",
            recitation="x",
            synthesis_sentence="this is concerning",
            citations=(Citation("x", 0, 1),),
            evidence_hash="x",
            model="x",
            prompt_version="x",
            generated_at="x",
            synthetic=True,
        )


def test_match_explanation_rejects_a_sentence_with_no_citations():
    with pytest.raises(ValueError):
        MatchExplanation(
            explanation_id="x",
            observation_kind=ObservationKind.CONCERN_TIE,
            observation_id="tie-1",
            case_id="case-1",
            recitation="x",
            synthesis_sentence="A clean grounded sentence.",
            citations=(),
            evidence_hash="x",
            model="x",
            prompt_version="x",
            generated_at="x",
            synthetic=True,
        )


def test_match_explanation_recitation_only_is_valid():
    m = MatchExplanation(
        explanation_id="x",
        observation_kind=ObservationKind.FINDING,
        observation_id="find-1",
        case_id="case-1",
        recitation="x",
        synthesis_sentence=None,
        citations=(),
        evidence_hash="x",
        model="x",
        prompt_version="x",
        generated_at="x",
        synthetic=True,
    )
    assert m.synthesis_sentence is None


# --------------------------------------------------------------------------
# evidence_hash_for -- M17: case_context must be part of the cache key
# --------------------------------------------------------------------------


def test_evidence_hash_for_differs_when_case_context_differs():
    """Two cases sharing an identical finding must not share a cached
    sentence if their surrounding ties differ -- the synthesis sentence is
    explicitly allowed to connect the primary to other observations in the
    same case, so the cache key has to be able to tell those two
    situations apart."""
    finding = _finding()
    context_a = [_tie(TieKind.DECLARED_EMPLOYER_ULTIMATE_PARENT)]
    context_b = [_tie(TieKind.OWN_AFFILIATION_HISTORY)]

    hash_a = service.evidence_hash_for(finding, context_a)
    hash_b = service.evidence_hash_for(finding, context_b)

    assert hash_a != hash_b


def test_evidence_hash_for_is_stable_under_case_context_reordering():
    """case_context comes from store.load_findings/load_ties, whose row
    order isn't guaranteed stable across calls (M10) -- the same logical
    context must hash the same regardless of the order its observations
    arrive in, or a GET immediately after the POST that cached it could
    already disagree."""
    finding = _finding()
    tie_a = _tie(TieKind.DECLARED_EMPLOYER_ULTIMATE_PARENT)
    tie_b = _tie(TieKind.OWN_AFFILIATION_HISTORY)

    hash_forward = service.evidence_hash_for(finding, [tie_a, tie_b])
    hash_reversed = service.evidence_hash_for(finding, [tie_b, tie_a])

    assert hash_forward == hash_reversed


def test_evidence_hash_for_with_no_context_matches_the_default():
    """Backward-compatible default: a call with no case_context argument
    (existing callers that haven't been updated) must not silently produce
    a different hash than one that explicitly passes an empty list."""
    finding = _finding()
    assert service.evidence_hash_for(finding) == service.evidence_hash_for(finding, [])


# --------------------------------------------------------------------------
# service.explain -- persistence + idempotency
# --------------------------------------------------------------------------


def test_explain_is_idempotent_for_the_same_observation_and_evidence(tmp_path):
    conn = storage.connect(tmp_path / "test.duckdb")
    calls = []
    document_text = generate._build_document(_tie(), [_finding()])

    def fake_call(request):
        calls.append(request)
        return _fake_response(
            "The tie to NIO INC. involves a Cayman Islands ultimate parent.",
            [_real_citation(document_text, "NIO INC.")],
        )

    tie = _tie()
    e1 = service.explain(
        conn, ObservationKind.CONCERN_TIE, tie, "case-1", [_finding()],
        synthetic=True, call=fake_call,
    )
    e2 = service.explain(
        conn, ObservationKind.CONCERN_TIE, tie, "case-1", [_finding()],
        synthetic=True, call=fake_call,
    )

    assert e1.explanation_id == e2.explanation_id
    assert len(calls) == 1  # second explain() call hit the cache, not the model
    conn.close()


def test_explain_persists_and_round_trips_via_store(tmp_path):
    conn = storage.connect(tmp_path / "test.duckdb")
    document_text = generate._build_document(_tie(), [_finding()])

    def fake_call(request):
        return _fake_response(
            "The tie to NIO INC. involves a Cayman Islands ultimate parent.",
            [_real_citation(document_text, "NIO INC.")],
        )

    explanation = service.explain(
        conn,
        ObservationKind.CONCERN_TIE,
        _tie(),
        "case-1",
        [_finding()],
        synthetic=True,
        call=fake_call,
    )

    loaded = store.load_explanation(conn, "tie-1", explanation.evidence_hash)
    assert loaded == explanation
    conn.close()


def test_explain_recitation_only_when_no_synthesis_clears_verification(tmp_path):
    conn = storage.connect(tmp_path / "test.duckdb")

    def always_ungrounded_call(request):
        return _fake_response("An unsupported connection.", [])

    explanation = service.explain(
        conn,
        ObservationKind.FINDING,
        _finding(),
        "case-1",
        [_tie()],
        synthetic=True,
        call=always_ungrounded_call,
    )

    assert explanation.synthesis_sentence is None
    assert explanation.citations == ()
    assert explanation.recitation  # the explanation still ships, recitation-only
    conn.close()
