"""Restricted-party screening (RPS): screen a ScreeningParty's name against
the registered entity-of-concern lists -- Use Case 02, step 5.

Reuses the *same* `OpenSanctionsList` matching machinery already built for
HB 127 (Epic D), which already carries every list TAMU's own Export Control
Compliance Program Manual names: the OFAC SDN List, the State Department
Foreign Terrorist Organizations list, and (via OpenSanctions'
`us_trade_csl` source -- the U.S. government's own Consolidated Screening
List) the BIS Denied Persons/Entity/Unverified Lists, the State Department
AECA Debarred Parties list, and State Department Nonproliferation Sanctions
-- confirmed against the real, live `us_trade_csl` data during this
feature's planning, not assumed (docs/plans/2026-09-14-restricted-party-
screening.md). No new curated list or ingestion code is needed.

This module deliberately does not import
`reconciliation/discover.py:_screen_name_against_concern_lists`, even though
the logic below mirrors it closely: `reconciliation/` already imports from
`screening/` (for `EntityOfConcernList`/`AdversaryCountryList`), so the
reverse import would invert this project's established layering. The small
duplication here is the cheaper cost.

**Explicit scope boundary, repeated from rps_schema.py's module docstring
so it is visible from whichever file a reader opens first:** this screens
*names* only. `ScreeningParty.country` is never checked against OFAC's
embargoed-country list or any other country-level gate.
"""
from __future__ import annotations

import uuid

from entity_screening.common.schema import MatchStatus
from entity_screening.resolution.matcher import DEFAULT_THRESHOLD, is_candidate_match, score_pair
from entity_screening.screening.lists import EntityOfConcernList
from entity_screening.screening.rps_schema import PartyKind, ScreeningMatch, ScreeningParty


def screen_party(
    party: ScreeningParty,
    concern_lists: list[EntityOfConcernList],
    threshold: float = DEFAULT_THRESHOLD,
) -> list[ScreeningMatch]:
    """Screens one party's name against every registered concern list.
    Returns one ScreeningMatch per list entry that clears `threshold` --
    never a bare boolean, always confidence-scored and evidence-carrying,
    matching every other matcher in this codebase."""
    matches: list[ScreeningMatch] = []
    for concern_list in concern_lists:
        for entry in concern_list.candidates_for(party.name):
            best = None
            for variant in entry.name_variants:
                # S9: a person's name is never an organization's acronym or
                # a corporate-suffix-bearing form -- skip both heuristics
                # for PartyKind.PERSON (see score_pair's own docstring).
                candidate = score_pair(
                    party.name, variant, skip_org_heuristics=party.kind is PartyKind.PERSON
                )
                if best is None or candidate.confidence > best.confidence:
                    best = candidate
            if best is None or not is_candidate_match(best, threshold):
                continue
            matches.append(
                ScreeningMatch(
                    match_id=str(uuid.uuid4()),
                    party_id=party.party_id,
                    matched_variant=best.right_name,
                    matched_field=party.role_in_event,
                    list_name=concern_list.list_name,
                    confidence=best.confidence,
                    evidence={
                        "entry_id": entry.entry_id,
                        "match_basis": best.match_basis,
                        "matched_entry_fields": entry.source_fields,
                    },
                    status=MatchStatus.CANDIDATE_MATCH,
                )
            )
    return matches


def screen_parties(
    parties: list[ScreeningParty],
    concern_lists: list[EntityOfConcernList],
    threshold: float = DEFAULT_THRESHOLD,
) -> dict[str, list[ScreeningMatch]]:
    """screen_party for every party in one ScreeningEvent, keyed by party_id."""
    return {party.party_id: screen_party(party, concern_lists, threshold) for party in parties}
