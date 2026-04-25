from app.main import build_parser, format_layout, main


def test_build_parser_uses_project_name() -> None:
    parser = build_parser()

    assert parser.prog == "ml-copilot"


def test_format_layout_includes_expected_directories() -> None:
    output = format_layout(__import__("app.config", fromlist=["AppSettings"]).AppSettings.from_paths(
        __import__("app.config", fromlist=["AppPaths"]).AppPaths.default()
    ))

    assert "workspace_root=" in output
    assert "app_dir=" in output
    assert "tests_dir=" in output


def test_main_returns_success_for_default_help(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["ml-copilot"])

    exit_code = main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Focused ML engineering agent" in captured.out
