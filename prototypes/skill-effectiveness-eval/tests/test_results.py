"""Failure-classification and result-normalization tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from inspect_ai.event import ModelEvent, ToolEvent
from inspect_ai.log import EvalSample
from inspect_ai.model import ModelUsage
from inspect_ai.scorer import Score

from skill_eval.results import classify_failure, normalize_sample


@pytest.mark.parametrize(
    ("sample_error", "model_errors", "expected"),
    [
        (RuntimeError("agent failed"), ["credit balance is too low"], ("unavailable", "billing_error")),
        (
            RuntimeError("agent failed"),
            ["authentication_error: invalid x-api-key"],
            ("unavailable", "authentication_error"),
        ),
        (RuntimeError("agent failed"), ["provider timeout"], ("infrastructure_error", "provider_error")),
    ],
)
def test_failure_classification(
    sample_error: RuntimeError,
    model_errors: list[str],
    expected: tuple[str, str],
) -> None:
    assert classify_failure("error", sample_error, model_errors) == expected


def test_successful_sample_becomes_a_portable_record() -> None:
    model_event = ModelEvent.model_construct(error=None)
    tool_event = ToolEvent.model_construct(id="tool", function="bash", arguments={})
    sample = EvalSample.model_construct(
        metadata={
            "run_id": "smoke-p1-2-symposium",
            "attempt_id": "smoke-test",
            "phase": "smoke",
            "pair": 1,
            "order": 2,
            "condition": "symposium",
        },
        scores={
            "api_notes_scorer": Score(value="C", explanation="exact", metadata={}),
            "symposium_capability_scorer": Score(
                value=1,
                explanation="used",
                metadata={"skill_available": True},
            ),
        },
        events=[model_event, tool_event],
        error=None,
        total_time=12.0,
        working_time=10.0,
        model_usage={"model": ModelUsage(input_tokens=100, total_tokens=100, total_cost=0.01)},
    )

    normalized = normalize_sample("success", sample, Path("sample.eval"))

    assert normalized.status == "passed"
    assert normalized.provider_requests == 1
    assert normalized.tool_calls == 1
    assert "messages" not in normalized.to_json()


def test_normalized_error_omits_traceback_and_authentication_material() -> None:
    class InspectError:
        message = "agent failed"

        def model_dump(self, *, mode: str) -> dict[str, str]:
            assert mode == "json"
            return {
                "message": self.message,
                "traceback": "ANTHROPIC_AUTH_TOKEN=must-not-leak",
            }

    sample = EvalSample.model_construct(
        metadata={},
        scores={},
        events=[],
        error=InspectError(),
        total_time=1.0,
        working_time=1.0,
        model_usage={},
    )

    normalized = normalize_sample("error", sample, Path("sample.eval"))

    assert normalized.error == {"message": "agent failed"}
    assert "must-not-leak" not in str(normalized.to_json())
