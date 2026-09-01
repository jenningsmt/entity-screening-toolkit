import json
from pathlib import Path

import pytest

from entity_screening.common.schema import MatchStatus
from entity_screening.resolution.matcher import is_candidate_match, score_pair

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


def test_score_pair_never_returns_a_bare_bool():
    candidate = score_pair("Acme Inc.", "Acme Corporation")
    assert isinstance(candidate.confidence, float)
    assert 0.0 <= candidate.confidence <= 1.0


def test_score_pair_status_is_always_candidate_match():
    candidate = score_pair("Acme Inc.", "Acme Corporation")
    assert candidate.status is MatchStatus.CANDIDATE_MATCH
