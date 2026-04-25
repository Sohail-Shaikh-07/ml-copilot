from app.config import AppPaths, AppSettings


def test_default_paths_are_repo_relative() -> None:
    paths = AppPaths.default()

    assert paths.app_dir == paths.workspace_root / "app"
    assert paths.tests_dir == paths.workspace_root / "tests"
    assert paths.docs_dir == paths.workspace_root / "docs"
    assert paths.scripts_dir == paths.workspace_root / "scripts"


def test_settings_wrap_default_paths() -> None:
    settings = AppSettings.from_paths(AppPaths.default())

    assert settings.app_name == "ML Copilot"
    assert settings.version == "0.1.0"
    assert settings.paths.workspace_root.name == "ml-copilot"
