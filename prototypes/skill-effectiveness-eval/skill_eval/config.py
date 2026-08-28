"""Validated TOML configuration for the skill-effectiveness prototype."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from skill_eval.models import CONDITION_NAMES, PHASE_NAMES, Condition, JsonObject, Phase

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "experiment.toml"


class ConfigError(ValueError):
    """Report an invalid or incomplete experiment configuration."""


@dataclass(frozen=True)
class ExperimentSettings:
    """Identity, intervention, and artifact paths for the experiment."""

    id: str
    seed: int
    model: str
    agent: str
    agent_version: str
    task_version: int
    skill: str
    crate: str
    crate_version: str
    skill_path: str
    fixture_path: str
    grader_path: str
    sandbox_config: str
    results_path: str
    report_path: str
    controls_path: str
    budget_path: str
    logs_path: str


@dataclass(frozen=True)
class Limits:
    """Hard and observed limits applied to each run and full experiment."""

    message_limit: int
    token_limit: int
    output_token_limit: int
    time_limit_seconds: int
    cost_limit_usd: float
    experiment_cost_limit_usd: float
    max_provider_requests: int
    max_tool_calls: int


@dataclass(frozen=True)
class AgentBinaryPin:
    """Integrity metadata for the sandboxed coding-agent executable."""

    cache_file: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ModelPrice:
    """Per-million-token prices passed to Inspect."""

    input: float
    output: float
    input_cache_write: float
    input_cache_read: float


@dataclass(frozen=True)
class ExperimentConfig:
    """Fully validated configuration consumed by the prototype."""

    schema_version: int
    root: Path
    experiment: ExperimentSettings
    conditions: Mapping[Condition, tuple[str, ...]]
    phase_pairs: Mapping[Phase, int]
    limits: Limits
    agent_binary: AgentBinaryPin
    model_costs: Mapping[str, ModelPrice]

    def resolve(self, configured_path: str) -> Path:
        """Resolve a path relative to the prototype directory."""
        return (self.root / configured_path).resolve()

    def experiment_json(self) -> JsonObject:
        """Return public experiment settings for plans and normalized results."""
        return cast(JsonObject, asdict(self.experiment))

    def model_costs_json(self) -> JsonObject:
        """Return model prices in the shape Inspect and JSON consumers expect."""
        return cast(
            JsonObject,
            {name: asdict(price) for name, price in self.model_costs.items()},
        )


def _table(document: Mapping[str, Any], key: str, location: str = "root") -> Mapping[str, Any]:
    value = document.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"{location}.{key} must be a table")
    return value


def _string(table: Mapping[str, Any], key: str, location: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{location}.{key} must be a non-empty string")
    return value


def _integer(table: Mapping[str, Any], key: str, location: str) -> int:
    value = table.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"{location}.{key} must be an integer")
    return value


def _positive_integer(table: Mapping[str, Any], key: str, location: str) -> int:
    value = _integer(table, key, location)
    if value <= 0:
        raise ConfigError(f"{location}.{key} must be positive")
    return value


def _positive_number(table: Mapping[str, Any], key: str, location: str) -> float:
    value = table.get(key)
    if not isinstance(value, int | float) or isinstance(value, bool) or not isfinite(value) or value <= 0:
        raise ConfigError(f"{location}.{key} must be a positive number")
    return float(value)


def _strings(table: Mapping[str, Any], key: str, location: str) -> tuple[str, ...]:
    value = table.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{location}.{key} must be an array of strings")
    return tuple(value)


def _experiment_settings(document: Mapping[str, Any]) -> ExperimentSettings:
    table = _table(document, "experiment")
    return ExperimentSettings(
        id=_string(table, "id", "experiment"),
        seed=_integer(table, "seed", "experiment"),
        model=_string(table, "model", "experiment"),
        agent=_string(table, "agent", "experiment"),
        agent_version=_string(table, "agent-version", "experiment"),
        task_version=_positive_integer(table, "task-version", "experiment"),
        skill=_string(table, "skill", "experiment"),
        crate=_string(table, "crate", "experiment"),
        crate_version=_string(table, "crate-version", "experiment"),
        skill_path=_string(table, "skill-path", "experiment"),
        fixture_path=_string(table, "fixture-path", "experiment"),
        grader_path=_string(table, "grader-path", "experiment"),
        sandbox_config=_string(table, "sandbox-config", "experiment"),
        results_path=_string(table, "results-path", "experiment"),
        report_path=_string(table, "report-path", "experiment"),
        controls_path=_string(table, "controls-path", "experiment"),
        budget_path=_string(table, "budget-path", "experiment"),
        logs_path=_string(table, "logs-path", "experiment"),
    )


def _conditions(document: Mapping[str, Any]) -> Mapping[Condition, tuple[str, ...]]:
    table = _table(document, "conditions")
    conditions: dict[Condition, tuple[str, ...]] = {}
    for condition in CONDITION_NAMES:
        conditions[condition] = _strings(_table(table, condition, "conditions"), "skills", f"conditions.{condition}")
    if set(table) != set(CONDITION_NAMES):
        raise ConfigError("conditions must contain exactly baseline and symposium")
    return MappingProxyType(conditions)


def _phases(document: Mapping[str, Any]) -> Mapping[Phase, int]:
    table = _table(document, "phases")
    phases: dict[Phase, int] = {}
    for phase in PHASE_NAMES:
        phases[phase] = _positive_integer(_table(table, phase, "phases"), "pairs", f"phases.{phase}")
    if set(table) != set(PHASE_NAMES):
        raise ConfigError("phases must contain exactly smoke and measured")
    return MappingProxyType(phases)


def _limits(document: Mapping[str, Any]) -> Limits:
    table = _table(document, "limits")
    return Limits(
        message_limit=_positive_integer(table, "message-limit", "limits"),
        token_limit=_positive_integer(table, "token-limit", "limits"),
        output_token_limit=_positive_integer(table, "output-token-limit", "limits"),
        time_limit_seconds=_positive_integer(table, "time-limit-seconds", "limits"),
        cost_limit_usd=_positive_number(table, "cost-limit-usd", "limits"),
        experiment_cost_limit_usd=_positive_number(table, "experiment-cost-limit-usd", "limits"),
        max_provider_requests=_positive_integer(table, "max-provider-requests", "limits"),
        max_tool_calls=_positive_integer(table, "max-tool-calls", "limits"),
    )


def _agent_binary(document: Mapping[str, Any]) -> AgentBinaryPin:
    table = _table(document, "agent-binary")
    cache_file = _string(table, "cache-file", "agent-binary")
    if Path(cache_file).name != cache_file:
        raise ConfigError("agent-binary.cache-file must be a filename without directories")
    sha256 = _string(table, "sha256", "agent-binary").casefold()
    if re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
        raise ConfigError("agent-binary.sha256 must be 64 hexadecimal characters")
    return AgentBinaryPin(
        cache_file=cache_file,
        size=_positive_integer(table, "size", "agent-binary"),
        sha256=sha256,
    )


def _model_costs(document: Mapping[str, Any]) -> Mapping[str, ModelPrice]:
    table = _table(document, "model-costs")
    costs: dict[str, ModelPrice] = {}
    for model, raw_price in table.items():
        if not isinstance(model, str) or not isinstance(raw_price, dict):
            raise ConfigError("model-costs entries must be named tables")
        costs[model] = ModelPrice(
            input=_positive_number(raw_price, "input", f"model-costs.{model}"),
            output=_positive_number(raw_price, "output", f"model-costs.{model}"),
            input_cache_write=_positive_number(raw_price, "input_cache_write", f"model-costs.{model}"),
            input_cache_read=_positive_number(raw_price, "input_cache_read", f"model-costs.{model}"),
        )
    if not costs:
        raise ConfigError("model-costs must contain at least one model")
    return MappingProxyType(costs)


def load_config(path: Path = CONFIG_PATH) -> ExperimentConfig:
    """Load and validate an experiment configuration file."""
    try:
        with path.open("rb") as stream:
            document = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"cannot read configuration {path}: {error}") from error

    schema_version = _positive_integer(document, "schema-version", "root")
    if schema_version != 1:
        raise ConfigError(f"unsupported schema-version: {schema_version}")

    experiment = _experiment_settings(document)
    conditions = _conditions(document)
    phases = _phases(document)
    limits = _limits(document)
    model_costs = _model_costs(document)
    if experiment.model not in model_costs:
        raise ConfigError(f"model-costs has no entry for experiment model {experiment.model}")

    declared_total = sum(phases.values()) * len(CONDITION_NAMES) * limits.cost_limit_usd
    if declared_total > limits.experiment_cost_limit_usd:
        raise ConfigError(
            f"declared experiment maximum ${declared_total:.2f} exceeds "
            f"experiment ceiling ${limits.experiment_cost_limit_usd:.2f}"
        )

    return ExperimentConfig(
        schema_version=schema_version,
        root=path.resolve().parent,
        experiment=experiment,
        conditions=conditions,
        phase_pairs=phases,
        limits=limits,
        agent_binary=_agent_binary(document),
        model_costs=model_costs,
    )
