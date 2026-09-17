import datetime
import json
import uuid
from pathlib import Path

import pytest

from entity_screening.common.schema import MatchStatus, ResolvedEntity, SourceRecord
from entity_screening.resolution.matcher import is_candidate_match, score_pair
from entity_screening.screening.lists import OpenSanctionsList
from entity_screening.screening.screen import screen_entity

FIXTURES_DIR = Path(__file__).parent / "fixtures"
KNOWN_DIFFICULT_PAIRS = json.loads(
    (FIXTURES_DIR / "known_difficult_pairs.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize(
    "pair", KNOWN_DIFFICULT_PAIRS, ids=[p["reason"] for p in KNOWN_DIFFICULT_PAIRS]
)
def test_known_difficult_pairs(pair):
    candidate = score_pair(pair["left"], pair["right"])
    assert is_candidate_match(candidate) == pair["expect_match"], (
        f"{pair['left']!r} vs {pair['right']!r} ({pair['reason']}): "
        f"got confidence={candidate.confidence:.2f} basis={candidate.match_basis!r}"
    )


@pytest.mark.parametrize(
    "pair", KNOWN_DIFFICULT_PAIRS, ids=[p["reason"] for p in KNOWN_DIFFICULT_PAIRS]
)
def test_known_difficult_pairs_through_screen_entity(pair):
    """Regression for Finding 1: test_known_difficult_pairs above calls
    score_pair directly, which is why the blocking-step defect shipped
    undetected -- every acronym case in this fixture passed at the scorer
    level while being completely unreachable through the actual screening
    path (screen_entity's blocking step never returned the concern-list
    entry as a candidate in the first place). Epic B's acceptance criterion
    is about screening entities, not about the scorer in isolation, so the
    regression set has to be checked at that seam too."""
    concern_list = OpenSanctionsList(
        [
            SourceRecord(
                source_dataset="opensanctions_targets_simple",
                retrieval_date=datetime.date(2026, 1, 1),
                source_record_id="known-difficult-1",
                fields={"id": "known-difficult-1", "schema": "Company", "name": pair["right"], "aliases": ""},
            )
        ]
    )
    entity = ResolvedEntity(
        entity_id=str(uuid.uuid4()), canonical_name=pair["left"], entity_type="organization",
        source_records=(),
    )

    hits = list(screen_entity(entity, [concern_list]))

    assert bool(hits) == pair["expect_match"], (
        f"{pair['left']!r} vs {pair['right']!r} ({pair['reason']}) through screen_entity: "
        f"got {len(hits)} hit(s)"
    )


def test_score_pair_never_returns_a_bare_bool():
    candidate = score_pair("Acme Inc.", "Acme Corporation")
    assert isinstance(candidate.confidence, float)
    assert 0.0 <= candidate.confidence <= 1.0


def test_score_pair_status_is_always_candidate_match():
    candidate = score_pair("Acme Inc.", "Acme Corporation")
    assert candidate.status is MatchStatus.CANDIDATE_MATCH


# --------------------------------------------------------------------------
# S9: person-name screening false positives from org-name heuristics.
# --------------------------------------------------------------------------


def test_person_name_acronym_false_positive_confirmed_and_fixed():
    """The real bug this fixture reproduces: a Turkish dotless-i name
    fragments under the old ASCII-only acronym regex, and a person's
    surname ("Sa") gets stripped as a corporate suffix -- together they
    produce a 0.9 confidence "acronym" match between two unrelated
    people. The regex fix alone (default score_pair, no flag) already
    drops this below any real threshold."""
    candidate = score_pair("Ana Sa", "Akın Alptuna")
    assert candidate.confidence < 0.5
    assert candidate.match_basis != "acronym"


def test_skip_org_heuristics_does_not_regress_the_person_false_positive():
    candidate = score_pair("Ana Sa", "Akın Alptuna", skip_org_heuristics=True)
    assert candidate.confidence < 0.5
    assert candidate.match_basis != "acronym"


def test_skip_org_heuristics_prevents_a_surname_from_being_stripped_as_a_suffix():
    """Independent of the acronym bug: strip_corporate_suffix treats a
    person's surname "Co" as a corporate form, which -- baked into
    normalize_for_matching -- collapses "Robert Co" to "Robert" for
    BOTH the normalized-exact check and the fuzzy fallback. The default,
    org-path score_pair still does this (unchanged, deliberately);
    skip_org_heuristics=True must not."""
    unmodified = score_pair("Robert Co", "Robert")
    assert unmodified.confidence == 1.0
    assert unmodified.match_basis == "normalized_exact"

    person_aware = score_pair("Robert Co", "Robert", skip_org_heuristics=True)
    assert person_aware.match_basis != "normalized_exact"


def test_skip_org_heuristics_leaves_the_acronym_branch_unreachable():
    """With the bypass on, a real organization acronym (which would
    otherwise match at 0.9) must not fire -- confirming the acronym
    branch is skipped entirely, not just de-prioritized."""
    org_path = score_pair("International Business Machines Corporation", "IBM")
    assert org_path.match_basis == "acronym"

    person_aware = score_pair(
        "International Business Machines Corporation", "IBM", skip_org_heuristics=True
    )
    assert person_aware.match_basis != "acronym"
