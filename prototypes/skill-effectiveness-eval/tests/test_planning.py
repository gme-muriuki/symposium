"""Pair scheduling and cumulative-budget tests."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from skill_eval.config import ExperimentConfig
from skill_eval.planning import (
    BudgetError,
    budget_summary,
    build_plan,
    cancel_reservations,
    complete_run,
    load_budget,
    reserve_attempt,
)


def test_pair_order_is_deterministic(config: ExperimentConfig) -> None:
    first = build_plan(config, "smoke")
    second = build_plan(config, "smoke")

    assert first == second
    assert [run.condition for run in first] == ["baseline", "symposium"]


def test_completed_and_cancelled_reservations_release_unused_budget(isolated_config: ExperimentConfig) -> None:
    runs = build_plan(isolated_config, "smoke")
    reserve_attempt(isolated_config, runs, "smoke-test")

    complete_run(isolated_config, "smoke-test", runs[0].run_id, 0.12)
    cancel_reservations(isolated_config, "smoke-test")

    summary = budget_summary(isolated_config)
    assert summary.observed_usd == pytest.approx(0.12)
    assert summary.reserved_usd == 0
    assert [entry.state for entry in load_budget(isolated_config)] == ["completed", "cancelled"]


def test_cumulative_spend_blocks_an_over_budget_retry(isolated_config: ExperimentConfig) -> None:
    config = replace(
        isolated_config,
        limits=replace(isolated_config.limits, experiment_cost_limit_usd=1.0),
    )
    runs = build_plan(config, "smoke")
    reserve_attempt(config, runs, "first")
    complete_run(config, "first", runs[0].run_id, 0.30)
    complete_run(config, "first", runs[1].run_id, 0.30)

    with pytest.raises(BudgetError, match=r"committed \$0\.60 plus requested \$0\.70"):
        reserve_attempt(config, runs, "retry")


def test_normalized_result_reconciles_an_interrupted_reservation(isolated_config: ExperimentConfig) -> None:
    runs = build_plan(isolated_config, "smoke")
    reserve_attempt(isolated_config, runs, "interrupted")
    results_path = isolated_config.resolve(isolated_config.experiment.results_path)
    results_path.write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "attempt_id": "interrupted",
                        "run_id": runs[0].run_id,
                        "phase": "smoke",
                        "model_usage": {"model": {"total_cost": 0.08}},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    entries = load_budget(isolated_config)

    assert entries[0].state == "completed"
    assert entries[0].observed_usd == pytest.approx(0.08)
    assert entries[1].state == "reserved"
