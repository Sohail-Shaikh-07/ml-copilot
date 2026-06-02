"""Tests for app.tools.datasets module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.config import AppPaths, AppSettings
from app.tools.datasets import (
    _inspect_csv,
    _inspect_jsonl,
    _looks_like_path,
    get_tool_specs,
    inspect_dataset_handler,
)


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings.from_paths(AppPaths.from_workspace_root(tmp_path))


class TestLooksLikePath:
    def test_csv_extension(self, tmp_path: Path) -> None:
        assert _looks_like_path("data/train.csv", tmp_path) is True

    def test_jsonl_extension(self, tmp_path: Path) -> None:
        assert _looks_like_path("data.jsonl", tmp_path) is True

    def test_parquet_extension(self, tmp_path: Path) -> None:
        assert _looks_like_path("model/data.parquet", tmp_path) is True

    def test_hf_dataset_name(self, tmp_path: Path) -> None:
        assert _looks_like_path("imdb", tmp_path) is False

    def test_existing_file(self, tmp_path: Path) -> None:
        (tmp_path / "myfile").write_text("x")
        assert _looks_like_path("myfile", tmp_path) is True


class TestInspectCsv:
    def test_basic_csv(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("name,age,city\nAlice,30,NYC\nBob,,London\n")
        result = _inspect_csv(csv_file, sample_rows=2)
        assert "data.csv" in result
        assert "Columns:** 3" in result
        assert "name" in result
        assert "Alice" in result
        assert "age" in result

    def test_missing_values(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "gaps.csv"
        csv_file.write_text("a,b\n1,\n2,\n3,x\n")
        result = _inspect_csv(csv_file, sample_rows=1)
        assert "2/3" in result  # 2 missing out of 3

    def test_empty_file(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("")
        result = _inspect_csv(csv_file, sample_rows=1)
        assert "empty" in result.lower()

    def test_tsv(self, tmp_path: Path) -> None:
        tsv_file = tmp_path / "data.tsv"
        tsv_file.write_text("col1\tcol2\nval1\tval2\n")
        result = _inspect_csv(tsv_file, sample_rows=1, delimiter="\t")
        assert "col1" in result
        assert "val1" in result


class TestInspectJsonl:
    def test_basic_jsonl(self, tmp_path: Path) -> None:
        f = tmp_path / "data.jsonl"
        f.write_text('{"text":"hello","label":1}\n{"text":"world","label":0}\n')
        result = _inspect_jsonl(f, sample_rows=2)
        assert "data.jsonl" in result
        assert "text" in result
        assert "label" in result
        assert "hello" in result

    def test_missing_fields(self, tmp_path: Path) -> None:
        f = tmp_path / "data.jsonl"
        f.write_text('{"a":1,"b":2}\n{"a":3}\n')
        result = _inspect_jsonl(f, sample_rows=1)
        assert "1/2" in result  # b missing in 1 of 2 records

    def test_parse_errors(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.jsonl"
        f.write_text('{"a":1}\nnot json\n{"a":2}\n')
        result = _inspect_jsonl(f, sample_rows=1)
        assert "Parse errors" in result

    def test_empty_jsonl(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.jsonl"
        f.write_text("\n\n")
        result = _inspect_jsonl(f, sample_rows=1)
        assert "Error" in result


class TestInspectDatasetHandler:
    @pytest.mark.asyncio
    async def test_local_csv(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "train.csv"
        csv_file.write_text("x,y\n1,2\n3,4\n")
        settings = _settings(tmp_path)
        result = await inspect_dataset_handler({"source": "train.csv"}, settings)
        assert "train.csv" in result
        assert "x" in result

    @pytest.mark.asyncio
    async def test_missing_source(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        result = await inspect_dataset_handler({}, settings)
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_nonexistent_file(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        result = await inspect_dataset_handler({"source": "nope.csv"}, settings)
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_workspace_escape(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        result = await inspect_dataset_handler({"source": "../../etc/passwd"}, settings)
        assert "outside workspace" in result.lower()

    @pytest.mark.asyncio
    async def test_unsupported_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("binary")
        settings = _settings(tmp_path)
        result = await inspect_dataset_handler({"source": "data.xlsx"}, settings)
        assert "Unsupported" in result

    @pytest.mark.asyncio
    async def test_hf_dataset(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        mock_responses = [
            {"preview": True},
            {"splits": [{"config": "default", "split": "train"}]},
        ]
        with patch("app.tools.datasets._hf_parallel", new_callable=AsyncMock) as mock_hf:
            mock_hf.side_effect = [
                mock_responses,
                [{"dataset_info": {"features": {"text": {"dtype": "string"}}}}, {"rows": []}],
            ]
            result = await inspect_dataset_handler({"source": "username/dataset"}, settings)
        assert "Hugging Face" in result


class TestGetToolSpecs:
    def test_spec(self) -> None:
        specs = get_tool_specs()
        assert len(specs) == 1
        assert specs[0]["name"] == "inspect_dataset"
        assert "source" in specs[0]["parameters"]["properties"]
