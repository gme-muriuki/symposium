from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from types import SimpleNamespace

PROTOTYPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROTOTYPE))

import run


class PlanningTests(unittest.TestCase):
    def test_pair_order_is_deterministic_for_the_recorded_seed(self) -> None:
        config = {
            "experiment": {"seed": 824315},
            "phases": {"smoke": {"pairs": 1}},
            "conditions": {
                "baseline": {"skills": []},
                "symposium": {"skills": ["find-crate-source"]},
            },
        }

        first = run.build_plan(config, "smoke")
        second = run.build_plan(config, "smoke")

        self.assertEqual(first, second)
        self.assertEqual([item.condition for item in first], ["baseline", "symposium"])


class FailureClassificationTests(unittest.TestCase):
    def test_low_provider_credit_is_unavailable_billing(self) -> None:
        event = type("ModelEvent", (), {})()
        event.error = "Your credit balance is too low to access the Anthropic API"
        sample = SimpleNamespace(
            error=RuntimeError("agent exited after API error"),
            events=[event],
        )

        classification = run.classify_sample_failure("error", sample)

        self.assertEqual(classification, ("unavailable", "billing_error"))

    def test_invalid_provider_key_is_unavailable_authentication(self) -> None:
        event = type("ModelEvent", (), {})()
        event.error = "authentication_error: invalid x-api-key"
        sample = SimpleNamespace(error=RuntimeError("agent API error"), events=[event])

        classification = run.classify_sample_failure("error", sample)

        self.assertEqual(classification, ("unavailable", "authentication_error"))

    def test_other_provider_failures_are_infrastructure_errors(self) -> None:
        event = type("ModelEvent", (), {})()
        event.error = "provider connection timed out"
        sample = SimpleNamespace(error=RuntimeError("agent API error"), events=[event])

        classification = run.classify_sample_failure("error", sample)

        self.assertEqual(classification, ("infrastructure_error", "provider_error"))

    def test_terminal_failure_stops_the_phase(self) -> None:
        event = type("ModelEvent", (), {})()
        event.error = "Your credit balance is too low"
        sample = SimpleNamespace(error=RuntimeError("agent API error"), events=[event])
        log = SimpleNamespace(status="error", samples=[sample])

        failure = run.first_terminal_failure([log])

        self.assertEqual(failure, ("unavailable", "billing_error"))


class ResultNormalizationTests(unittest.TestCase):
    def test_successful_sample_becomes_a_portable_passed_record(self) -> None:
        model_event = type("ModelEvent", (), {})()
        model_event.error = None
        tool_event = type("ToolEvent", (), {})()
        score = SimpleNamespace(
            value="C",
            explanation="exact answer",
            metadata={"observed": "completed notes"},
        )
        capability = SimpleNamespace(
            value=1,
            explanation="invocation observed",
            metadata={"skill_available": True, "invocations": ["cargo agents"]},
        )
        sample = SimpleNamespace(
            metadata={
                "run_id": "smoke-p1-2-symposium",
                "attempt_id": "smoke-test",
                "phase": "smoke",
                "pair": 1,
                "order": 2,
                "condition": "symposium",
            },
            scores={
                "api_notes_scorer": score,
                "symposium_capability_scorer": capability,
            },
            events=[model_event, tool_event],
            error=None,
            total_time=12.0,
            working_time=10.0,
            model_usage={"anthropic/claude-sonnet-5": {"input_tokens": 100}},
        )

        normalized = run.normalize_sample("success", sample, Path("sample.eval"))

        self.assertEqual(normalized["status"], "passed")
        self.assertEqual(normalized["provider_requests"], 1)
        self.assertEqual(normalized["tool_calls"], 1)
        self.assertEqual(
            normalized["scores"]["symposium_capability_scorer"]["value"], 1
        )
        self.assertNotIn("messages", normalized)

    def test_normalized_error_omits_traceback_and_authentication_material(self) -> None:
        class InspectError:
            message = "agent failed"

            def model_dump(self, *, mode: str) -> dict[str, str]:
                self.assert_mode = mode
                return {
                    "message": self.message,
                    "traceback": "ANTHROPIC_AUTH_TOKEN=must-not-leak",
                }

        sample = SimpleNamespace(
            metadata={},
            scores={},
            events=[],
            error=InspectError(),
            total_time=1.0,
            working_time=1.0,
            model_usage={},
        )

        normalized = run.normalize_sample("error", sample, Path("sample.eval"))

        self.assertEqual(normalized["error"], {"message": "agent failed"})
        self.assertNotIn("must-not-leak", str(normalized))


class EvidenceReportTests(unittest.TestCase):
    def test_completed_smoke_pair_renders_gates_deltas_and_capability_use(self) -> None:
        def result(
            condition: str,
            *,
            tokens: int,
            seconds: float,
            invoked: int,
        ) -> dict[str, object]:
            return {
                "run_id": f"smoke-p1-{condition}",
                "attempt_id": "smoke-20260825T150000Z",
                "phase": "smoke",
                "pair": 1,
                "condition": condition,
                "status": "passed",
                "error_kind": None,
                "total_time": seconds,
                "model_usage": {
                    "anthropic/claude-sonnet-5": {
                        "total_tokens": tokens,
                        "total_cost": 0.01,
                    }
                },
                "provider_requests": 2,
                "scores": {
                    "api_notes_scorer": {"value": "C", "metadata": {}},
                    "symposium_capability_scorer": {
                        "value": invoked,
                        "metadata": {
                            "skill_available": condition == "symposium",
                            "invocations": ["cargo agents"] if invoked else [],
                        },
                    },
                },
                "messages": ["must not appear in report"],
            }

        document = {
            "experiment_id": "example",
            "controls": {"passed": True},
            "runs": [
                result("baseline", tokens=120, seconds=20.0, invoked=0),
                result("symposium", tokens=80, seconds=15.0, invoked=1),
            ],
        }

        report = run.render_report(document)

        self.assertIn("Smoke readiness: PASS", report)
        self.assertIn("| smoke | 1 | passed | passed | +0 | -40 | -5.0 | yes |", report)
        self.assertNotIn("must not appear in report", report)

    def test_missing_control_evidence_fails_the_smoke_gate(self) -> None:
        report = run.render_report({"experiment_id": "example", "runs": []})

        self.assertIn("| Grader controls passed | FAIL |", report)


class AgentBinaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_binary = os.environ.pop("CLAUDE_CODE_BINARY_PATH", None)

    def tearDown(self) -> None:
        os.environ.pop("CLAUDE_CODE_BINARY_PATH", None)
        if self.previous_binary is not None:
            os.environ["CLAUDE_CODE_BINARY_PATH"] = self.previous_binary

    def test_verified_binary_is_exported_from_an_isolated_cache(self) -> None:
        contents = b"pinned claude code"
        config = {
            "agent-binary": {
                "cache-file": "claude-test-linux-x64",
                "size": len(contents),
                "sha256": hashlib.sha256(contents).hexdigest(),
            }
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_root = Path(temporary_directory)
            binary = cache_root / "claude-code-downloads" / "claude-test-linux-x64"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(contents)

            ready = run.configure_agent_binary(config, cache_root=cache_root)

            self.assertTrue(ready)
            self.assertEqual(os.environ["CLAUDE_CODE_BINARY_PATH"], str(binary))

    def test_missing_binary_is_populated_by_the_docker_downloader(self) -> None:
        contents = b"downloaded claude code"
        config = {
            "agent-binary": {
                "cache-file": "claude-test-linux-x64",
                "size": len(contents),
                "sha256": hashlib.sha256(contents).hexdigest(),
            }
        }
        commands: list[list[str]] = []

        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_root = Path(temporary_directory)
            binary = run.agent_binary_path(config, cache_root=cache_root)

            def docker(command: list[str], **_: object) -> CompletedProcess[str]:
                commands.append(command)
                if command[1] == "run":
                    binary.parent.mkdir(parents=True, exist_ok=True)
                    binary.write_bytes(contents)
                return CompletedProcess(command, 0)

            run.cache_agent_binary(
                config,
                cache_root=cache_root,
                command_runner=docker,
            )

        self.assertEqual(commands[0][0:4], ["docker", "build", "--target", "downloader"])
        self.assertEqual(commands[1][0:3], ["docker", "run", "--rm"])


class GraderControlTests(unittest.TestCase):
    def test_control_fingerprint_changes_with_graded_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            first = Path(temporary_directory) / "fixture.md"
            second = Path(temporary_directory) / "grader.md"
            first.write_text("placeholder", encoding="utf-8")
            second.write_text("answer", encoding="utf-8")

            before = run.file_fingerprint([first, second])
            first.write_text("changed", encoding="utf-8")
            after = run.file_fingerprint([first, second])

        self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()
