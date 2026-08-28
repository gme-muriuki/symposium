"""Human-readable evidence gates and paired comparisons."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from skill_eval.config import ExperimentConfig
from skill_eval.models import CONDITION_NAMES, JsonValue
from skill_eval.results import (
    NormalizedRun,
    ResultsDocument,
    capability_metadata,
    latest_phase_runs,
    load_results,
    run_cost,
    run_tokens,
    score_value,
)


def _boolean(value: JsonValue) -> bool:
    return value is True


def _cell(value: object) -> str:
    """Escape dynamic values for a Markdown table cell."""
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _signed(value: int | float, *, decimals: int = 0) -> str:
    return f"{value:+.{decimals}f}" if decimals else f"{int(value):+d}"


def _smoke_gates(document: ResultsDocument) -> tuple[Mapping[str, bool], list[NormalizedRun]]:
    smoke_runs = latest_phase_runs(document.runs, "smoke")
    smoke_by_condition = {run.condition: run for run in smoke_runs if run.condition in CONDITION_NAMES}
    complete_pair = set(smoke_by_condition) == set(CONDITION_NAMES)
    completed_agents = complete_pair and all(run.status in ("passed", "failed") for run in smoke_by_condition.values())
    usage_recorded = complete_pair and all(
        run_tokens(run) > 0 and run.provider_requests > 0 for run in smoke_by_condition.values()
    )
    scores_recorded = complete_pair and all(
        score_value(run, "api_notes_scorer") in ("C", "I") for run in smoke_by_condition.values()
    )
    treatment = smoke_by_condition.get("symposium")
    skill_available = treatment is not None and _boolean(capability_metadata(treatment).get("skill_available"))
    capability_recorded = treatment is not None and "symposium_capability_scorer" in treatment.scores
    gates = {
        "Grader controls passed": document.controls.get("passed") is True,
        "Both smoke conditions retained": complete_pair,
        "Both agents reached a task outcome": completed_agents,
        "Nonzero provider usage recorded": usage_recorded,
        "Deterministic task scores recorded": scores_recorded,
        "Treatment skill marked available": skill_available,
        "Capability evidence recorded": capability_recorded,
    }
    return gates, smoke_runs


def _latest_runs(document: ResultsDocument) -> list[NormalizedRun]:
    return latest_phase_runs(document.runs, "smoke") + latest_phase_runs(document.runs, "measured")


def _task_delta(baseline: NormalizedRun, treatment: NormalizedRun) -> str:
    baseline_score = score_value(baseline, "api_notes_scorer")
    treatment_score = score_value(treatment, "api_notes_scorer")
    if baseline_score not in ("C", "I") or treatment_score not in ("C", "I"):
        return "-"
    return _signed(int(treatment_score == "C") - int(baseline_score == "C"))


def _append_latest_runs(lines: list[str], runs: Sequence[NormalizedRun]) -> None:
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
    for run in sorted(runs, key=lambda item: (item.phase or "", item.pair or 0, item.condition or "")):
        metadata = capability_metadata(run)
        lines.append(
            "| "
            + " | ".join(
                _cell(value)
                for value in (
                    run.phase or "-",
                    run.pair or "-",
                    run.condition or "-",
                    run.status,
                    score_value(run, "api_notes_scorer") or "-",
                    run_tokens(run),
                    f"${run_cost(run):.4f}",
                    f"{run.total_time or 0.0:.1f}",
                    run.provider_requests,
                    "yes" if metadata.get("skill_available") is True else "no",
                    "yes" if score_value(run, "symposium_capability_scorer") == 1 else "no",
                )
            )
            + " |"
        )


def _append_pair_deltas(lines: list[str], runs: Sequence[NormalizedRun]) -> None:
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
    grouped: dict[tuple[str, int], dict[str, NormalizedRun]] = {}
    for run in runs:
        grouped.setdefault((run.phase or "", run.pair or 0), {})[run.condition or ""] = run
    for (phase, pair), conditions in sorted(grouped.items()):
        if not all(condition in conditions for condition in CONDITION_NAMES):
            continue
        baseline = conditions["baseline"]
        treatment = conditions["symposium"]
        lines.append(
            "| "
            + " | ".join(
                _cell(value)
                for value in (
                    phase,
                    pair,
                    baseline.status,
                    treatment.status,
                    _task_delta(baseline, treatment),
                    _signed(run_tokens(treatment) - run_tokens(baseline)),
                    _signed((treatment.total_time or 0.0) - (baseline.total_time or 0.0), decimals=1),
                    "yes" if score_value(treatment, "symposium_capability_scorer") == 1 else "no",
                )
            )
            + " |"
        )


def render_report(document: ResultsDocument) -> str:
    """Render smoke gates and paired evidence without choosing a verdict."""
    gates, _ = _smoke_gates(document)
    smoke_ready = all(gates.values())
    runs = _latest_runs(document)
    lines = [
        "# Skill-effectiveness evidence report",
        "",
        f"Experiment: {_cell(document.experiment_id)}",
        "",
        "## Smoke gates",
        "",
        f"**Smoke readiness: {'PASS' if smoke_ready else 'FAIL'}**",
        "",
        "| Gate | Result |",
        "|---|---|",
    ]
    lines.extend(f"| {_cell(name)} | {'PASS' if passed else 'FAIL'} |" for name, passed in gates.items())
    _append_latest_runs(lines, runs)
    _append_pair_deltas(lines, runs)
    lines.extend(
        [
            "",
            "The smoke gates assess whether the experiment produced interpretable "
            "evidence; they do not choose an adoption verdict.",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(config: ExperimentConfig) -> int:
    """Render retained normalized evidence to Markdown."""
    results_path = config.resolve(config.experiment.results_path)
    if not results_path.exists():
        raise SystemExit("No normalized results found; run summarize first")
    document = load_results(results_path)
    report_path: Path = config.resolve(config.experiment.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(document), encoding="utf-8")
    print(f"Wrote evidence report to {report_path}")
    return 0
