from __future__ import annotations

from pathlib import Path
from typing import Any

from inspect_ai import Task
from inspect_ai.agent import as_solver
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessage, GenerateConfig, GenerateInput, Model, ModelOutput
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Target, accuracy, scorer
from inspect_ai.solver import TaskState, solver
from inspect_ai.tool import ToolChoice, ToolInfo
from inspect_ai.util import LimitExceededError, sandbox, token_limit
from inspect_swe import claude_code


ROOT = Path(__file__).resolve().parent
WORKSPACE = "/workspace"
EXPECTED_INVOCATION = "cargo agents crate-info cargo-platform"
PROMPT = """Complete the three `<from source>` entries in `API_NOTES.md` by inspecting the source of cargo-platform 0.3.3.

Preserve the heading and labels. List variants in declaration order as comma-separated inline-code items, including field types. For the method, list only parameters after `self`, in declaration order, with each complete name/type pair as an inline-code item.

Do not change `Cargo.toml` or create additional files. Leave the completed notes in the working tree.
"""


def resolve(configured_path: str) -> Path:
    return (ROOT / configured_path).resolve()


def provider_request_filter(max_requests: int):
    requests = 0

    async def enforce(
        model: Model,
        input: list[ChatMessage],
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
def api_notes_scorer(expected_path: Path):
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
def symposium_capability_scorer(condition: str):
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
def no_op_solver():
    async def solve(state: TaskState, generate):
        return state

    return solve


def task_files(fixture: Path, notes_path: Path) -> dict[str, str]:
    return {
        f"{WORKSPACE}/Cargo.toml": str(fixture / "Cargo.toml"),
        f"{WORKSPACE}/API_NOTES.md": str(notes_path),
    }


def build_task(config: dict[str, Any], planned_run: Any) -> Task:
    experiment = config["experiment"]
    limits = config["limits"]
    fixture = resolve(experiment["fixture-path"])
    expected = resolve(experiment["grader-path"])
    skill = resolve(experiment["skill-path"])
    compose = resolve(experiment["sandbox-config"])

    skills = [skill] if planned_run.condition == "symposium" else None
    metadata = {
        "experiment_id": experiment["id"],
        "run_id": planned_run.run_id,
        "attempt_id": planned_run.attempt_id,
        "phase": planned_run.phase,
        "pair": planned_run.pair,
        "order": planned_run.order,
        "condition": planned_run.condition,
        "task_version": experiment["task-version"],
        "skill": experiment["skill"],
        "agent": experiment["agent"],
        "agent_version": experiment["agent-version"],
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
        filter=provider_request_filter(int(limits["max-provider-requests"])),
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
            limits=[token_limit(int(limits["output-token-limit"]), type="output")],
        ),
        scorer=[api_notes_scorer(expected), symposium_capability_scorer(planned_run.condition)],
        sandbox=("docker", str(compose)),
        message_limit=int(limits["message-limit"]),
        token_limit=int(limits["token-limit"]),
        time_limit=int(limits["time-limit-seconds"]),
        cost_limit=float(limits["cost-limit-usd"]),
        metadata=metadata,
    )


def build_control_task(config: dict[str, Any], *, known_good: bool) -> Task:
    experiment = config["experiment"]
    fixture = resolve(experiment["fixture-path"])
    expected = resolve(experiment["grader-path"])
    compose = resolve(experiment["sandbox-config"])
    control = "known-good" if known_good else "untouched"
    notes_path = expected if known_good else fixture / "API_NOTES.md"
    metadata = {
        "experiment_id": experiment["id"],
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
