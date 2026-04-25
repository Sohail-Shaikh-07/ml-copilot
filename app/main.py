"""Bootstrap entrypoint for the ML Copilot application."""

from __future__ import annotations

import argparse

from app.config import AppSettings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ml-copilot",
        description="Focused ML engineering agent for repository analysis and safe automation.",
    )
    parser.add_argument(
        "--print-layout",
        action="store_true",
        help="Print the expected repository layout for the current bootstrap slice.",
    )
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="Print the effective runtime configuration with sensitive values redacted.",
    )
    return parser


def format_layout(settings: AppSettings) -> str:
    paths = settings.paths
    return "\n".join(
        [
            "ML Copilot bootstrap is ready.",
            f"workspace_root={paths.workspace_root}",
            f"app_dir={paths.app_dir}",
            f"tests_dir={paths.tests_dir}",
            f"docs_dir={paths.docs_dir}",
            f"scripts_dir={paths.scripts_dir}",
        ]
    )


def format_config(settings: AppSettings) -> str:
    redacted_api_key = "<unset>" if settings.llm.api_key is None else "<redacted>"
    return "\n".join(
        [
            "ML Copilot configuration",
            f"workspace_root={settings.paths.workspace_root}",
            f"db_path={settings.db_path}",
            f"llm.base_url={settings.llm.base_url}",
            f"llm.model={settings.llm.model}",
            f"llm.api_key={redacted_api_key}",
            f"llm.timeout_seconds={settings.llm.timeout_seconds}",
            f"safety.require_tool_approval={settings.safety.require_tool_approval}",
            f"safety.allow_destructive_commands={settings.safety.allow_destructive_commands}",
            f"safety.redact_secrets={settings.safety.redact_secrets}",
        ]
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    settings = AppSettings.load()

    if args.print_layout:
        print(format_layout(settings))
        return 0

    if args.print_config:
        print(format_config(settings))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
