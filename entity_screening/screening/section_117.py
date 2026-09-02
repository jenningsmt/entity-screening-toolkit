"""Section 117 foreign gift & contract disclosure cross-check.

The last piece of "V2" per docs/requirements.md Section 12's roadmap sentence.
Chains two independent fuzzy matches, both via the same
resolution/matcher.py:score_pair used everywhere else in this project:

1. Institution match -- is this disclosure even about the entity being
   screened? Section 117's `School Name` uses each institution's common name;
   NSF's `awardeeName` is often the legal/governing-board name instead
   ("Regents of the University of Idaho" vs "University of Idaho"). Real
   pairs score 0.72-0.81 without stripping that governance-board affix first
   -- below even the default 0.80 threshold -- and land in a different
   blocking prefix (see docs/plans/2026-09-01-section-117-foreign-gift-
   disclosure-cross-check.md). `strip_institutional_governance_affix` fixes
   the common case; a rarer system-consortium "obo" naming style stays a
   documented miss (docs/methodology.md).
2. Funder match -- is the disclosed foreign entity itself a concern? Reuses
   the same registered concern lists (screening/lists.py) `screen_entity`
   already checks elsewhere in the same run.

Only rows clearing both thresholds produce a hit. `ScreeningHit.confidence`
is the funder-match confidence only -- verified against real data that once
step 1's fix is in place, institution-match confidences cluster at 0.97-1.0,
tight enough that demoting the institution match to `evidence` context
doesn't hide a weak link behind a single headline number.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator

from entity_screening.common.schema import MatchStatus, ResolvedEntity, ScreeningHit, SourceRecord
from entity_screening.resolution.matcher import DEFAULT_THRESHOLD, is_candidate_match, score_pair
from entity_screening.resolution.normalize import (
    normalize_for_matching,
    strip_institutional_governance_affix,
)
from entity_screening.screening.lists import EntityOfConcernList

LIST_NAME = "section_117_foreign_funding_disclosure"
DEFAULT_INSTITUTION_THRESHOLD = 0.90
BLOCK_SIZE = 3

LEGAL_NAME_FIELD = "Restricted Transaction Foreign Government Legal Name"
GOVERNMENT_NAME_FIELD = "Restricted Transaction Foreign Government Name"
OWNER_NAME_FIELD = "Foreign Source Owner Name"


def extract_named_foreign_entity(record: SourceRecord) -> str | None:
    """Returns the specific foreign entity named on a disclosure row, if any.

    Not an "alias precedence" pick among three interchangeable candidates:
    real data shows `Legal Name` is populated in 5,571 of 5,576 real named
    rows and is consistently the specific entity ("Kuwait Embassy"), while
    `Government Name` is consistently just the country/government name
    ("Kuwait") and is never populated on its own. `Government Name` is
    surfaced in evidence by `cross_check_section_117`, never tried here as a
    second independent match candidate -- a bare country name against an
    entity concern list is a different, near-meaningless signal. `Owner
    Name` handles the structurally distinct foreign-ownership-of-institution
    disclosure type (~5 real rows).
    """
    for field in (LEGAL_NAME_FIELD, GOVERNMENT_NAME_FIELD, OWNER_NAME_FIELD):
        value = record.fields.get(field)
        if value and str(value).strip():
            return str(value).strip()
    return None


def _block_index(
    records: Iterable[SourceRecord], block_size: int
) -> dict[str, list[SourceRecord]]:
    index: dict[str, list[SourceRecord]] = defaultdict(list)
    for record in records:
        school_name = record.fields.get("School Name")
        if not school_name:
            continue
        stripped = strip_institutional_governance_affix(str(school_name))
        key = normalize_for_matching(stripped)[:block_size]
        if key:
            index[key].append(record)
    return dict(index)


def cross_check_section_117(
    entity: ResolvedEntity,
    section_117_records: Iterable[SourceRecord],
    concern_lists: Iterable[EntityOfConcernList],
    institution_threshold: float = DEFAULT_INSTITUTION_THRESHOLD,
    funder_threshold: float = DEFAULT_THRESHOLD,
    block_size: int = BLOCK_SIZE,
) -> Iterator[ScreeningHit]:
    concern_lists = list(concern_lists)
    index = _block_index(section_117_records, block_size)
    entity_key = normalize_for_matching(
        strip_institutional_governance_affix(entity.canonical_name)
    )[:block_size]

    for record in index.get(entity_key, []):
        school_name = str(record.fields["School Name"])
        institution_candidate = score_pair(
            strip_institutional_governance_affix(entity.canonical_name),
            strip_institutional_governance_affix(school_name),
        )
        if not is_candidate_match(institution_candidate, institution_threshold):
            continue

        named_entity = extract_named_foreign_entity(record)
        if named_entity is None:
            continue

        for concern_list in concern_lists:
            for entry in concern_list.candidates_for(named_entity, block_size=block_size):
                best_candidate = None
                for variant in entry.name_variants:
                    candidate = score_pair(named_entity, variant)
                    if best_candidate is None or candidate.confidence > best_candidate.confidence:
                        best_candidate = candidate
                if best_candidate is None or not is_candidate_match(best_candidate, funder_threshold):
                    continue
                yield ScreeningHit(
                    entity_id=entity.entity_id,
                    list_name=LIST_NAME,
                    matched_variant=best_candidate.right_name,
                    matched_field="section_117_named_foreign_entity",
                    confidence=best_candidate.confidence,
                    evidence={
                        "entry_id": entry.entry_id,
                        "matched_list": concern_list.list_name,
                        "match_basis": best_candidate.match_basis,
                        "matched_entry_fields": entry.source_fields,
                        "institution_match": {
                            "school_name": school_name,
                            "confidence": institution_candidate.confidence,
                            "match_basis": institution_candidate.match_basis,
                        },
                        "disclosure": {
                            "source_record_id": record.source_record_id,
                            "transaction_type": record.fields.get("Transaction Type"),
                            "attribution_country": record.fields.get("Attribution Country"),
                            "amount": record.fields.get("Amount"),
                            "receipt_date": record.fields.get("Receipt Date"),
                            # Government/country-level context, never itself
                            # used as a match candidate -- see
                            # extract_named_foreign_entity's docstring.
                            "government_name": record.fields.get(GOVERNMENT_NAME_FIELD),
                        },
                    },
                    status=MatchStatus.CANDIDATE_MATCH,
                    producer="section_117",
                )
