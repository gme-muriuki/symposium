"""Process-state and local-integrity tests."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from skill_eval.config import ExperimentConfig
from skill_eval.environment import (
    agent_binary_path,
    cache_agent_binary,
    control_result,
    temporary_environment,
    working_directory,
)


def test_temporary_environment_restores_present_and_absent_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKILL_EVAL_PRESENT", "before")
    monkeypatch.delenv("SKILL_EVAL_ABSENT", raising=False)

    with temporary_environment({"SKILL_EVAL_PRESENT": "during", "SKILL_EVAL_ABSENT": "during"}):
        assert os.environ["SKILL_EVAL_PRESENT"] == "during"
        assert os.environ["SKILL_EVAL_ABSENT"] == "during"

    assert os.environ["SKILL_EVAL_PRESENT"] == "before"
    assert "SKILL_EVAL_ABSENT" not in os.environ


def test_working_directory_is_restored_after_failure(tmp_path: Path) -> None:
    original = Path.cwd()

    with pytest.raises(RuntimeError, match="stop"), working_directory(tmp_path):
        assert Path.cwd() == tmp_path
        raise RuntimeError("stop")

    assert Path.cwd() == original


def test_downloader_receives_pin_from_config(config: ExperimentConfig, tmp_path: Path) -> None:
    contents = b"downloaded claude code"
    config = replace(
        config,
        agent_binary=replace(
            config.agent_binary,
            cache_file="claude-test-linux-x64",
            size=len(contents),
            sha256=hashlib.sha256(contents).hexdigest(),
        ),
    )
    commands: list[list[str]] = []
    binary = agent_binary_path(config, cache_root=tmp_path)

    def docker(command: Sequence[str], *, cwd: Path, check: bool) -> CompletedProcess[bytes]:
        commands.append(list(command))
        if command[1] == "run":
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_bytes(contents)
        return CompletedProcess(command, 0)

    result = cache_agent_binary(
        config,
        docker=Path("docker"),
        cache_root=tmp_path,
        command_runner=docker,
    )

    assert result == binary
    assert commands[1][-4:] == [
        config.experiment.agent_version,
        config.agent_binary.cache_file,
        str(config.agent_binary.size),
        config.agent_binary.sha256,
    ]


def test_malformed_control_json_fails_closed(isolated_config: ExperimentConfig) -> None:
    path = isolated_config.resolve(isolated_config.experiment.controls_path)
    path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    evidence = control_result(isolated_config)

    assert not evidence.passed
    assert evidence.reason == "malformed"
