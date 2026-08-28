"""Command-line interface for the disposable evaluation prototype."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from typing import cast

from skill_eval.config import ConfigError, ExperimentConfig, load_config
from skill_eval.environment import asset_status, framework_versions, prerequisites
from skill_eval.execution import execute_phase, prepare_environment, run_controls
from skill_eval.models import PHASE_NAMES, JsonObject, JsonValue, Phase
from skill_eval.planning import BudgetError, budget_summary, build_plan
from skill_eval.reporting import write_report
from skill_eval.results import ResultsError, summarize


def _limits_json(config: ExperimentConfig) -> JsonObject:
    limits = config.limits
    return {
        "message-limit": limits.message_limit,
        "token-limit": limits.token_limit,
        "output-token-limit": limits.output_token_limit,
        "time-limit-seconds": limits.time_limit_seconds,
        "cost-limit-usd": limits.cost_limit_usd,
        "experiment-cost-limit-usd": limits.experiment_cost_limit_usd,
        "max-provider-requests": limits.max_provider_requests,
        "max-tool-calls": limits.max_tool_calls,
    }


def _budget_json(config: ExperimentConfig) -> JsonObject:
    try:
        return budget_summary(config).to_json()
    except BudgetError as error:
        return {"error": str(error)}


def plan_document(config: ExperimentConfig) -> JsonObject:
    """Build the free, machine-readable execution plan."""
    runs: list[JsonValue] = []
    for phase in PHASE_NAMES:
        runs.extend(
            {
                "run_id": run.run_id,
                "phase": run.phase,
                "pair": run.pair,
                "order": run.order,
                "condition": run.condition,
                "skills": list(run.skills),
                "attempt_id": run.attempt_id,
            }
            for run in build_plan(config, phase)
        )
    return {
        "schema_version": config.schema_version,
        "experiment": config.experiment_json(),
        "framework_versions": cast(JsonObject, framework_versions()),
        "model_costs": config.model_costs_json(),
        "limits": _limits_json(config),
        "budget": _budget_json(config),
        "limit_enforcement": cast(
            JsonObject,
            {
                "message-limit": "hard: Inspect sample limit",
                "token-limit": "hard: Inspect sample limit",
                "output-token-limit": "hard: nested Inspect agent limit",
                "time-limit-seconds": "hard: Inspect sample limit",
                "cost-limit-usd": "hard: Inspect sample limit",
                "experiment-cost-limit-usd": "hard: cumulative local reservation ledger",
                "max-provider-requests": "hard: prototype GenerateFilter",
                "max-tool-calls": "observed only: no pinned Inspect SWE guard",
            },
        ),
        "assets": cast(JsonObject, asset_status(config)),
        "prerequisites": cast(JsonObject, prerequisites(config)),
        "external_requirements": cast(
            JsonObject,
            {"api_account_funding": "unverified until a provider request"},
        ),
        "runs": runs,
    }


def _object(document: JsonObject, key: str) -> JsonObject:
    value = document[key]
    if not isinstance(value, dict):
        raise AssertionError(f"plan field {key} is not an object")
    return value


def _array(document: JsonObject, key: str) -> list[JsonValue]:
    value = document[key]
    if not isinstance(value, list):
        raise AssertionError(f"plan field {key} is not an array")
    return value


def _number(document: JsonObject, key: str) -> float:
    value = document[key]
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise AssertionError(f"plan field {key} is not numeric")
    return float(value)


def print_plan(config: ExperimentConfig, *, as_json: bool) -> int:
    """Print the plan and local readiness without making provider requests."""
    document = plan_document(config)
    assets = _object(document, "assets")
    missing_assets = [name for name, exists in assets.items() if exists is not True]
    if as_json:
        print(json.dumps(document, indent=2))
    else:
        experiment = _object(document, "experiment")
        limits = _object(document, "limits")
        versions = _object(document, "framework_versions")
        print(f"Experiment: {experiment['id']}")
        print(f"Agent: {experiment['agent']} {experiment['agent_version']}")
        print(f"Model: {experiment['model']}")
        print("Frameworks: " + ", ".join(f"{name} {package_version}" for name, package_version in versions.items()))
        print(f"Per-run ceiling: ${_number(limits, 'cost-limit-usd'):.2f}")
        print(f"Experiment ceiling: ${_number(limits, 'experiment-cost-limit-usd'):.2f}")
        budget = _object(document, "budget")
        if "error" in budget:
            print(f"Budget ledger: ERROR ({budget['error']})")
        else:
            print(
                f"Budget committed: ${_number(budget, 'committed_usd'):.2f}; "
                f"remaining: ${_number(budget, 'remaining_usd'):.2f}"
            )
        print("\nPlanned runs:")
        for raw_run in _array(document, "runs"):
            if not isinstance(raw_run, dict):
                continue
            raw_skills = raw_run.get("skills")
            skills = [str(skill) for skill in raw_skills] if isinstance(raw_skills, list) else []
            print(
                f"  {raw_run.get('run_id')}: pair={raw_run.get('pair')} order={raw_run.get('order')} "
                f"condition={raw_run.get('condition')} skills={', '.join(skills) or 'none'}"
            )
        print("\nLocal readiness:")
        for name, ready in assets.items():
            print(f"  asset.{name}: {'ready' if ready is True else 'MISSING'}")
        for name, ready in _object(document, "prerequisites").items():
            print(f"  prerequisite.{name}: {'ready' if ready is True else 'unavailable'}")
        print("  API account funding: unverified until a provider request")
        print("\nLimit enforcement:")
        for name, enforcement in _object(document, "limit_enforcement").items():
            print(f"  {name}: {enforcement}")
        print("\nPlanning is free. Smoke and measured commands require --confirm-paid-run.")

    if missing_assets:
        print(f"Missing required assets: {', '.join(missing_assets)}", file=sys.stderr)
        return 2
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments from an injectable sequence."""
    parser = argparse.ArgumentParser(description="Disposable Symposium skill-eval prototype")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan", help="print the free execution plan")
    plan_parser.add_argument("--json", action="store_true", help="emit the plan as JSON")
    subparsers.add_parser(
        "prepare",
        help="perform free local preparation and grader controls",
        description="Perform free local preparation and grader controls.",
    )
    for command in PHASE_NAMES:
        run_parser = subparsers.add_parser(command, help=f"run the paid {command} phase")
        run_parser.add_argument("--confirm-paid-run", action="store_true")
    subparsers.add_parser("controls", help="run free grader controls in Docker")
    subparsers.add_parser("summarize", help="export normalized JSON from existing logs")
    subparsers.add_parser("report", help="render a free Markdown evidence report")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch one prototype command with concise boundary errors."""
    try:
        args = parse_args(argv)
        config = load_config()
        if args.command == "plan":
            return print_plan(config, as_json=bool(args.json))
        if args.command == "prepare":
            return prepare_environment(config)
        if args.command == "controls":
            return run_controls(config)
        if args.command in PHASE_NAMES:
            phase = cast(Phase, args.command)
            return execute_phase(config, phase, confirmed=bool(args.confirm_paid_run))
        if args.command == "summarize":
            return summarize(config)
        if args.command == "report":
            return write_report(config)
        raise AssertionError(f"unhandled command: {args.command}")
    except (BudgetError, ConfigError, ResultsError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as error:
        print(f"error: command failed with exit code {error.returncode}: {error.cmd}", file=sys.stderr)
        return 2
