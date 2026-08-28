from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


PROTOTYPE = Path(__file__).resolve().parents[1]


class CommandLineTests(unittest.TestCase):
    def test_prepare_is_advertised_as_free(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(PROTOTYPE / "run.py"), "prepare", "--help"],
            cwd=PROTOTYPE,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("free", completed.stdout.casefold())

    def test_plan_succeeds_without_a_key_and_marks_funding_unverified(self) -> None:
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

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("api account funding: unverified", completed.stdout.casefold())


if __name__ == "__main__":
    unittest.main()
