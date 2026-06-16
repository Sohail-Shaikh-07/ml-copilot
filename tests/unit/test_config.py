from pathlib import Path

import pytest

from app.config import AppPaths, AppSettings, load_environment, parse_bool, read_env_file


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
    assert settings.llm.provider == "openai_compatible"
    assert settings.llm.base_url == "https://api.openai.com/v1"
    assert settings.safety.require_tool_approval is True
    assert settings.usage.prompt_cost_per_1k_tokens_usd == 0.0015
    assert settings.usage.completion_cost_per_1k_tokens_usd == 0.006
    assert settings.mcp.enabled is False
    assert settings.mcp.manifest_path is None


def test_load_uses_env_values_and_defaults(tmp_path: Path) -> None:
    settings = AppSettings.load(
        environ={
            "LLM_API_KEY": "secret-key",
            "LLM_PROVIDER": "anthropic",
            "LLM_MODEL": "gpt-test",
            "ML_COPILOT_WORKSPACE_ROOT": str(tmp_path),
            "ML_COPILOT_REQUIRE_TOOL_APPROVAL": "false",
            "ML_COPILOT_ALLOW_DESTRUCTIVE_COMMANDS": "true",
            "ML_COPILOT_REDACT_SECRETS": "false",
            "ML_COPILOT_ENABLE_MCP": "true",
            "ML_COPILOT_MCP_MANIFEST_PATH": "mcp-tools.json",
            "LLM_PROMPT_COST_PER_1K_TOKENS_USD": "0.01",
            "LLM_COMPLETION_COST_PER_1K_TOKENS_USD": "0.02",
        }
    )

    assert settings.llm.provider == "anthropic"
    assert settings.llm.base_url == "https://api.anthropic.com/v1"
    assert settings.llm.api_key == "secret-key"
    assert settings.llm.model == "gpt-test"
    assert settings.paths.workspace_root == tmp_path.resolve()
    assert settings.db_path == (tmp_path / ".ml-copilot" / "ml-copilot.db").resolve()
    assert settings.safety.require_tool_approval is False
    assert settings.safety.allow_destructive_commands is True
    assert settings.safety.redact_secrets is False
    assert settings.usage.prompt_cost_per_1k_tokens_usd == 0.01
    assert settings.usage.completion_cost_per_1k_tokens_usd == 0.02
    assert settings.mcp.enabled is True
    assert settings.mcp.manifest_path == (tmp_path / "mcp-tools.json").resolve()


def test_environment_prefers_process_env_over_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_MODEL=file-model\nLLM_BASE_URL=https://example.invalid/v1\n",
        encoding="utf-8",
    )

    loaded = load_environment(
        environ={"LLM_MODEL": "process-model"},
        env_file=env_file,
    )

    assert loaded["LLM_MODEL"] == "process-model"
    assert loaded["LLM_BASE_URL"] == "https://example.invalid/v1"


def test_read_env_file_strips_quotes_and_comments(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\nLLM_MODEL=\"quoted-model\"\nLLM_API_KEY='token'\n",
        encoding="utf-8",
    )

    loaded = read_env_file(env_file)

    assert loaded == {
        "LLM_MODEL": "quoted-model",
        "LLM_API_KEY": "token",
    }


def test_parse_bool_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        parse_bool("FLAG", "sometimes", default=True)
