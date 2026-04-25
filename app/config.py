"""Bootstrap configuration primitives.

This module intentionally stays light for ML-2. Environment loading and richer
runtime settings belong to the dedicated configuration task later in Phase 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
        return cls(
            workspace_root=workspace_root,
            app_dir=workspace_root / "app",
            tests_dir=workspace_root / "tests",
            docs_dir=workspace_root / "docs",
            scripts_dir=workspace_root / "scripts",
        )


@dataclass(frozen=True)
class AppSettings:
    app_name: str
    version: str
    paths: AppPaths

    @classmethod
    def from_paths(cls, paths: AppPaths) -> "AppSettings":
        return cls(
            app_name="ML Copilot",
            version="0.1.0",
            paths=paths,
        )
