"""Bootstrap entrypoint for the ML Copilot application."""

from __future__ import annotations

import argparse

from app.config import AppPaths, AppSettings


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


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    settings = AppSettings.from_paths(AppPaths.default())

    if args.print_layout:
        print(format_layout(settings))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
