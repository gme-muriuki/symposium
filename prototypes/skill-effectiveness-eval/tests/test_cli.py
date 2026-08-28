"""Subprocess-level CLI compatibility tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROTOTYPE = Path(__file__).resolve().parents[1]


def test_prepare_is_advertised_as_free() -> None:
    completed = subprocess.run(
        [sys.executable, str(PROTOTYPE / "run.py"), "prepare", "--help"],
        cwd=PROTOTYPE,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "free" in completed.stdout.casefold()


def test_plan_succeeds_without_a_key_and_marks_funding_unverified() -> None:
    environment = os.environ.copy()
    environment.pop("ANTHROPIC_API_KEY", None)
    completed = subprocess.run(
        [sys.executable, str(PROTOTYPE / "run.py"), "plan"],
        cwd=PROTOTYPE,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "api account funding: unverified" in completed.stdout.casefold()
