"""Known-important-entity regression test for the "Seven Sons of National
Defence" universities (docs/requirements.md Section 12's V3 roadmap item),
mirroring known_difficult_pairs.json's pattern.

Real-data finding (docs/plans/2026-09-01-v3-openalex-bibliometric-affiliation-layer.md,
Finding 1): grepping the real, full OpenSanctions targets.simple.csv (455MB,
~1.22M rows) showed all seven Seven Sons universities already exist as standalone,
well-aliased entries there, several explicitly citing NDAA Section 1286 as their
designation basis. The existing OpenSanctionsList + screen_entity() (built since V1)
already catches these with zero new code, once run against a real OpenSanctions
download rather than a tiny fixture -- so this project deliberately does NOT ship a
dedicated SevenSonsList/curated file (that would duplicate coverage that already
exists, the mirror image of why DoD 1260H needed its own list). This test proves
that claim against a small fixture built from the real names/aliases found in that
grep, rather than requiring the full 455MB file in the test suite.

Known limitation, documented in docs/data_sources.md: this coverage is contingent
on OpenSanctions continuing to carry these NDAA-1286 designations. Unlike DoD 1260H's
bundled static snapshot, there is no independent fallback here if a future
OpenSanctions update ever drops or re-labels them.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from entity_screening.common.schema import ResolvedEntity
from entity_screening.ingestion.base import IngestionErrorLog
from entity_screening.ingestion.opensanctions import OpenSanctionsTargetsIngester
from entity_screening.screening.lists import OpenSanctionsList
from entity_screening.screening.screen import screen_entity

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SEVEN_SONS_FIXTURE = FIXTURES_DIR / "seven_sons_opensanctions_sample.csv"

# The real common names, as they'd appear as an NSF-resolved entity's canonical_name.
SEVEN_SONS_REAL_NAMES = [
    "Beihang University",
    "Beijing Institute of Technology",
    "Harbin Engineering University",
    "Harbin Institute of Technology",
    "Nanjing University of Aeronautics and Astronautics",
    "Nanjing University of Science and Technology",
    "Northwestern Polytechnical University",
]


def _entity(name: str) -> ResolvedEntity:
    return ResolvedEntity(
        entity_id=str(uuid.uuid4()), canonical_name=name, entity_type="organization",
        source_records=(),
    )


def test_existing_opensanctions_list_finds_all_seven_sons_with_no_new_code(tmp_path):
    error_log = IngestionErrorLog(tmp_path / "errors.jsonl")
    records = list(
        OpenSanctionsTargetsIngester(error_log, csv_path=SEVEN_SONS_FIXTURE).stream_records()
    )
    error_log.close()
    assert len(records) == 7

    concern_list = OpenSanctionsList(records)

    for real_name in SEVEN_SONS_REAL_NAMES:
        hits = list(screen_entity(_entity(real_name), [concern_list]))
        assert len(hits) == 1, f"expected exactly one hit for {real_name!r}, got {hits}"
        assert hits[0].list_name == "opensanctions_consolidated"
        assert hits[0].confidence == 1.0


def test_seven_sons_also_match_via_their_real_acronym_aliases():
    """NSF award data doesn't always use an institution's full common name --
    confirms the acronym aliases found in the real OpenSanctions data also work.

    This passes because the real OpenSanctions entries happen to carry both
    the full name *and* the acronym as separate name_variants on the same
    entry, so the (pre-Finding-1-fix) name-key-only block index already
    contained a key for the acronym string itself -- a property of
    OpenSanctions' data quality for these specific entries, not proof that
    acronym matching works in general. It does not exercise the general case
    (an acronym matching a concern-list entry that carries *only* the full
    name, with no acronym alias present) -- that's what
    tests/test_matcher.py:test_known_difficult_pairs_through_screen_entity
    and tests/test_screening.py:test_blocking_does_not_drop_a_true_match_outside_default_block
    cover, and what screening/lists.py's acronym-key blocking (Finding 1) now
    makes reachable regardless of whether a list entry happens to carry both
    spellings."""
    error_log_path = "seven_sons_acronym_test_errors.jsonl"
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        error_log = IngestionErrorLog(Path(tmp) / error_log_path)
        records = list(
            OpenSanctionsTargetsIngester(error_log, csv_path=SEVEN_SONS_FIXTURE).stream_records()
        )
        error_log.close()

    concern_list = OpenSanctionsList(records)

    for acronym in ["BUAA", "BIT", "HEU", "HIT", "NUAA", "NJUST", "NPU"]:
        hits = list(screen_entity(_entity(acronym), [concern_list]))
        assert len(hits) == 1, f"expected exactly one hit for acronym {acronym!r}, got {hits}"
