"""Paired scheduling and cumulative budget accounting."""

from __future__ import annotations

import json
import os
import random
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from importlib import import_module
from math import isfinite
from pathlib import Path
from typing import BinaryIO, Protocol, cast

from skill_eval.config import ExperimentConfig
from skill_eval.models import (
    CONDITION_NAMES,
    BudgetEntry,
    BudgetSummary,
    JsonObject,
    Phase,
    PlannedRun,
)

BUDGET_SCHEMA_VERSION = 1


class BudgetError(RuntimeError):
    """Report malformed budget evidence or an exceeded ceiling."""


class _FcntlModule(Protocol):
    LOCK_EX: int
    LOCK_NB: int
    LOCK_UN: int

    def flock(self, file_descriptor: int, operation: int) -> None: ...


def build_plan(config: ExperimentConfig, phase: Phase) -> list[PlannedRun]:
    """Build deterministic, pair-randomized runs for one phase."""
    planned: list[PlannedRun] = []
    for pair in range(1, config.phase_pairs[phase] + 1):
        conditions = list(CONDITION_NAMES)
        random.Random(f"{config.experiment.seed}:{phase}:{pair}").shuffle(conditions)
        for order, condition in enumerate(conditions, start=1):
            planned.append(
                PlannedRun(
                    run_id=f"{phase}-p{pair}-{order}-{condition}",
                    phase=phase,
                    pair=pair,
                    order=order,
                    condition=condition,
                    skills=config.conditions[condition],
                )
            )
    return planned


def with_attempt(runs: list[PlannedRun], attempt_id: str) -> list[PlannedRun]:
    """Attach a retained attempt identifier to planned runs."""
    return [replace(run, attempt_id=attempt_id) for run in runs]


def _number(value: object, field: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool) or not isfinite(value) or value < 0:
        raise BudgetError(f"budget entry {field} must be a non-negative number")
    return float(value)


def _entry(value: object) -> BudgetEntry:
    if not isinstance(value, dict):
        raise BudgetError("budget entries must be objects")
    attempt_id = value.get("attempt_id")
    run_id = value.get("run_id")
    phase = value.get("phase")
    state = value.get("state")
    if not isinstance(attempt_id, str) or not attempt_id:
        raise BudgetError("budget entry attempt_id must be a non-empty string")
    if not isinstance(run_id, str) or not run_id:
        raise BudgetError("budget entry run_id must be a non-empty string")
    if phase not in ("smoke", "measured"):
        raise BudgetError("budget entry phase must be smoke or measured")
    if state not in ("reserved", "completed", "cancelled"):
        raise BudgetError("budget entry state is invalid")
    observed = value.get("observed_usd")
    return BudgetEntry(
        attempt_id=attempt_id,
        run_id=run_id,
        phase=cast(Phase, phase),
        state=state,
        reserved_usd=_number(value.get("reserved_usd"), "reserved_usd"),
        observed_usd=None if observed is None else _number(observed, "observed_usd"),
    )


def _seed_entries(results_path: Path) -> list[BudgetEntry]:
    if not results_path.exists():
        return []
    try:
        document = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BudgetError(f"cannot seed budget from results: {error}") from error
    if not isinstance(document, dict) or not isinstance(document.get("runs"), list):
        raise BudgetError("cannot seed budget from malformed normalized results")

    entries: list[BudgetEntry] = []
    for index, run in enumerate(document["runs"]):
        if not isinstance(run, dict):
            raise BudgetError(f"normalized result run {index} must be an object")
        phase = run.get("phase")
        attempt_id = run.get("attempt_id")
        run_id = run.get("run_id")
        if phase not in ("smoke", "measured") or not isinstance(attempt_id, str) or not isinstance(run_id, str):
            continue
        usage = run.get("model_usage")
        observed = 0.0
        if isinstance(usage, dict):
            for model_usage in usage.values():
                if isinstance(model_usage, dict):
                    cost = model_usage.get("total_cost")
                    if isinstance(cost, int | float) and not isinstance(cost, bool):
                        observed += _number(cost, "normalized total_cost")
        entries.append(
            BudgetEntry(
                attempt_id=attempt_id,
                run_id=run_id,
                phase=cast(Phase, phase),
                state="completed",
                reserved_usd=0.0,
                observed_usd=observed,
            )
        )
    return entries


def _reconcile_entries(entries: list[BudgetEntry], observed_entries: list[BudgetEntry]) -> list[BudgetEntry]:
    """Replace reservations with matching normalized provider observations."""
    observed_by_run = {(entry.attempt_id, entry.run_id): entry for entry in observed_entries}
    reconciled: list[BudgetEntry] = []
    existing_keys: set[tuple[str, str]] = set()
    for entry in entries:
        key = (entry.attempt_id, entry.run_id)
        existing_keys.add(key)
        reconciled.append(observed_by_run.get(key, entry))
    reconciled.extend(entry for entry in observed_entries if (entry.attempt_id, entry.run_id) not in existing_keys)
    return reconciled


def load_budget(config: ExperimentConfig) -> list[BudgetEntry]:
    """Load the local budget ledger, seeding it from retained results if absent."""
    path = config.resolve(config.experiment.budget_path)
    if not path.exists():
        return _seed_entries(config.resolve(config.experiment.results_path))
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BudgetError(f"cannot read budget ledger: {error}") from error
    if not isinstance(document, dict):
        raise BudgetError("budget ledger must be a JSON object")
    if document.get("schema_version") != BUDGET_SCHEMA_VERSION:
        raise BudgetError("budget ledger has an unsupported schema_version")
    if document.get("experiment_id") != config.experiment.id:
        raise BudgetError("budget ledger belongs to a different experiment")
    raw_entries = document.get("entries")
    if not isinstance(raw_entries, list):
        raise BudgetError("budget ledger entries must be an array")
    entries = [_entry(value) for value in raw_entries]
    observed_entries = _seed_entries(config.resolve(config.experiment.results_path))
    return _reconcile_entries(entries, observed_entries)


def _write_budget(config: ExperimentConfig, entries: list[BudgetEntry]) -> None:
    path = config.resolve(config.experiment.budget_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document: JsonObject = {
        "schema_version": BUDGET_SCHEMA_VERSION,
        "experiment_id": config.experiment.id,
        "entries": [entry.to_json() for entry in entries],
    }
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _lock_file(file: BinaryIO) -> None:
    file.seek(0, os.SEEK_END)
    if file.tell() == 0:
        file.write(b"\0")
        file.flush()
    file.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl = cast(_FcntlModule, import_module("fcntl"))

            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        raise BudgetError("another process is updating the budget ledger") from error


def _unlock_file(file: BinaryIO) -> None:
    file.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl = cast(_FcntlModule, import_module("fcntl"))

        fcntl.flock(file.fileno(), fcntl.LOCK_UN)


@contextmanager
def _budget_lock(config: ExperimentConfig) -> Iterator[None]:
    path = config.resolve(config.experiment.budget_path).with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as file:
        _lock_file(file)
        try:
            yield
        finally:
            _unlock_file(file)


def budget_summary(config: ExperimentConfig) -> BudgetSummary:
    """Summarize observed and unresolved budget commitments."""
    entries = load_budget(config)
    return BudgetSummary(
        observed_usd=sum(entry.observed_usd or 0.0 for entry in entries if entry.state == "completed"),
        reserved_usd=sum(entry.reserved_usd for entry in entries if entry.state == "reserved"),
        ceiling_usd=config.limits.experiment_cost_limit_usd,
    )


def reserve_attempt(
    config: ExperimentConfig,
    runs: list[PlannedRun],
    attempt_id: str,
) -> None:
    """Reserve every planned run before a paid attempt begins."""
    with _budget_lock(config):
        entries = load_budget(config)
        if any(entry.attempt_id == attempt_id for entry in entries):
            raise BudgetError(f"budget attempt already exists: {attempt_id}")
        requested = len(runs) * config.limits.cost_limit_usd
        committed = sum(entry.committed_usd for entry in entries)
        ceiling = config.limits.experiment_cost_limit_usd
        if committed + requested > ceiling + 1e-9:
            raise BudgetError(
                f"committed ${committed:.2f} plus requested ${requested:.2f} exceeds experiment ceiling ${ceiling:.2f}"
            )
        entries.extend(
            BudgetEntry(
                attempt_id=attempt_id,
                run_id=run.run_id,
                phase=run.phase,
                state="reserved",
                reserved_usd=config.limits.cost_limit_usd,
            )
            for run in runs
        )
        _write_budget(config, entries)


def complete_run(config: ExperimentConfig, attempt_id: str, run_id: str, observed_usd: float) -> None:
    """Replace one reservation with provider-observed cost."""
    observed_usd = _number(observed_usd, "observed_usd")
    with _budget_lock(config):
        entries = load_budget(config)
        updated = False
        result: list[BudgetEntry] = []
        for entry in entries:
            if entry.attempt_id == attempt_id and entry.run_id == run_id:
                if entry.state != "reserved":
                    raise BudgetError(f"budget entry is not reserved: {attempt_id}/{run_id}")
                result.append(replace(entry, state="completed", observed_usd=observed_usd))
                updated = True
            else:
                result.append(entry)
        if not updated:
            raise BudgetError(f"missing budget reservation: {attempt_id}/{run_id}")
        _write_budget(config, result)


def cancel_reservations(config: ExperimentConfig, attempt_id: str) -> None:
    """Release unlaunched reservations after a handled terminal failure."""
    with _budget_lock(config):
        entries = load_budget(config)
        result = [
            replace(entry, state="cancelled") if entry.attempt_id == attempt_id and entry.state == "reserved" else entry
            for entry in entries
        ]
        _write_budget(config, result)
