from entity_screening.cli import _cmd_validate, build_parser


def test_validate_command_passes_on_a_healthy_repo():
    parser = build_parser()
    args = parser.parse_args(["validate"])
    assert _cmd_validate(args) == 0


def test_cli_parses_run_subcommand_arguments(tmp_path):
    parser = build_parser()
    csv_path = tmp_path / "targets.simple.csv"
    csv_path.write_text("id,schema,name,aliases\n")

    args = parser.parse_args(["run", "--opensanctions-file", str(csv_path)])

    assert args.command == "run"
    assert args.opensanctions_file == csv_path
    assert args.threshold == 0.80
