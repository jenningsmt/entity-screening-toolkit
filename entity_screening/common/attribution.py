"""Per-source attribution, license, and precision-caveat text.

Finding 6 / Epic E's third criterion ("every result surfaces OpenAlex's own
stated match-precision caveat inline, not buried in documentation") and
Section 10's license-compliance NFR ("surfaced in output, not just in a
README") were both true only in the Streamlit UI before this module existed:
`OPENALEX_PRECISION_DISCLAIMER` lived at `app.py` module scope as an
`st.caption`, and no CSV row or API response carried it at all. Every
producer (`screening/screen.py`, `screening/section_117.py`,
`bibliometric/cross_check.py`) now injects
`evidence["source_attribution"] = attribution_for(...)` into every
`ScreeningHit` it yields, so `evidence` — already serialized whole through
both the API and the CSV/Excel export, per Section 9a's self-contained-
evidence requirement — carries it everywhere a hit does, and no consumer can
drop it the way `app.py`'s own module constant could be (and was).

The strings below are lifted **verbatim** from `docs/data_sources.md`'s
Attribution/License bullets — that file remains the canonical prose source,
the one to edit first. Keep the two in step: this module's whole job is
making the same wording reach the evidence trail, not originating new
wording, so a source's attribution text changing in `docs/data_sources.md`
without a matching update here recreates exactly the "guarantee made in one
layer, quietly lost at a boundary" pattern this workstream exists to close.
`cli.py validate` checks that every list registered in
`screening/lists.py:registered_lists()`, plus Section 117's `LIST_NAME`, has
an entry here — so a future list added without attribution fails CI rather
than shipping silently unattributed.
"""
from __future__ import annotations

OPENALEX_PRECISION_CAVEAT = (
    "OpenAlex's own stated affiliation-matching precision: \">98% precision and "
    ">90% recall for most academic institutions. But across the full corpus of "
    "all scholarly works in OpenAlex (500M+), that's still millions of errors.\" "
    "(source: OpenAlex's own blog) -- a bibliometric hit inherits this "
    "uncertainty on top of this project's own author-disambiguation and "
    "cross-check confidence."
)

_ATTRIBUTIONS: dict[str, dict[str, str]] = {
    "opensanctions_consolidated": {
        "attribution": (
            "Data: OpenSanctions (opensanctions.org), consolidated targets "
            "export, retrieved on the date recorded in this run's manifest."
        ),
        "license": (
            "Free for non-commercial and journalistic use under OpenSanctions' "
            "own terms; commercial use requires a separate data license. See "
            "https://www.opensanctions.org/licensing/ for current terms."
        ),
    },
    "dod_section_1260h": {
        "attribution": (
            "Source: U.S. Department of Defense, Section 1260H list (Public Law "
            "116-283); compiled via OpenSanctions (opensanctions.org). Snapshot "
            "dated in this run's manifest under `dod_section_1260h`."
        ),
        "license": (
            "U.S. Government work — not subject to copyright in the United "
            "States (17 U.S.C. § 105)."
        ),
    },
    "section_117_foreign_funding_disclosure": {
        "attribution": (
            "Source: U.S. Department of Education, Section 117 foreign gift and "
            "contract disclosures (foreignfundinghighered.gov). Snapshot dated "
            "in this run's manifest under `section_117_foreign_funding_disclosure`."
        ),
        "license": (
            "U.S. Government work — not subject to copyright in the United "
            "States (17 U.S.C. § 105)."
        ),
    },
}


def attribution_for(source: str) -> dict[str, str]:
    """{attribution, license} for a registered concern-list/source identifier
    (the same string as `EntityOfConcernList.list_name` or Section 117's
    `LIST_NAME`). Returns an empty dict for an unregistered source rather
    than raising, so a caller can still write a hit's evidence for a source
    that genuinely has no attribution entry yet -- `cli.py validate` is what
    turns that gap into a build failure, not this function at hit-construction
    time."""
    return dict(_ATTRIBUTIONS.get(source, {}))


def registered_sources() -> tuple[str, ...]:
    return tuple(_ATTRIBUTIONS)
