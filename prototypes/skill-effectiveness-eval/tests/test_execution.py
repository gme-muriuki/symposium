"""Paid-attempt orchestration tests."""

from __future__ import annotations

import pytest
from inspect_ai.event import ModelEvent
from inspect_ai.log import EvalLog, EvalSample

from skill_eval.config import ExperimentConfig
from skill_eval.execution import run_planned_attempt
from skill_eval.models import PlannedRun
from skill_eval.planning import build_plan, load_budget, with_attempt


def _billing_failure_log() -> EvalLog:
    event = ModelEvent.model_construct(error="credit balance is too low")
    sample = EvalSample.model_construct(
        events=[event],
        error=RuntimeError("agent failed"),
        model_usage={},
    )
    return EvalLog.model_construct(status="error", samples=[sample])


def test_terminal_failure_stops_before_the_next_condition(isolated_config: ExperimentConfig) -> None:
    attempt_id = "smoke-test"
    runs = with_attempt(build_plan(isolated_config, "smoke"), attempt_id)
    called: list[str] = []

    def evaluate(run: PlannedRun) -> list[EvalLog]:
        called.append(run.run_id)
        return [_billing_failure_log()]

    failure = run_planned_attempt(isolated_config, runs, attempt_id, evaluate)

    assert failure == ("unavailable", "billing_error")
    assert called == [runs[0].run_id]
    assert [entry.state for entry in load_budget(isolated_config)] == ["completed", "cancelled"]


def test_unexpected_interruption_leaves_conservative_reservations(isolated_config: ExperimentConfig) -> None:
    attempt_id = "smoke-interrupted"
    runs = with_attempt(build_plan(isolated_config, "smoke"), attempt_id)

    def interrupt(run: PlannedRun) -> list[EvalLog]:
        raise RuntimeError(f"process interrupted during {run.run_id}")

    with pytest.raises(RuntimeError, match="process interrupted"):
        run_planned_attempt(isolated_config, runs, attempt_id, interrupt)

    assert [entry.state for entry in load_budget(isolated_config)] == ["reserved", "reserved"]
