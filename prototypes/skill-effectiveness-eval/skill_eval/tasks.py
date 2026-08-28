"""Inspect tasks, solvers, request limits, and deterministic scorers."""

from __future__ import annotations

from pathlib import Path

from inspect_ai import Task
from inspect_ai.agent import as_solver
from inspect_ai.dataset import Sample
from inspect_ai.model import (
    ChatMessage,
    GenerateConfig,
    GenerateFilter,
    GenerateInput,
    Model,
    ModelOutput,
)
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Scorer, Target, accuracy, scorer
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import ToolChoice, ToolInfo
from inspect_ai.util import LimitExceededError, sandbox, token_limit
from inspect_swe import claude_code

from skill_eval.config import ExperimentConfig
from skill_eval.models import PlannedRun

WORKSPACE = "/workspace"
EXPECTED_INVOCATION = "cargo agents crate-info cargo-platform"
PROMPT = (
    "Complete the three `<from source>` entries in `API_NOTES.md` by inspecting "
    "the source of cargo-platform 0.3.3.\n\n"
    "Preserve the heading and labels. List variants in declaration order as "
    "comma-separated inline-code items, including field types. For the method, "
    "list only parameters after `self`, in declaration order, with each complete "
    "name/type pair as an inline-code item.\n\n"
    "Do not change `Cargo.toml` or create additional files. Leave the completed "
    "notes in the working tree.\n"
)


def provider_request_filter(max_requests: int) -> GenerateFilter:
    """Stop an agent after the configured number of provider requests."""
    requests = 0

    async def enforce(
        model: Model,
        messages: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput | GenerateInput | None:
        nonlocal requests
        requests += 1
        if requests > max_requests:
            raise LimitExceededError(
                "custom",
                value=requests,
                limit=max_requests,
                message=f"Exceeded provider request limit: {max_requests}",
            )
        return None

    return enforce


@scorer(metrics=[accuracy()])
def api_notes_scorer(expected_path: Path) -> Scorer:
    """Build an exact-content scorer for the completed notes file."""
    expected = expected_path.read_text(encoding="utf-8").replace("\r\n", "\n")

    async def score(state: TaskState, target: Target) -> Score:
        try:
            observed = await sandbox().read_file(f"{WORKSPACE}/API_NOTES.md")
        except FileNotFoundError:
            observed = ""
        observed = observed.replace("\r\n", "\n")
        matches = observed == expected
        return Score(
            value=CORRECT if matches else INCORRECT,
            explanation=(
                "API_NOTES.md exactly matches the grader-owned answer"
                if matches
                else "API_NOTES.md does not exactly match the grader-owned answer"
            ),
            metadata={"observed": observed},
        )

    return score


@scorer(metrics=[])
def symposium_capability_scorer(condition: str) -> Scorer:
    """Score whether the task invoked the capability named by the skill."""

    async def score(state: TaskState, target: Target) -> Score:
        try:
            contents = await sandbox().read_file(f"{WORKSPACE}/.symposium/invocations.log")
            invocations = [line.strip() for line in contents.splitlines() if line.strip()]
        except FileNotFoundError:
            invocations = []

        invoked = EXPECTED_INVOCATION in invocations
        return Score(
            value=1 if invoked else 0,
            explanation=(
                "Expected cargo agents invocation observed"
                if invoked
                else "Expected cargo agents invocation not observed"
            ),
            metadata={
                "condition": condition,
                "skill_available": condition == "symposium",
                "expected_invocation": EXPECTED_INVOCATION,
                "invocations": invocations,
            },
        )

    return score


@solver
def no_op_solver() -> Solver:
    """Return the sample unchanged for no-model control evaluations."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        return state

    return solve


def task_files(fixture: Path, notes_path: Path) -> dict[str, str]:
    """Map host fixture files to their sandbox paths."""
    return {
        f"{WORKSPACE}/Cargo.toml": str(fixture / "Cargo.toml"),
        f"{WORKSPACE}/API_NOTES.md": str(notes_path),
    }


def build_task(config: ExperimentConfig, planned_run: PlannedRun) -> Task:
    """Construct one paid baseline or treatment task."""
    experiment = config.experiment
    limits = config.limits
    fixture = config.resolve(experiment.fixture_path)
    expected = config.resolve(experiment.grader_path)
    skill = config.resolve(experiment.skill_path)
    compose = config.resolve(experiment.sandbox_config)

    skills = [skill] if planned_run.condition == "symposium" else None
    metadata = {
        "experiment_id": experiment.id,
        "run_id": planned_run.run_id,
        "attempt_id": planned_run.attempt_id,
        "phase": planned_run.phase,
        "pair": planned_run.pair,
        "order": planned_run.order,
        "condition": planned_run.condition,
        "task_version": experiment.task_version,
        "skill": experiment.skill,
        "agent": experiment.agent,
        "agent_version": experiment.agent_version,
    }

    agent = claude_code(
        skills=skills,
        version="sandbox",
        attempts=1,
        retry_refusals=0,
        retry_uncaught_errors=0,
        cwd=WORKSPACE,
        permission_mode="bypassPermissions",
        disallowed_tools=["WebFetch", "WebSearch"],
        filter=provider_request_filter(limits.max_provider_requests),
    )

    return Task(
        name=f"skill-effectiveness-{planned_run.condition}",
        dataset=[
            Sample(
                id=planned_run.run_id,
                input=PROMPT,
                target="API_NOTES.md exactly matches the grader-owned answer.",
                metadata=metadata,
                files=task_files(fixture, fixture / "API_NOTES.md"),
            )
        ],
        solver=as_solver(
            agent,
            limits=[token_limit(limits.output_token_limit, type="output")],
        ),
        scorer=[api_notes_scorer(expected), symposium_capability_scorer(planned_run.condition)],
        sandbox=("docker", str(compose)),
        message_limit=limits.message_limit,
        token_limit=limits.token_limit,
        time_limit=limits.time_limit_seconds,
        cost_limit=limits.cost_limit_usd,
        metadata=metadata,
    )


def build_control_task(config: ExperimentConfig, *, known_good: bool) -> Task:
    """Construct an untouched or known-good no-model control task."""
    experiment = config.experiment
    fixture = config.resolve(experiment.fixture_path)
    expected = config.resolve(experiment.grader_path)
    compose = config.resolve(experiment.sandbox_config)
    control = "known-good" if known_good else "untouched"
    notes_path = expected if known_good else fixture / "API_NOTES.md"
    metadata = {
        "experiment_id": experiment.id,
        "run_id": f"control-{control}",
        "phase": "control",
        "pair": 0,
        "order": 1 if known_good else 0,
        "condition": control,
    }

    return Task(
        name=f"skill-effectiveness-control-{control}",
        dataset=[
            Sample(
                id=f"control-{control}",
                input="Do nothing.",
                target="Known-good passes; untouched fails.",
                metadata=metadata,
                files=task_files(fixture, notes_path),
            )
        ],
        solver=no_op_solver(),
        scorer=api_notes_scorer(expected),
        sandbox=("docker", str(compose)),
        metadata=metadata,
    )
