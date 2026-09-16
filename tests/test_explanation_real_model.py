"""Real-model regression guard for Epic J (mirrors
tests/test_topic_similarity_real_model.py's role): makes a real call to the
live Claude API, against the real bundled demo case's real findings/ties,
and asserts the citation-grounding and lexicon checks both against the
raw, uncontrolled output -- not a fixture.

Skipped, not failed, when ANTHROPIC_API_KEY is unset (e.g. the base `test`
CI job). A skip guard alone would let this regression guard go quietly
unexercised in CI forever, which defeats its whole purpose -- see
test_topic_similarity_real_model.py's own docstring for the precedent this
follows. Paired with a dedicated `llm-explanation-real-model` job in
.github/workflows/llm-explanation-real-model.yml (a separate workflow file,
not a job inside ci.yml, because GitHub's path filters are workflow-scoped)
that has the secret configured and actually runs this, triggered on changes
under entity_screening/explanation/ plus a weekly schedule -- a skip guard
and that job are a package deal, not alternatives, adapted from the VSS
job's every-push trigger because a live API call spends real money on
every run, unlike a free local-model download.

The first real run of this test is also the calibration pass
docs/plans/<date>-epic-j-evidence-grounded-explanation.md's Real-data
research section flagged as not yet done during planning (no
ANTHROPIC_API_KEY was available then) -- read the raw model output here
before assuming explanation/lexicon.py's seed list is complete.
"""
from __future__ import annotations

import os

import pytest

from entity_screening.case import demo, store as case_store
from entity_screening.common import storage
from entity_screening.common.schema import TieKind
from entity_screening.explanation import generate, lexicon
from entity_screening.pipeline import reconcile_case

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set -- see this file's module docstring",
)


def _real_demo_observations(tmp_path):
    db_path = tmp_path / "case.duckdb"
    conn = storage.connect(db_path)
    demo.build_demo_case(conn)
    conn.close()
    reconcile_case(
        demo.DEMO_CASE_ID,
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        works_fixture=demo.load_demo_works_fixture(),
        gleif_lei_file=demo.DEMO_GLEIF_LEI_FILE,
        gleif_relationships_file=demo.DEMO_GLEIF_RELATIONSHIPS_FILE,
    )
    conn = storage.connect(db_path)
    findings = case_store.load_findings(conn, demo.DEMO_CASE_ID)
    ties = case_store.load_ties(conn, demo.DEMO_CASE_ID)
    conn.close()
    return findings, ties


def test_real_model_synthesis_against_the_real_demo_case_is_grounded(tmp_path):
    findings, ties = _real_demo_observations(tmp_path)
    # Selected by a stable attribute, not list position -- row order from
    # load_findings/load_ties isn't guaranteed stable (M10). This is the
    # demo's one ownership tie, its headline case.
    primary = next(t for t in ties if t.tie_kind == TieKind.DECLARED_EMPLOYER_ULTIMATE_PARENT)
    context = list(findings) + [t for t in ties if t is not primary]

    document_text = generate._build_document(primary, context)
    raw_response = generate._default_anthropic_call(generate._build_request(document_text))
    blocks = generate._extract(raw_response)

    total = sum(1 for text, _ in blocks if text.strip())
    uncited = sum(1 for text, cites in blocks if text.strip() and not cites)
    sentence = " ".join(text.strip() for text, _ in blocks if text.strip())

    print(f"\n[Epic J calibration] document_text: {document_text!r}")
    print(f"[Epic J calibration] sentence: {sentence!r}")
    print(f"[Epic J calibration] blocks={total} uncited={uncited}")
    for text, cites in blocks:
        for c in cites:
            matched = document_text[c.start_char : c.end_char] == c.cited_text
            print(
                f"[Epic J calibration] citation {c.cited_text!r} "
                f"offset={c.start_char}:{c.end_char} matches={matched}"
            )

    # Independent assertions -- computed from the raw response here, not
    # delegated to generate_synthesis's own boolean. The uncited == 0 bar
    # is not an invented tolerance: it's the same grounding invariant
    # generate_synthesis enforces (B1), restated and checked independently.
    assert total > 0, "model returned no text content at all"
    assert uncited == 0, f"{uncited}/{total} block(s) had no citation at all"
    for text, cites in blocks:
        for c in cites:
            assert document_text[c.start_char : c.end_char] == c.cited_text, (
                f"citation offset mismatch: expected {c.cited_text!r}, "
                f"got {document_text[c.start_char : c.end_char]!r}"
            )
    if sentence:
        assert lexicon.is_clean(sentence), (
            f"real model output failed the lexicon check: {sentence!r} -- "
            f"violations: {lexicon.find_violations(sentence)}"
        )

    # Also exercise the real, retry-wrapped public entry point, logging its
    # verdict -- a second, independent live call (this test spends two
    # billed calls per run, not one; see the module docstring's note on
    # this job's cost-driven, narrower CI trigger).
    result = generate.generate_synthesis(primary, context)
    print(
        "[Epic J calibration] generate_synthesis verdict: "
        + ("accepted" if result else "rejected -- recitation-only ships")
    )
