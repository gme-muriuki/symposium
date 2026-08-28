"""Shared fixtures for offline prototype tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from skill_eval.config import ExperimentConfig, load_config


@pytest.fixture
def config() -> ExperimentConfig:
    """Load the repository's validated experiment configuration."""
    return load_config()


@pytest.fixture
def isolated_config(config: ExperimentConfig, tmp_path: Path) -> ExperimentConfig:
    """Redirect mutable artifacts to one test-owned directory."""
    experiment = replace(
        config.experiment,
        results_path=(tmp_path / "results.json").as_posix(),
        report_path=(tmp_path / "report.md").as_posix(),
        controls_path=(tmp_path / "controls.json").as_posix(),
        budget_path=(tmp_path / "budget.json").as_posix(),
        logs_path=(tmp_path / "logs").as_posix(),
    )
    return replace(config, experiment=experiment)
