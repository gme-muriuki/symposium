"""Inspect-log classification, normalization, and portable result storage."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from inspect_ai.event import ModelEvent, SampleLimitEvent, ToolEvent
from inspect_ai.log import EvalLog, EvalSample

from skill_eval.config import ExperimentConfig
from skill_eval.environment import control_result, framework_versions
from skill_eval.models import JsonObject, JsonValue


class ResultsError(ValueError):
    """Report malformed normalized evidence."""


@dataclass(frozen=True)
class ScoreRecord:
    """Portable subset of one Inspect score."""

    value: JsonValue
    explanation: str | None
    metadata: JsonObject

    def to_json(self) -> JsonObject:
        """Return a secret-minimized score object."""
        return {
            "value": self.value,
            "explanation": self.explanation,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class NormalizedRun:
    """Portable evidence retained for one evaluated sample."""

    run_id: str | None
    attempt_id: str | None
    phase: str | None
    pair: int | None
    order: int | None
    condition: str | None
    status: str
    error_kind: str | None
    inspect_status: str
    error: JsonObject | None
    total_time: float | None
    working_time: float | None
    model_usage: Mapping[str, JsonObject]
    event_counts: Mapping[str, int]
    provider_requests: int
    tool_calls: int
    scores: Mapping[str, ScoreRecord]
    inspect_log: str

    def to_json(self) -> JsonObject:
        """Return the normalized result schema."""
        return {
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "phase": self.phase,
            "pair": self.pair,
            "order": self.order,
            "condition": self.condition,
            "status": self.status,
            "error_kind": self.error_kind,
            "inspect_status": self.inspect_status,
            "error": self.error,
            "total_time": self.total_time,
            "working_time": self.working_time,
            "model_usage": dict(self.model_usage),
            "event_counts": dict(self.event_counts),
            "provider_requests": self.provider_requests,
            "tool_calls": self.tool_calls,
            "scores": {name: score.to_json() for name, score in self.scores.items()},
            "inspect_log": self.inspect_log,
        }


@dataclass(frozen=True)
class ResultsDocument:
    """Versioned collection of normalized run evidence."""

    experiment_id: str
    configuration: JsonObject
    framework_versions: Mapping[str, str]
    controls: JsonObject
    generated_at: str
    runs: tuple[NormalizedRun, ...]

    def to_json(self) -> JsonObject:
        """Return the versioned portable results document."""
        return {
            "schema_version": 1,
            "experiment_id": self.experiment_id,
            "configuration": self.configuration,
            "framework_versions": dict(self.framework_versions),
            "controls": self.controls,
            "generated_at": self.generated_at,
            "runs": [run.to_json() for run in self.runs],
        }


def json_value(value: object) -> JsonValue:
    """Convert dynamic framework values into a stable JSON value."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, BaseException):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [json_value(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return json_value(model_dump(mode="json"))
    return str(value)


def _json_object(value: object, field: str) -> JsonObject:
    converted = json_value(value)
    if not isinstance(converted, dict):
        raise ResultsError(f"{field} must be an object")
    return converted


def error_text(value: object) -> str:
    """Return a stable one-line representation of a framework error."""
    if value is None:
        return ""
    if isinstance(value, str | BaseException):
        return str(value)
    if message := getattr(value, "message", None):
        return str(message)
    return json.dumps(json_value(value), sort_keys=True)


def normalized_error(value: object) -> JsonObject | None:
    """Retain only an error summary, excluding tracebacks and auth material."""
    if value is None:
        return None
    converted = json_value(value)
    if isinstance(converted, dict) and converted.get("message") is not None:
        return {"message": str(converted["message"])}
    return {"message": error_text(value)}


def classify_failure(
    inspect_status: str,
    sample_error: object,
    model_errors: Sequence[object],
) -> tuple[str, str] | None:
    """Classify terminal provider, framework, and agent failures."""
    failed = sample_error is not None or inspect_status == "error"
    if not failed:
        return None
    combined_error = "\n".join([error_text(sample_error), *(error_text(error) for error in model_errors)]).casefold()
    if any(
        marker in combined_error for marker in ("credit balance is too low", "insufficient credit", "billing_error")
    ):
        return "unavailable", "billing_error"
    if any(marker in combined_error for marker in ("authentication_error", "invalid api key", "invalid x-api-key")):
        return "unavailable", "authentication_error"
    if model_errors:
        return "infrastructure_error", "provider_error"
    return "infrastructure_error", "agent_runtime_error"


def classify_sample_failure(inspect_status: str, sample: EvalSample) -> tuple[str, str] | None:
    """Extract typed model-event errors and classify the sample."""
    model_errors = [event.error for event in sample.events if isinstance(event, ModelEvent) and event.error is not None]
    return classify_failure(inspect_status, sample.error, model_errors)


def first_terminal_failure(logs: Sequence[EvalLog]) -> tuple[str, str] | None:
    """Return the first failure that should stop a paid phase."""
    for log in logs:
        for sample in log.samples or []:
            if failure := classify_sample_failure(log.status, sample):
                return failure
        if log.status == "error" and not log.samples:
            return "infrastructure_error", "framework_error"
    return None


def _metadata_str(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) else None


def _metadata_int(metadata: Mapping[str, Any], key: str) -> int | None:
    value = metadata.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def normalize_sample(inspect_status: str, sample: EvalSample, inspect_log: Path | str) -> NormalizedRun:
    """Normalize an Inspect sample without copying messages or transcripts."""
    scores = {
        name: ScoreRecord(
            value=json_value(score.value),
            explanation=score.explanation,
            metadata=_json_object(score.metadata or {}, f"score {name} metadata"),
        )
        for name, score in (sample.scores or {}).items()
    }
    event_counts = Counter(type(event).__name__ for event in sample.events)
    task_score = scores.get("api_notes_scorer")
    failure = classify_sample_failure(inspect_status, sample)
    if failure is not None:
        status, error_kind = failure
    elif any(isinstance(event, SampleLimitEvent) for event in sample.events) and not any(
        isinstance(event, ModelEvent | ToolEvent) for event in sample.events
    ):
        status, error_kind = "infrastructure_error", "setup_limit"
    elif task_score is not None and task_score.value == "C":
        status, error_kind = "passed", None
    else:
        status, error_kind = "failed", None

    model_usage = {name: _json_object(usage, f"model usage {name}") for name, usage in sample.model_usage.items()}
    return NormalizedRun(
        run_id=_metadata_str(sample.metadata, "run_id"),
        attempt_id=_metadata_str(sample.metadata, "attempt_id"),
        phase=_metadata_str(sample.metadata, "phase"),
        pair=_metadata_int(sample.metadata, "pair"),
        order=_metadata_int(sample.metadata, "order"),
        condition=_metadata_str(sample.metadata, "condition"),
        status=status,
        error_kind=error_kind,
        inspect_status=inspect_status,
        error=normalized_error(sample.error),
        total_time=sample.total_time,
        working_time=sample.working_time,
        model_usage=model_usage,
        event_counts=dict(sorted(event_counts.items())),
        provider_requests=sum(isinstance(event, ModelEvent) for event in sample.events),
        tool_calls=sum(isinstance(event, ToolEvent) for event in sample.events),
        scores=scores,
        inspect_log=str(inspect_log),
    )


def run_tokens(run: NormalizedRun) -> int:
    """Return provider-reported tokens for one normalized run."""
    total = 0
    for usage in run.model_usage.values():
        if isinstance(usage.get("total_tokens"), int) and not isinstance(usage.get("total_tokens"), bool):
            total += cast(int, usage["total_tokens"])
        else:
            for field in ("input_tokens", "output_tokens"):
                value = usage.get(field)
                if isinstance(value, int) and not isinstance(value, bool):
                    total += value
    return total


def run_cost(run: NormalizedRun) -> float:
    """Return provider-reported cost for one normalized run."""
    total = 0.0
    for usage in run.model_usage.values():
        value = usage.get("total_cost")
        if isinstance(value, int | float) and not isinstance(value, bool):
            total += float(value)
    return total


def eval_logs_cost(logs: Sequence[EvalLog]) -> float:
    """Return observed cost from freshly returned Inspect logs."""
    total = 0.0
    for log in logs:
        for sample in log.samples or []:
            for usage in sample.model_usage.values():
                if usage.total_cost is not None:
                    total += float(usage.total_cost)
    return total


def score_value(run: NormalizedRun, scorer: str) -> JsonValue:
    """Return a scorer value or None when the score is absent."""
    score = run.scores.get(scorer)
    return score.value if score is not None else None


def capability_metadata(run: NormalizedRun) -> JsonObject:
    """Return structured capability evidence for a normalized run."""
    score = run.scores.get("symposium_capability_scorer")
    return score.metadata if score is not None else {}


def latest_phase_runs(runs: Sequence[NormalizedRun], phase: str) -> list[NormalizedRun]:
    """Select the lexically latest retained attempt for a phase."""
    phase_runs = [run for run in runs if run.phase == phase]
    attempt_ids = sorted({run.attempt_id for run in phase_runs if run.attempt_id is not None})
    if not attempt_ids:
        return phase_runs
    return [run for run in phase_runs if run.attempt_id == attempt_ids[-1]]


def _optional_string(value: object, field: str) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise ResultsError(f"{field} must be a string or null")


def _optional_integer(value: object, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise ResultsError(f"{field} must be an integer or null")


def _optional_number(value: object, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    raise ResultsError(f"{field} must be a number or null")


def _required_string(value: object, field: str) -> str:
    if isinstance(value, str):
        return value
    raise ResultsError(f"{field} must be a string")


def _required_integer(value: object, field: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise ResultsError(f"{field} must be an integer")


def _score_records(value: object, field: str) -> dict[str, ScoreRecord]:
    if not isinstance(value, dict):
        raise ResultsError(f"{field} must be an object")
    records: dict[str, ScoreRecord] = {}
    for name, raw_score in value.items():
        if not isinstance(name, str) or not isinstance(raw_score, dict):
            raise ResultsError(f"{field} entries must be named objects")
        records[name] = ScoreRecord(
            value=json_value(raw_score.get("value")),
            explanation=_optional_string(raw_score.get("explanation"), f"{field}.{name}.explanation"),
            metadata=_json_object(raw_score.get("metadata") or {}, f"{field}.{name}.metadata"),
        )
    return records


def _run_from_json(value: object, index: int) -> NormalizedRun:
    if not isinstance(value, dict):
        raise ResultsError(f"runs[{index}] must be an object")
    model_usage = _json_object(value.get("model_usage"), f"runs[{index}].model_usage")
    usage_objects = {
        name: _json_object(usage, f"runs[{index}].model_usage.{name}") for name, usage in model_usage.items()
    }
    event_counts_object = _json_object(value.get("event_counts"), f"runs[{index}].event_counts")
    event_counts = {
        name: _required_integer(count, f"runs[{index}].event_counts.{name}")
        for name, count in event_counts_object.items()
    }
    error = value.get("error")
    return NormalizedRun(
        run_id=_optional_string(value.get("run_id"), f"runs[{index}].run_id"),
        attempt_id=_optional_string(value.get("attempt_id"), f"runs[{index}].attempt_id"),
        phase=_optional_string(value.get("phase"), f"runs[{index}].phase"),
        pair=_optional_integer(value.get("pair"), f"runs[{index}].pair"),
        order=_optional_integer(value.get("order"), f"runs[{index}].order"),
        condition=_optional_string(value.get("condition"), f"runs[{index}].condition"),
        status=_required_string(value.get("status"), f"runs[{index}].status"),
        error_kind=_optional_string(value.get("error_kind"), f"runs[{index}].error_kind"),
        inspect_status=_required_string(value.get("inspect_status"), f"runs[{index}].inspect_status"),
        error=None if error is None else _json_object(error, f"runs[{index}].error"),
        total_time=_optional_number(value.get("total_time"), f"runs[{index}].total_time"),
        working_time=_optional_number(value.get("working_time"), f"runs[{index}].working_time"),
        model_usage=usage_objects,
        event_counts=event_counts,
        provider_requests=_required_integer(value.get("provider_requests"), f"runs[{index}].provider_requests"),
        tool_calls=_required_integer(value.get("tool_calls"), f"runs[{index}].tool_calls"),
        scores=_score_records(value.get("scores"), f"runs[{index}].scores"),
        inspect_log=_required_string(value.get("inspect_log"), f"runs[{index}].inspect_log"),
    )


def load_results(path: Path) -> ResultsDocument:
    """Load and validate a normalized results document."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ResultsError(f"cannot read normalized results: {error}") from error
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ResultsError("normalized results must be a schema-version 1 object")
    raw_runs = document.get("runs")
    if not isinstance(raw_runs, list):
        raise ResultsError("normalized results runs must be an array")
    versions = _json_object(document.get("framework_versions"), "framework_versions")
    return ResultsDocument(
        experiment_id=_required_string(document.get("experiment_id"), "experiment_id"),
        configuration=_json_object(document.get("configuration"), "configuration"),
        framework_versions={
            name: _required_string(value, f"framework_versions.{name}") for name, value in versions.items()
        },
        controls=_json_object(document.get("controls"), "controls"),
        generated_at=_required_string(document.get("generated_at"), "generated_at"),
        runs=tuple(_run_from_json(run, index) for index, run in enumerate(raw_runs)),
    )


def summarize(config: ExperimentConfig) -> int:
    """Export portable JSON from retained Inspect logs."""
    from inspect_ai.log import list_eval_logs, read_eval_log

    log_root = config.resolve(config.experiment.logs_path)
    output_path = config.resolve(config.experiment.results_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    runs: list[NormalizedRun] = []

    if log_root.exists():
        for info in reversed(list_eval_logs(str(log_root))):
            log = read_eval_log(info)
            for sample in log.samples or []:
                if sample.metadata.get("phase") == "control":
                    continue
                runs.append(normalize_sample(log.status, sample, str(info)))

    document = ResultsDocument(
        experiment_id=config.experiment.id,
        configuration=config.experiment_json(),
        framework_versions=framework_versions(),
        controls=control_result(config).to_json(),
        generated_at=datetime.now(UTC).isoformat(),
        runs=tuple(runs),
    )
    output_path.write_text(json.dumps(document.to_json(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(runs)} normalized run(s) to {output_path}")
    return 0
