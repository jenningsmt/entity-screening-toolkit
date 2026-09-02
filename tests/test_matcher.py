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
