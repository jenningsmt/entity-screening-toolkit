from entity_screening.cli import _cmd_validate, build_parser
from entity_screening.common.schema import _FORBIDDEN_OBSERVATION_FIELD_TOKENS, walk_dict_keys


def test_validate_command_passes_on_a_healthy_repo():
    parser = build_parser()
    args = parser.parse_args(["validate"])
    assert _cmd_validate(args) == 0


# --- S15: the recursive evidence-dict-key walker actually descends ---


def test_walk_dict_keys_descends_into_nested_dicts_and_lists():
    nested = {"outer": {"inner": {"risk_note": "x"}, "items": [{"tier": "y"}]}}
    keys = set(walk_dict_keys(nested))
    assert {"risk_note", "tier", "outer", "inner", "items"} <= keys


def test_walk_dict_keys_catches_what_a_top_level_only_check_would_miss():
    """This is S15's actual fix, proven as a property, not just asserted:
    ScreeningHit/ForeignControlFlag's evidence dict can nest a forbidden
    token arbitrarily deep, and a shallow key check (what existed before
    this phase) would silently pass it."""
    nested = {"ownership_path": {"risk_note": "x"}}
    shallow_keys = set(nested.keys())
    assert not any(
        token in key.lower() for key in shallow_keys for token in _FORBIDDEN_OBSERVATION_FIELD_TOKENS
    ), "the shallow check should NOT catch this -- that's the bug"
    deep_keys = set(walk_dict_keys(nested))
    assert any(
        token in key.lower() for key in deep_keys for token in _FORBIDDEN_OBSERVATION_FIELD_TOKENS
    ), "the recursive walk MUST catch it"


def test_cli_parses_run_subcommand_arguments(tmp_path):
    parser = build_parser()
    csv_path = tmp_path / "targets.simple.csv"
    csv_path.write_text("id,schema,name,aliases\n")

    args = parser.parse_args(["run", "--opensanctions-file", str(csv_path)])

    assert args.command == "run"
    assert args.opensanctions_file == csv_path
    assert args.threshold == 0.80
