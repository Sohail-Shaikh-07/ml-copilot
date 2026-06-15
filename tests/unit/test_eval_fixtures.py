"""Tests for bundled eval fixtures."""

from __future__ import annotations

from pathlib import Path

from app.evals.runner import load_fixture


def test_bundled_eval_fixtures_load_and_are_unique() -> None:
    fixture_dir = Path(__file__).resolve().parents[1] / "fixtures" / "evals"
    fixture_paths = sorted(fixture_dir.glob("*.json"))

    assert len(fixture_paths) == 5

    fixtures = [load_fixture(path) for path in fixture_paths]
    fixture_ids = [fixture.id for fixture in fixtures]

    assert fixture_ids == [
        "ml-201-dataset-validation",
        "ml-201-eval-script",
        "ml-201-model-card-inference",
        "ml-201-repo-analysis",
        "ml-201-training-script-fix",
    ]
    assert all(fixture.prompt for fixture in fixtures)
    assert all(fixture.checks for fixture in fixtures)


def test_eval_fixture_filenames_match_ids() -> None:
    fixture_dir = Path(__file__).resolve().parents[1] / "fixtures" / "evals"
    for path in fixture_dir.glob("*.json"):
        fixture = load_fixture(path)
        assert fixture.id in path.stem
