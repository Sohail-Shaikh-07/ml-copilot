"""Application configuration and environment loading."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class AppPaths:
    workspace_root: Path
    app_dir: Path
    tests_dir: Path
    docs_dir: Path
    scripts_dir: Path

    @classmethod
    def default(cls) -> "AppPaths":
        workspace_root = Path(__file__).resolve().parent.parent
        return cls.from_workspace_root(workspace_root)

    @classmethod
    def from_workspace_root(cls, workspace_root: Path) -> "AppPaths":
        workspace_root = workspace_root.resolve()
        return cls(
            workspace_root=workspace_root,
            app_dir=workspace_root / "app",
            tests_dir=workspace_root / "tests",
            docs_dir=workspace_root / "docs",
            scripts_dir=workspace_root / "scripts",
        )


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    base_url: str
    api_key: str | None
    model: str
    timeout_seconds: int


@dataclass(frozen=True)
class SafetySettings:
    require_tool_approval: bool
    allow_destructive_commands: bool
    redact_secrets: bool


@dataclass(frozen=True)
class UsageAccountingSettings:
    prompt_cost_per_1k_tokens_usd: float
    completion_cost_per_1k_tokens_usd: float


@dataclass(frozen=True)
class MCPSettings:
    enabled: bool
    manifest_path: Path | None


@dataclass(frozen=True)
class AppSettings:
    app_name: str
    version: str
    paths: AppPaths
    llm: LLMSettings
    db_path: Path
    safety: SafetySettings
    usage: UsageAccountingSettings
    mcp: MCPSettings

    @classmethod
    def from_paths(cls, paths: AppPaths) -> "AppSettings":
        return cls(
            app_name="ML Copilot",
            version="0.1.0",
            paths=paths,
            llm=LLMSettings(
                provider="openai_compatible",
                base_url="https://api.openai.com/v1",
                api_key=None,
                model="gpt-5.4",
                timeout_seconds=600,
            ),
            db_path=paths.workspace_root / ".ml-copilot" / "ml-copilot.db",
            safety=SafetySettings(
                require_tool_approval=True,
                allow_destructive_commands=False,
                redact_secrets=True,
            ),
            usage=UsageAccountingSettings(
                prompt_cost_per_1k_tokens_usd=0.0015,
                completion_cost_per_1k_tokens_usd=0.006,
            ),
            mcp=MCPSettings(
                enabled=False,
                manifest_path=None,
            ),
        )

    @classmethod
    def load(
        cls,
        environ: Mapping[str, str] | None = None,
        env_file: Path | None = None,
    ) -> "AppSettings":
        merged_env = load_environment(environ=environ, env_file=env_file)
        provider = normalize_llm_provider(merged_env.get("LLM_PROVIDER"))
        workspace_root = Path(merged_env.get("ML_COPILOT_WORKSPACE_ROOT", str(AppPaths.default().workspace_root)))
        paths = AppPaths.from_workspace_root(workspace_root)

        db_path = Path(
            merged_env.get(
                "ML_COPILOT_DB_PATH",
                str(paths.workspace_root / ".ml-copilot" / "ml-copilot.db"),
            )
        )
        if not db_path.is_absolute():
            db_path = paths.workspace_root / db_path

        mcp_manifest_path = blank_to_none(merged_env.get("ML_COPILOT_MCP_MANIFEST_PATH"))
        resolved_mcp_manifest_path = Path(mcp_manifest_path) if mcp_manifest_path else None
        if resolved_mcp_manifest_path is not None and not resolved_mcp_manifest_path.is_absolute():
            resolved_mcp_manifest_path = paths.workspace_root / resolved_mcp_manifest_path

        return cls(
            app_name="ML Copilot",
            version="0.1.0",
            paths=paths,
            llm=LLMSettings(
                provider=provider,
                base_url=merged_env.get("LLM_BASE_URL", default_llm_base_url(provider)),
                api_key=blank_to_none(merged_env.get("LLM_API_KEY")),
                model=merged_env.get("LLM_MODEL", "gpt-5.4"),
                timeout_seconds=parse_int(
                    "LLM_TIMEOUT_SECONDS",
                    merged_env.get("LLM_TIMEOUT_SECONDS"),
                    default=600,
                    minimum=1,
                ),
            ),
            db_path=db_path.resolve(),
            safety=SafetySettings(
                require_tool_approval=parse_bool(
                    "ML_COPILOT_REQUIRE_TOOL_APPROVAL",
                    merged_env.get("ML_COPILOT_REQUIRE_TOOL_APPROVAL"),
                    default=True,
                ),
                allow_destructive_commands=parse_bool(
                    "ML_COPILOT_ALLOW_DESTRUCTIVE_COMMANDS",
                    merged_env.get("ML_COPILOT_ALLOW_DESTRUCTIVE_COMMANDS"),
                    default=False,
                ),
                redact_secrets=parse_bool(
                    "ML_COPILOT_REDACT_SECRETS",
                    merged_env.get("ML_COPILOT_REDACT_SECRETS"),
                    default=True,
                ),
            ),
            usage=UsageAccountingSettings(
                prompt_cost_per_1k_tokens_usd=parse_float(
                    "LLM_PROMPT_COST_PER_1K_TOKENS_USD",
                    merged_env.get("LLM_PROMPT_COST_PER_1K_TOKENS_USD"),
                    default=0.0015,
                    minimum=0.0,
                ),
                completion_cost_per_1k_tokens_usd=parse_float(
                    "LLM_COMPLETION_COST_PER_1K_TOKENS_USD",
                    merged_env.get("LLM_COMPLETION_COST_PER_1K_TOKENS_USD"),
                    default=0.006,
                    minimum=0.0,
                ),
            ),
            mcp=MCPSettings(
                enabled=parse_bool(
                    "ML_COPILOT_ENABLE_MCP",
                    merged_env.get("ML_COPILOT_ENABLE_MCP"),
                    default=False,
                ),
                manifest_path=resolved_mcp_manifest_path.resolve() if resolved_mcp_manifest_path else None,
            ),
        )


def blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def parse_bool(name: str, value: str | None, *, default: bool) -> bool:
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value, got {value!r}.")


def parse_int(name: str, value: str | None, *, default: int, minimum: int | None = None) -> int:
    if value is None:
        return default

    parsed = int(value)
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {parsed}.")
    return parsed


def parse_float(name: str, value: str | None, *, default: float, minimum: float | None = None) -> float:
    if value is None:
        return default

    parsed = float(value)
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {parsed}.")
    return parsed


def load_environment(
    environ: Mapping[str, str] | None = None,
    env_file: Path | None = None,
) -> dict[str, str]:
    environment = dict(os.environ if environ is None else environ)
    resolved_env_file = _resolve_env_file(environment, env_file=env_file)
    file_values = read_env_file(resolved_env_file)
    return {**file_values, **environment}


def _resolve_env_file(environment: Mapping[str, str], env_file: Path | None) -> Path:
    if env_file is not None:
        return env_file

    configured = environment.get("ML_COPILOT_ENV_FILE")
    if configured:
        return Path(configured)

    return AppPaths.default().workspace_root / ".env"


def read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid env line in {path}: {raw_line!r}")

        key, raw_value = line.split("=", 1)
        values[key.strip()] = strip_optional_quotes(raw_value.strip())
    return values


def strip_optional_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def normalize_llm_provider(value: str | None) -> str:
    normalized = (value or "openai_compatible").strip().lower().replace("-", "_")
    if normalized in {"openai", "openai_compatible", "compatible"}:
        return "openai_compatible"
    if normalized in {"anthropic", "claude"}:
        return "anthropic"
    if normalized in {"gemini", "google_gemini", "google"}:
        return "gemini"
    if normalized in {"xai", "grok"}:
        return "xai"
    if normalized == "minimax":
        return "minimax"
    if normalized == "kimi":
        return "kimi"
    if normalized in {"zai", "z_ai", "z"}:
        return "zai"
    raise ValueError(f"Unsupported LLM provider: {value!r}")


def default_llm_base_url(provider: str) -> str:
    if provider == "anthropic":
        return "https://api.anthropic.com/v1"
    if provider == "gemini":
        return "https://generativelanguage.googleapis.com/v1beta"
    if provider == "xai":
        return "https://api.x.ai/v1"
    return "https://api.openai.com/v1"
