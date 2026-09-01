from entity_screening.resolution.normalize import (
    acronym,
    normalize_for_matching,
    strip_corporate_suffix,
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
