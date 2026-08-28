from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "experiment.toml"
CONDITION_NAMES = ("baseline", "symposium")


@dataclass(frozen=True)
class PlannedRun:
    run_id: str
    phase: str
    pair: int
    order: int
    condition: str
    skills: list[str]
    attempt_id: str | None = None


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("rb") as stream:
        return tomllib.load(stream)


def resolve(configured_path: str) -> Path:
    return (ROOT / configured_path).resolve()


def build_plan(config: dict[str, Any], phase: str) -> list[PlannedRun]:
    pair_count = int(config["phases"][phase]["pairs"])
    seed = int(config["experiment"]["seed"])
    planned: list[PlannedRun] = []

    for pair in range(1, pair_count + 1):
        conditions = list(CONDITION_NAMES)
        random.Random(f"{seed}:{phase}:{pair}").shuffle(conditions)
        for order, condition in enumerate(conditions, start=1):
            skills = list(config["conditions"][condition]["skills"])
            planned.append(
                PlannedRun(
                    run_id=f"{phase}-p{pair}-{order}-{condition}",
                    phase=phase,
                    pair=pair,
                    order=order,
                    condition=condition,
                    skills=skills,
                )
            )
    return planned


def asset_status(config: dict[str, Any]) -> dict[str, bool]:
    experiment = config["experiment"]
    assets = {
        "fixture": resolve(experiment["fixture-path"]),
        "grader": resolve(experiment["grader-path"]),
        "skill": resolve(experiment["skill-path"]),
        "sandbox_config": resolve(experiment["sandbox-config"]),
        "dockerfile": ROOT / "Dockerfile",
        "cargo_shim": ROOT / "bin" / "cargo",
        "cargo_agents_shim": ROOT / "bin" / "cargo-agents",
    }
    return {name: path.exists() for name, path in assets.items()}


def file_fingerprint(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def control_fingerprint(config: dict[str, Any]) -> str:
    experiment = config["experiment"]
    fixture = resolve(experiment["fixture-path"])
    return file_fingerprint(
        [
            fixture / "Cargo.toml",
            fixture / "API_NOTES.md",
            resolve(experiment["grader-path"]),
            ROOT / "run.py",
            ROOT / "eval_task.py",
            ROOT / "experiment.toml",
            ROOT / "Dockerfile",
            resolve(experiment["sandbox-config"]),
            ROOT / "bin" / "cargo",
            ROOT / "bin" / "cargo-agents",
            ROOT / "pyproject.toml",
            ROOT / "uv.lock",
        ]
    )


def control_result(config: dict[str, Any]) -> dict[str, Any]:
    path = resolve(config["experiment"]["controls-path"])
    if not path.exists():
        return {"passed": False, "reason": "missing"}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"passed": False, "reason": "unreadable"}
    try:
        current_fingerprint = control_fingerprint(config)
    except OSError:
        return {"passed": False, "reason": "missing inputs"}
    if document.get("fingerprint") != current_fingerprint:
        return {"passed": False, "reason": "stale"}
    return document


def configure_docker_cli() -> bool:
    docker_available = shutil.which("docker") is not None

    if not docker_available:
        candidates = []
        if local_app_data := os.environ.get("LOCALAPPDATA"):
            candidates.append(
                Path(local_app_data)
                / "Programs"
                / "DockerDesktop"
                / "resources"
                / "bin"
                / "docker.exe"
            )
        if program_files := os.environ.get("ProgramFiles"):
            candidates.append(
                Path(program_files)
                / "Docker"
                / "Docker"
                / "resources"
                / "bin"
                / "docker.exe"
            )

        for candidate in candidates:
            try:
                exists = candidate.is_file()
            except OSError:
                exists = False
            if exists:
                os.environ["PATH"] = (
                    f"{candidate.parent}{os.pathsep}{os.environ.get('PATH', '')}"
                )
                docker_available = True
                break

    if docker_available and os.name == "nt":
        os.environ.setdefault("COMPOSE_BAKE", "false")
    return docker_available


def agent_binary_path(
    config: dict[str, Any],
    *,
    cache_root: Path | None = None,
) -> Path:
    if cache_root is None:
        from platformdirs import user_cache_path

        cache_root = user_cache_path("inspect_swe")
    binary = config["agent-binary"]
    return cache_root / "claude-code-downloads" / binary["cache-file"]


def configure_agent_binary(
    config: dict[str, Any],
    *,
    cache_root: Path | None = None,
) -> bool:
    binary = config["agent-binary"]
    path = agent_binary_path(config, cache_root=cache_root)
    try:
        if path.stat().st_size != int(binary["size"]):
            return False
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError:
        return False
    if digest != binary["sha256"]:
        return False
    os.environ["CLAUDE_CODE_BINARY_PATH"] = str(path)
    return True


def cache_agent_binary(
    config: dict[str, Any],
    *,
    cache_root: Path | None = None,
    command_runner: Any = subprocess.run,
) -> None:
    if configure_agent_binary(config, cache_root=cache_root):
        return

    path = agent_binary_path(config, cache_root=cache_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    image = "symposium-skill-effectiveness-downloader:local"
    command_runner(
        [
            "docker",
            "build",
            "--target",
            "downloader",
            "--tag",
            image,
            "--file",
            str(ROOT / "Dockerfile"),
            str(ROOT),
        ],
        cwd=ROOT,
        check=True,
    )
    command_runner(
        [
            "docker",
            "run",
            "--rm",
            "--mount",
            f"type=bind,source={path.parent},target=/cache",
            image,
        ],
        cwd=ROOT,
        check=True,
    )
    if not configure_agent_binary(config, cache_root=cache_root):
        raise RuntimeError("Downloaded Claude Code binary failed size or SHA-256 check")


def prepare_environment(config: dict[str, Any]) -> int:
    if not configure_docker_cli():
        raise SystemExit("Preparation unavailable; docker is not on PATH")
    cache_agent_binary(config)
    path = agent_binary_path(config)
    print(f"Verified pinned Claude Code binary at {path}")
    return run_controls(config)


def prerequisites(config: dict[str, Any]) -> dict[str, bool]:
    return {
        "docker": configure_docker_cli(),
        "agent_binary": configure_agent_binary(config),
        "anthropic_api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "grader_controls": control_result(config).get("passed") is True,
    }


def framework_versions() -> dict[str, str]:
    versions = {}
    for package in ("inspect-ai", "inspect-swe"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = "unavailable"
    return versions


def model_cost_config(config: dict[str, Any]) -> dict[str, Any]:
    from inspect_ai.model import ModelCost

    return {
        model: ModelCost(**prices)
        for model, prices in config["model-costs"].items()
    }


def plan_document(config: dict[str, Any]) -> dict[str, Any]:
    runs = [
        asdict(run)
        for phase in ("smoke", "measured")
        for run in build_plan(config, phase)
    ]
    return {
        "schema_version": config["schema-version"],
        "experiment": config["experiment"],
        "framework_versions": framework_versions(),
        "model_costs": config["model-costs"],
        "limits": config["limits"],
        "limit_enforcement": {
            "message-limit": "hard: Inspect sample limit",
            "token-limit": "hard: Inspect sample limit",
            "output-token-limit": "hard: nested Inspect agent limit",
            "time-limit-seconds": "hard: Inspect sample limit",
            "cost-limit-usd": "hard: Inspect sample limit",
            "max-provider-requests": "hard: prototype GenerateFilter",
            "max-tool-calls": "observed only: no pinned Inspect SWE guard",
        },
        "assets": asset_status(config),
        "prerequisites": prerequisites(config),
        "external_requirements": {
            "api_account_funding": "unverified until a provider request",
        },
        "runs": runs,
    }


def print_plan(config: dict[str, Any], *, as_json: bool) -> int:
    document = plan_document(config)
    missing_assets = [name for name, exists in document["assets"].items() if not exists]

    if as_json:
        print(json.dumps(document, indent=2))
    else:
        experiment = document["experiment"]
        limits = document["limits"]
        print(f"Experiment: {experiment['id']}")
        print(f"Agent: {experiment['agent']} {experiment['agent-version']}")
        print(f"Model: {experiment['model']}")
        print(
            "Frameworks: "
            + ", ".join(
                f"{name} {package_version}"
                for name, package_version in document["framework_versions"].items()
            )
        )
        print(f"Per-run ceiling: ${limits['cost-limit-usd']:.2f}")
        print(f"Experiment ceiling: ${limits['experiment-cost-limit-usd']:.2f}")
        print("\nPlanned runs:")
        for run in document["runs"]:
            skill_label = ", ".join(run["skills"]) or "none"
            print(
                f"  {run['run_id']}: pair={run['pair']} order={run['order']} "
                f"condition={run['condition']} skills={skill_label}"
            )
        print("\nLocal readiness:")
        for name, ready in document["assets"].items():
            print(f"  asset.{name}: {'ready' if ready else 'MISSING'}")
        for name, ready in document["prerequisites"].items():
            print(f"  prerequisite.{name}: {'ready' if ready else 'unavailable'}")
        print("  API account funding: unverified until a provider request")
        print("\nLimit enforcement:")
        for name, enforcement in document["limit_enforcement"].items():
            print(f"  {name}: {enforcement}")
        print("\nPlanning is free. Smoke and measured commands require --confirm-paid-run.")

    if missing_assets:
        print(f"Missing required assets: {', '.join(missing_assets)}", file=sys.stderr)
        return 2
    return 0


def require_paid_confirmation(
    args: argparse.Namespace,
    config: dict[str, Any],
    phase: str,
) -> None:
    if not args.confirm_paid_run:
        raise SystemExit(f"Refusing paid {phase} run without --confirm-paid-run")

    missing = [name for name, ready in prerequisites(config).items() if not ready]
    if missing:
        raise SystemExit(f"Run unavailable; missing prerequisite(s): {', '.join(missing)}")

    runs = build_plan(config, phase)
    limits = config["limits"]
    declared_maximum = len(runs) * float(limits["cost-limit-usd"])
    experiment_limit = float(limits["experiment-cost-limit-usd"])
    if declared_maximum > experiment_limit:
        raise SystemExit(
            f"Declared {phase} maximum ${declared_maximum:.2f} exceeds "
            f"experiment ceiling ${experiment_limit:.2f}"
        )


def execute_phase(args: argparse.Namespace, config: dict[str, Any], phase: str) -> int:
    require_paid_confirmation(args, config, phase)

    from inspect_ai import eval as inspect_eval

    from eval_task import build_task

    log_root = resolve(config["experiment"]["logs-path"])
    log_root.mkdir(parents=True, exist_ok=True)
    os.chdir(ROOT)
    attempt_id = f"{phase}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"

    for planned_run in build_plan(config, phase):
        planned_run = replace(planned_run, attempt_id=attempt_id)
        run_log_dir = log_root / attempt_id / planned_run.run_id
        run_log_dir.mkdir(parents=True, exist_ok=True)
        print(f"Starting {planned_run.run_id}", flush=True)
        logs = inspect_eval(
            build_task(config, planned_run),
            model=config["experiment"]["model"],
            model_cost_config=model_cost_config(config),
            log_dir=str(run_log_dir),
            log_format="eval",
            max_connections=1,
            max_retries=0,
        )
        if failure := first_terminal_failure(logs):
            status, error_kind = failure
            print(
                f"Stopping {attempt_id} after {planned_run.run_id}: "
                f"{status} ({error_kind}).",
                file=sys.stderr,
            )
            summarize(config)
            return 1

    return summarize(config)


def run_controls(config: dict[str, Any]) -> int:
    if not prerequisites(config)["docker"]:
        raise SystemExit("Control run unavailable; docker is not on PATH")

    from inspect_ai import eval as inspect_eval
    from inspect_ai.scorer import CORRECT, INCORRECT

    from eval_task import build_control_task

    log_dir = resolve(config["experiment"]["logs-path"]) / "controls"
    log_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(ROOT)

    observed: dict[str, Any] = {}
    for known_good in (False, True):
        logs = inspect_eval(
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
                observed[sample.id] = score.value if score is not None else None

    expected = {
        "control-untouched": INCORRECT,
        "control-known-good": CORRECT,
    }
    for control_id, expected_value in expected.items():
        actual = observed.get(control_id)
        outcome = "PASS" if actual == expected_value else "FAIL"
        print(f"{control_id}: {actual!r} (expected {expected_value!r}) [{outcome}]")

    passed = observed == expected
    control_path = resolve(config["experiment"]["controls-path"])
    control_path.parent.mkdir(parents=True, exist_ok=True)
    control_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": datetime.now(UTC).isoformat(),
                "fingerprint": control_fingerprint(config),
                "passed": passed,
                "observed": observed,
                "expected": expected,
                "framework_versions": framework_versions(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    if not passed:
        print("Grader controls failed; do not run a paid experiment.", file=sys.stderr)
        return 1
    print("Grader controls passed; the untouched and known-good states are distinguished.")
    return 0


def model_dump(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def error_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, BaseException):
        return str(value)
    if message := getattr(value, "message", None):
        return str(message)
    return json.dumps(model_dump(value), sort_keys=True)


def normalized_error(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    dumped = model_dump(value)
    if isinstance(dumped, dict) and dumped.get("message"):
        return {"message": str(dumped["message"])}
    return {"message": error_text(value)}


def classify_sample_failure(inspect_status: str, sample: Any) -> tuple[str, str] | None:
    event_errors = [
        error_text(getattr(event, "error", None))
        for event in sample.events
        if type(event).__name__ == "ModelEvent" and getattr(event, "error", None)
    ]
    failed = sample.error is not None or inspect_status == "error"
    if not failed:
        return None

    combined_error = "\n".join(
        [error_text(sample.error), *event_errors]
    ).casefold()
    if any(
        marker in combined_error
        for marker in (
            "credit balance is too low",
            "insufficient credit",
            "billing_error",
        )
    ):
        return "unavailable", "billing_error"
    if any(
        marker in combined_error
        for marker in (
            "authentication_error",
            "invalid api key",
            "invalid x-api-key",
        )
    ):
        return "unavailable", "authentication_error"
    if event_errors:
        return "infrastructure_error", "provider_error"
    return "infrastructure_error", "agent_runtime_error"


def first_terminal_failure(logs: list[Any]) -> tuple[str, str] | None:
    for log in logs:
        for sample in log.samples or []:
            if failure := classify_sample_failure(log.status, sample):
                return failure
        if log.status == "error" and not log.samples:
            return "infrastructure_error", "framework_error"
    return None


def normalize_sample(inspect_status: str, sample: Any, inspect_log: Path | str) -> dict[str, Any]:
    scores = {
        name: {
            "value": score.value,
            "explanation": score.explanation,
            "metadata": model_dump(score.metadata),
        }
        for name, score in (sample.scores or {}).items()
    }
    event_counts = Counter(type(event).__name__ for event in sample.events)
    task_score = scores.get("api_notes_scorer", {}).get("value")
    failure = classify_sample_failure(inspect_status, sample)
    if failure is not None:
        status, error_kind = failure
    elif (
        event_counts["SampleLimitEvent"] > 0
        and event_counts["ModelEvent"] == 0
        and event_counts["ToolEvent"] == 0
    ):
        status = "infrastructure_error"
        error_kind = "setup_limit"
    elif task_score == "C":
        status = "passed"
        error_kind = None
    else:
        status = "failed"
        error_kind = None

    return {
        "run_id": sample.metadata.get("run_id"),
        "attempt_id": sample.metadata.get("attempt_id"),
        "phase": sample.metadata.get("phase"),
        "pair": sample.metadata.get("pair"),
        "order": sample.metadata.get("order"),
        "condition": sample.metadata.get("condition"),
        "status": status,
        "error_kind": error_kind,
        "inspect_status": inspect_status,
        "error": normalized_error(sample.error),
        "total_time": sample.total_time,
        "working_time": sample.working_time,
        "model_usage": {
            name: model_dump(usage)
            for name, usage in sample.model_usage.items()
        },
        "event_counts": dict(sorted(event_counts.items())),
        "provider_requests": event_counts["ModelEvent"],
        "tool_calls": event_counts["ToolEvent"],
        "scores": scores,
        "inspect_log": str(inspect_log),
    }


def latest_phase_runs(runs: list[dict[str, Any]], phase: str) -> list[dict[str, Any]]:
    phase_runs = [run for run in runs if run.get("phase") == phase]
    attempt_ids = sorted(
        {
            str(run["attempt_id"])
            for run in phase_runs
            if run.get("attempt_id") is not None
        }
    )
    if not attempt_ids:
        return phase_runs
    latest_attempt = attempt_ids[-1]
    return [run for run in phase_runs if run.get("attempt_id") == latest_attempt]


def run_tokens(run: dict[str, Any]) -> int:
    total = 0
    for usage in run.get("model_usage", {}).values():
        if usage.get("total_tokens") is not None:
            total += int(usage["total_tokens"])
        else:
            total += int(usage.get("input_tokens") or 0)
            total += int(usage.get("output_tokens") or 0)
    return total


def run_cost(run: dict[str, Any]) -> float:
    return sum(
        float(usage.get("total_cost") or 0.0)
        for usage in run.get("model_usage", {}).values()
    )


def score_value(run: dict[str, Any], scorer: str) -> Any:
    return run.get("scores", {}).get(scorer, {}).get("value")


def capability_metadata(run: dict[str, Any]) -> dict[str, Any]:
    return (
        run.get("scores", {})
        .get("symposium_capability_scorer", {})
        .get("metadata", {})
        or {}
    )


def signed(value: int | float, *, decimals: int = 0) -> str:
    return f"{value:+.{decimals}f}" if decimals else f"{int(value):+d}"


def render_report(document: dict[str, Any]) -> str:
    all_runs = list(document.get("runs", []))
    runs = latest_phase_runs(all_runs, "smoke") + latest_phase_runs(
        all_runs, "measured"
    )
    smoke_runs = latest_phase_runs(all_runs, "smoke")
    smoke_by_condition = {
        run.get("condition"): run
        for run in smoke_runs
        if run.get("condition") in CONDITION_NAMES
    }
    complete_pair = set(smoke_by_condition) == set(CONDITION_NAMES)
    completed_agents = complete_pair and all(
        run.get("status") in ("passed", "failed")
        for run in smoke_by_condition.values()
    )
    usage_recorded = complete_pair and all(
        run_tokens(run) > 0 and int(run.get("provider_requests") or 0) > 0
        for run in smoke_by_condition.values()
    )
    scores_recorded = complete_pair and all(
        score_value(run, "api_notes_scorer") in ("C", "I")
        for run in smoke_by_condition.values()
    )
    treatment = smoke_by_condition.get("symposium", {})
    skill_available = capability_metadata(treatment).get("skill_available") is True
    capability_recorded = (
        "symposium_capability_scorer" in treatment.get("scores", {})
    )
    gates = {
        "Grader controls passed": document.get("controls", {}).get("passed") is True,
        "Both smoke conditions retained": complete_pair,
        "Both agents reached a task outcome": completed_agents,
        "Nonzero provider usage recorded": usage_recorded,
        "Deterministic task scores recorded": scores_recorded,
        "Treatment skill marked available": skill_available,
        "Capability evidence recorded": capability_recorded,
    }
    smoke_ready = all(gates.values())

    lines = [
        "# Skill-effectiveness evidence report",
        "",
        f"Experiment: `{document.get('experiment_id', 'unknown')}`",
        "",
        "## Smoke gates",
        "",
        f"**Smoke readiness: {'PASS' if smoke_ready else 'FAIL'}**",
        "",
        "| Gate | Result |",
        "|---|---|",
    ]
    lines.extend(
        f"| {name} | {'PASS' if passed else 'FAIL'} |"
        for name, passed in gates.items()
    )

    lines.extend(
        [
            "",
            "## Latest runs",
            "",
            "| Phase | Pair | Condition | Status | Task | Tokens | Cost | Seconds | "
            "Requests | Skill available | Capability invoked |",
            "|---|---:|---|---|---|---:|---:|---:|---:|---|---|",
        ]
    )
    for run in sorted(
        runs,
        key=lambda item: (
            str(item.get("phase")),
            int(item.get("pair") or 0),
            str(item.get("condition")),
        ),
    ):
        metadata = capability_metadata(run)
        lines.append(
            "| "
            + " | ".join(
                [
                    str(run.get("phase") or "-"),
                    str(run.get("pair") or "-"),
                    str(run.get("condition") or "-"),
                    str(run.get("status") or "-"),
                    str(score_value(run, "api_notes_scorer") or "-"),
                    str(run_tokens(run)),
                    f"${run_cost(run):.4f}",
                    f"{float(run.get('total_time') or 0.0):.1f}",
                    str(run.get("provider_requests") or 0),
                    "yes" if metadata.get("skill_available") else "no",
                    "yes"
                    if score_value(run, "symposium_capability_scorer") == 1
                    else "no",
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Pair deltas (treatment minus baseline)",
            "",
            "| Phase | Pair | Baseline status | Treatment status | Task delta | "
            "Token delta | Time delta (s) | Capability invoked |",
            "|---|---:|---|---|---:|---:|---:|---|",
        ]
    )
    grouped: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for run in runs:
        key = (str(run.get("phase")), int(run.get("pair") or 0))
        grouped.setdefault(key, {})[str(run.get("condition"))] = run
    for (phase, pair), conditions in sorted(grouped.items()):
        if not all(condition in conditions for condition in CONDITION_NAMES):
            continue
        baseline = conditions["baseline"]
        treatment_run = conditions["symposium"]
        baseline_task = 1 if score_value(baseline, "api_notes_scorer") == "C" else 0
        treatment_task = (
            1 if score_value(treatment_run, "api_notes_scorer") == "C" else 0
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    phase,
                    str(pair),
                    str(baseline.get("status")),
                    str(treatment_run.get("status")),
                    signed(treatment_task - baseline_task),
                    signed(run_tokens(treatment_run) - run_tokens(baseline)),
                    signed(
                        float(treatment_run.get("total_time") or 0.0)
                        - float(baseline.get("total_time") or 0.0),
                        decimals=1,
                    ),
                    "yes"
                    if score_value(treatment_run, "symposium_capability_scorer") == 1
                    else "no",
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "The smoke gates assess whether the experiment produced interpretable "
            "evidence; they do not choose an adoption verdict.",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(config: dict[str, Any]) -> int:
    results_path = resolve(config["experiment"]["results-path"])
    if not results_path.exists():
        raise SystemExit("No normalized results found; run summarize first")
    document = json.loads(results_path.read_text(encoding="utf-8"))
    report_path = resolve(
        config["experiment"].get("report-path", "artifacts/report.md")
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(document), encoding="utf-8")
    print(f"Wrote evidence report to {report_path}")
    return 0


def summarize(config: dict[str, Any]) -> int:
    from inspect_ai.log import list_eval_logs, read_eval_log

    log_root = resolve(config["experiment"]["logs-path"])
    output_path = resolve(config["experiment"]["results-path"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []

    if log_root.exists():
        for info in reversed(list_eval_logs(str(log_root))):
            log = read_eval_log(info)
            for sample in log.samples or []:
                if sample.metadata.get("phase") == "control":
                    continue
                runs.append(normalize_sample(log.status, sample, str(info)))

    document = {
        "schema_version": 1,
        "experiment_id": config["experiment"]["id"],
        "configuration": config["experiment"],
        "framework_versions": framework_versions(),
        "controls": control_result(config),
        "generated_at": datetime.now(UTC).isoformat(),
        "runs": runs,
    }
    output_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(runs)} normalized run(s) to {output_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Disposable Symposium skill-eval prototype")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="print the free execution plan")
    plan_parser.add_argument("--json", action="store_true", help="emit the plan as JSON")

    subparsers.add_parser(
        "prepare",
        help="perform free local preparation and grader controls",
        description="Perform free local preparation and grader controls.",
    )

    for command in ("smoke", "measured"):
        run_parser = subparsers.add_parser(command, help=f"run the paid {command} phase")
        run_parser.add_argument("--confirm-paid-run", action="store_true")

    subparsers.add_parser("controls", help="run free grader controls in Docker")
    subparsers.add_parser("summarize", help="export normalized JSON from existing logs")
    subparsers.add_parser("report", help="render a free Markdown evidence report")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()

    if args.command == "plan":
        return print_plan(config, as_json=args.json)
    if args.command == "prepare":
        return prepare_environment(config)
    if args.command == "controls":
        return run_controls(config)
    if args.command in ("smoke", "measured"):
        return execute_phase(args, config, args.command)
    if args.command == "summarize":
        return summarize(config)
    if args.command == "report":
        return write_report(config)
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
