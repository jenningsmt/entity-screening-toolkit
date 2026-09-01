from entity_screening.resolution.matcher import score_pair
from entity_screening.resolution.normalize import (
    acronym,
    normalize_for_matching,
    strip_corporate_suffix,
    strip_institutional_governance_affix,
    transliterate,
)


def test_strip_corporate_suffix_handles_common_forms():
    assert strip_corporate_suffix("Acme Inc.") == "Acme"
    assert strip_corporate_suffix("Acme, LLC") == "Acme"
    assert strip_corporate_suffix("Acme Company Limited") == "Acme"
    assert strip_corporate_suffix("Acme Corporation") == "Acme"


def test_strip_corporate_suffix_leaves_plain_names_alone():
    assert strip_corporate_suffix("Springfield State University") == "Springfield State University"


def test_transliterate_folds_accents():
    assert transliterate("Société Générale") == "Societe Generale"


def test_acronym_skips_stopwords():
    assert acronym("Beijing Institute of Technology") == "BIT"
    assert acronym("International Business Machines Corporation") == "IBMC"


def test_normalize_for_matching_is_case_and_punctuation_insensitive():
    assert normalize_for_matching("Huawei Technologies Co., Ltd.") == normalize_for_matching(
        "Huawei Technologies Company Limited"
    )


# Real pairs pulled from NSF's live awardeeName data and Section 117's real
# School Name column (see docs/plans/2026-09-01-section-117-foreign-gift-
# disclosure-cross-check.md) -- without stripping the governance-board
# affix, these score 0.72-0.81 via score_pair, below even the default 0.80
# screening threshold, let alone Section 117's 0.90 institution threshold.
REAL_GOVERNANCE_AFFIX_PAIRS = [
    ("University of Idaho", "Regents of the University of Idaho"),
    ("Boston University", "Trustees of Boston University"),
    ("University of Central Florida", "The University of Central Florida Board of Trustees"),
    ("University of Michigan - Ann Arbor", "Regents of the University of Michigan - Ann Arbor"),
]


def test_strip_institutional_governance_affix_clears_real_nsf_vs_section_117_pairs():
    for common_name, legal_name in REAL_GOVERNANCE_AFFIX_PAIRS:
        stripped_common = strip_institutional_governance_affix(common_name)
        stripped_legal = strip_institutional_governance_affix(legal_name)
        candidate = score_pair(stripped_common, stripped_legal)
        assert candidate.confidence == 1.0, (common_name, legal_name, candidate)
        assert normalize_for_matching(stripped_common)[:3] == normalize_for_matching(stripped_legal)[:3]


def test_strip_institutional_governance_affix_leaves_plain_names_alone():
    assert strip_institutional_governance_affix("University of Texas at Arlington") == (
        "University of Texas at Arlington"
    )


def test_strip_institutional_governance_affix_handles_trailing_the_paren():
    assert strip_institutional_governance_affix(
        "University of Texas Southwestern Medical Center (The)"
    ) == "University of Texas Southwestern Medical Center"


def test_strip_institutional_governance_affix_documented_residual_gap():
    """A rarer system-consortium "obo" naming style is a known, documented
    miss (docs/methodology.md), not silently passing or being chased with
    further special-casing -- asserted here so a future normalization change
    that happens to fix it is noticed, not just a change that breaks it
    further."""
    common_name = strip_institutional_governance_affix("University of Nevada , Reno")
    legal_name = strip_institutional_governance_affix(
        "Board of Regents, NSHE, obo University of Nevada, Reno"
    )
    candidate = score_pair(common_name, legal_name)
    assert candidate.confidence < 0.90
    assert normalize_for_matching(common_name)[:3] != normalize_for_matching(legal_name)[:3]
