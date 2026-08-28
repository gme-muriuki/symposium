"""Free controls and guarded paid-phase orchestration."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from inspect_ai import Task
from inspect_ai.log import EvalLog
from inspect_ai.model import ModelCost

from skill_eval.config import ExperimentConfig
from skill_eval.environment import (
    cache_agent_binary,
    control_fingerprint,
    discover_docker,
    framework_versions,
    prerequisites,
    runtime_environment,
    verified_agent_binary,
    working_directory,
)
from skill_eval.models import JsonObject, Phase, PlannedRun
from skill_eval.planning import (
    build_plan,
    cancel_reservations,
    complete_run,
    reserve_attempt,
    with_attempt,
)
from skill_eval.results import eval_logs_cost, first_terminal_failure, summarize
from skill_eval.tasks import build_control_task, build_task

type PlannedEvaluator = Callable[[PlannedRun], list[EvalLog]]


def model_cost_config(config: ExperimentConfig) -> dict[str, ModelCost]:
    """Build the model-price objects expected by Inspect."""
    return {
        model: ModelCost(
            input=price.input,
            output=price.output,
            input_cache_write=price.input_cache_write,
            input_cache_read=price.input_cache_read,
        )
        for model, price in config.model_costs.items()
    }


def require_paid_confirmation(config: ExperimentConfig, phase: Phase, *, confirmed: bool) -> None:
    """Refuse provider work unless confirmation and local prerequisites are current."""
    if not confirmed:
        raise SystemExit(f"Refusing paid {phase} run without --confirm-paid-run")
    missing = [name for name, ready in prerequisites(config).items() if not ready]
    if missing:
        raise SystemExit(f"Run unavailable; missing prerequisite(s): {', '.join(missing)}")


def run_planned_attempt(
    config: ExperimentConfig,
    runs: Sequence[PlannedRun],
    attempt_id: str,
    evaluator: PlannedEvaluator,
) -> tuple[str, str] | None:
    """Execute a reserved attempt and stop after its first terminal failure."""
    planned_runs = list(runs)
    reserve_attempt(config, planned_runs, attempt_id)
    for planned_run in planned_runs:
        logs = evaluator(planned_run)
        complete_run(config, attempt_id, planned_run.run_id, eval_logs_cost(logs))
        if failure := first_terminal_failure(logs):
            cancel_reservations(config, attempt_id)
            return failure
    return None


def _inspect_eval(task: Task, **kwargs: Any) -> list[EvalLog]:
    from inspect_ai import eval as inspect_eval

    return cast(list[EvalLog], inspect_eval(task, **kwargs))


def execute_phase(config: ExperimentConfig, phase: Phase, *, confirmed: bool) -> int:
    """Run one paid phase through Inspect with cumulative budget protection."""
    require_paid_confirmation(config, phase, confirmed=confirmed)
    docker = discover_docker()
    agent_binary = verified_agent_binary(config)
    if docker is None or agent_binary is None:
        raise SystemExit("Run unavailable; Docker or the verified agent binary disappeared")

    log_root = config.resolve(config.experiment.logs_path)
    log_root.mkdir(parents=True, exist_ok=True)
    attempt_id = f"{phase}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}"
    runs = with_attempt(build_plan(config, phase), attempt_id)

    def evaluate(planned_run: PlannedRun) -> list[EvalLog]:
        run_log_dir = log_root / attempt_id / planned_run.run_id
        run_log_dir.mkdir(parents=True, exist_ok=True)
        print(f"Starting {planned_run.run_id}", flush=True)
        return _inspect_eval(
            build_task(config, planned_run),
            model=config.experiment.model,
            model_cost_config=model_cost_config(config),
            log_dir=str(run_log_dir),
            log_format="eval",
            max_connections=1,
            max_retries=0,
        )

    with runtime_environment(docker, agent_binary), working_directory(config.root):
        failure = run_planned_attempt(config, runs, attempt_id, evaluate)
    if failure is not None:
        status, error_kind = failure
        print(f"Stopping {attempt_id}: {status} ({error_kind}).", file=sys.stderr)
        summarize(config)
        return 1
    return summarize(config)


def run_controls(
    config: ExperimentConfig,
    *,
    docker: Path | None = None,
    agent_binary: Path | None = None,
) -> int:
    """Run untouched and known-good scorer controls in fresh sandboxes."""
    from inspect_ai.scorer import CORRECT, INCORRECT

    docker = docker or discover_docker()
    if docker is None:
        raise SystemExit("Control run unavailable; docker is not on PATH")
    agent_binary = agent_binary or verified_agent_binary(config)
    if agent_binary is None:
        raise SystemExit("Control run unavailable; run prepare to cache the pinned agent binary")

    log_dir = config.resolve(config.experiment.logs_path) / "controls"
    log_dir.mkdir(parents=True, exist_ok=True)
    observed: dict[str, object] = {}
    with runtime_environment(docker, agent_binary), working_directory(config.root):
        for known_good in (False, True):
            logs = _inspect_eval(
                build_control_task(config, known_good=known_good),
                model="mockllm/model",
                log_dir=str(log_dir),
                log_format="eval",
                max_connections=1,
                max_retries=0,
            )
            for log in logs:
                for sample in log.samples or []:
                    score = (sample.scores or {}).get("api_notes_scorer")
                    observed[str(sample.id)] = score.value if score is not None else None

    expected = {"control-untouched": INCORRECT, "control-known-good": CORRECT}
    for control_id, expected_value in expected.items():
        actual = observed.get(control_id)
        outcome = "PASS" if actual == expected_value else "FAIL"
        print(f"{control_id}: {actual!r} (expected {expected_value!r}) [{outcome}]")

    passed = observed == expected
    control_path = config.resolve(config.experiment.controls_path)
    control_path.parent.mkdir(parents=True, exist_ok=True)
    document: JsonObject = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "fingerprint": control_fingerprint(config),
        "passed": passed,
        "observed": cast(JsonObject, {name: str(value) for name, value in observed.items()}),
        "expected": cast(JsonObject, {name: str(value) for name, value in expected.items()}),
        "framework_versions": cast(JsonObject, framework_versions()),
    }
    control_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    if not passed:
        print("Grader controls failed; do not run a paid experiment.", file=sys.stderr)
        return 1
    print("Grader controls passed; the untouched and known-good states are distinguished.")
    return 0


def prepare_environment(config: ExperimentConfig) -> int:
    """Prepare the pinned binary and refresh free grader controls."""
    docker = discover_docker()
    if docker is None:
        raise SystemExit("Preparation unavailable; docker is not on PATH")
    binary = cache_agent_binary(config, docker=docker)
    print(f"Verified pinned Claude Code binary at {binary}")
    return run_controls(config, docker=docker, agent_binary=binary)
