"""Configuration-boundary tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from skill_eval.config import ConfigError, load_config


def test_repository_configuration_is_valid() -> None:
    config = load_config()

    assert config.experiment.id == "find-crate-source-cargo-platform-v1"
    assert config.experiment.budget_path == "artifacts/budget.json"
    assert config.conditions["baseline"] == ()


def test_incomplete_configuration_names_the_missing_table(tmp_path: Path) -> None:
    path = tmp_path / "experiment.toml"
    path.write_text("schema-version = 1\n", encoding="utf-8")

    with pytest.raises(ConfigError, match=r"root\.experiment must be a table"):
        load_config(path)


def test_invalid_binary_digest_is_rejected(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "experiment.toml"
    contents = source.read_text(encoding="utf-8").replace(
        'sha256 = "0933b286cf94e1b2504b35ac165ab76b8f822735d53371c56393988c23040d58"',
        'sha256 = "not-a-digest"',
    )
    path = tmp_path / "experiment.toml"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(ConfigError, match=r"agent-binary\.sha256"):
        load_config(path)


def test_binary_cache_file_cannot_escape_the_cache_directory(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "experiment.toml"
    contents = source.read_text(encoding="utf-8").replace(
        'cache-file = "claude-2.1.238-linux-x64"',
        'cache-file = "../claude-code"',
    )
    path = tmp_path / "experiment.toml"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(ConfigError, match=r"agent-binary\.cache-file must be a filename without directories"):
        load_config(path)


def test_non_finite_cost_limit_is_rejected(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "experiment.toml"
    contents = source.read_text(encoding="utf-8").replace("cost-limit-usd = 0.35", "cost-limit-usd = nan")
    path = tmp_path / "experiment.toml"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(ConfigError, match=r"limits\.cost-limit-usd must be a positive number"):
        load_config(path)
