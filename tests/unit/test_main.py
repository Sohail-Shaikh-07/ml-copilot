from app.config import AppPaths, AppSettings
from app.main import build_parser, format_config, format_layout, main


def test_build_parser_uses_project_name() -> None:
    parser = build_parser()

    assert parser.prog == "ml-copilot"


def test_format_layout_includes_expected_directories() -> None:
    output = format_layout(AppSettings.from_paths(AppPaths.default()))

    assert "workspace_root=" in output
    assert "app_dir=" in output
    assert "tests_dir=" in output


def test_format_config_redacts_api_key() -> None:
    settings = AppSettings.load(
        environ={
            "LLM_API_KEY": "top-secret",
            "ML_COPILOT_WORKSPACE_ROOT": str(AppPaths.default().workspace_root),
        }
    )

    output = format_config(settings)

    assert "llm.api_key=<redacted>" in output
    assert "top-secret" not in output


def test_main_returns_success_for_default_help(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["ml-copilot"])

    exit_code = main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Focused ML engineering agent" in captured.out


def test_main_prints_config(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setattr("sys.argv", ["ml-copilot", "--print-config"])
    monkeypatch.setenv("ML_COPILOT_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "gpt-config")

    exit_code = main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "ML Copilot configuration" in captured.out
    assert "llm.model=gpt-config" in captured.out
