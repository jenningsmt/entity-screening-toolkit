"""Loader for the foreign-adversary-country list (Texas Education Code Sec.
51B.001(4), use-case-01 Section 12 step 4).

Unlike GLEIF or OpenSanctions, this is a handful of ISO country codes, not a
bulk download -- it mirrors `ingestion/dod_1260h.py`'s pattern (a small,
annually-updated, hand-curated static snapshot bundled with the package),
not `ownership/ingest.py`'s bulk-CSV pattern. The curated snapshot lives at
screening/data/adversary_countries.json; see that file's own "provenance"
field for exactly how and from what it was derived, including the two
recorded interpretive decisions (the 2026 ATA's framing, and not using
Texas Executive Order GA-48) -- see
docs/plans/2026-09-14-foreign-adversary-list-ingester.md for the full
research record behind those decisions.

This is deliberately not a live feed. The DNI publishes a new Annual Threat
Assessment roughly once a year, and re-deriving the list is a human
re-reading the new document and re-verifying its citations, not an
unattended script -- the 2026 ATA's own structural break from 2024/2025's
"one chapter, four countries" layout is exactly why an automated parser
would be the wrong tool here (see the plan doc).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DATA_FILE = (
    Path(__file__).resolve().parent / "data" / "adversary_countries.json"
)


@dataclass(frozen=True)
class AdversaryCountryList:
    """`countries` maps each ISO 3166-1 alpha-2 code to its citation list
    (each a dict with at least `kind`, matching the curated JSON's shape) --
    kept, not discarded, so a caller can surface *why* a country is on the
    list, not just that it is."""

    list_version: str
    derived_at: str
    countries: dict[str, tuple[dict, ...]] = field(default_factory=dict)

    def contains(self, country_code: str | None) -> bool | None:
        """None only when `country_code` itself is unresolvable -- once this
        list exists, every resolvable country gets a real True/False, never
        an omission-driven None (use-case doc Section 7's "not yet checked"
        distinction only applies before this list exists at all).

        Normalizes ISO 3166-2 subdivision codes (e.g. GLEIF's occasional
        "US-DE") down to the country prefix before matching -- confirmed
        necessary in practice during the GLEIF verification-gate work, even
        though none of the currently-listed countries need it themselves.
        """
        if not country_code:
            return None
        return country_code.strip().upper().split("-")[0] in self.countries


def load_adversary_list(path: Path | str = DEFAULT_DATA_FILE) -> AdversaryCountryList:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    countries = {
        entry["iso_code"]: tuple(entry.get("citations", ()))
        for entry in payload.get("countries", [])
    }
    return AdversaryCountryList(
        list_version=payload["list_version"],
        derived_at=payload["derived_at"],
        countries=countries,
    )
