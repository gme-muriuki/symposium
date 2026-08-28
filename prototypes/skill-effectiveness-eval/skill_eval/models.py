"""Shared records and structural interfaces for the evaluation prototype."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from subprocess import CompletedProcess
from typing import Literal, Protocol

type Condition = Literal["baseline", "symposium"]
type Phase = Literal["smoke", "measured"]
type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]

CONDITION_NAMES: tuple[Condition, ...] = ("baseline", "symposium")
PHASE_NAMES: tuple[Phase, ...] = ("smoke", "measured")


@dataclass(frozen=True)
class PlannedRun:
    """One condition execution within a paired experiment."""

    run_id: str
    phase: Phase
    pair: int
    order: int
    condition: Condition
    skills: tuple[str, ...]
    attempt_id: str | None = None


@dataclass(frozen=True)
class ControlEvidence:
    """Current trust state for the deterministic grader controls."""

    passed: bool
    reason: str | None = None
    fingerprint: str | None = None
    generated_at: str | None = None
    details: Mapping[str, JsonValue] | None = None

    def to_json(self) -> JsonObject:
        """Return the stable JSON representation used in plans and results."""
        document: JsonObject = {"passed": self.passed}
        if self.reason is not None:
            document["reason"] = self.reason
        if self.fingerprint is not None:
            document["fingerprint"] = self.fingerprint
        if self.generated_at is not None:
            document["generated_at"] = self.generated_at
        if self.details is not None:
            document.update(self.details)
        return document


@dataclass(frozen=True)
class BudgetEntry:
    """One paid run's reservation or observed cost."""

    attempt_id: str
    run_id: str
    phase: Phase
    state: Literal["reserved", "completed", "cancelled"]
    reserved_usd: float
    observed_usd: float | None = None

    @property
    def committed_usd(self) -> float:
        """Return the amount this entry commits against the experiment ceiling."""
        if self.state == "completed":
            return self.observed_usd or 0.0
        if self.state == "reserved":
            return self.reserved_usd
        return 0.0

    def to_json(self) -> JsonObject:
        """Return the ledger representation of this entry."""
        return {
            "attempt_id": self.attempt_id,
            "run_id": self.run_id,
            "phase": self.phase,
            "state": self.state,
            "reserved_usd": self.reserved_usd,
            "observed_usd": self.observed_usd,
        }


@dataclass(frozen=True)
class BudgetSummary:
    """A read-only view of experiment-wide budget commitments."""

    observed_usd: float
    reserved_usd: float
    ceiling_usd: float

    @property
    def committed_usd(self) -> float:
        """Return observed spend plus unresolved reservations."""
        return self.observed_usd + self.reserved_usd

    @property
    def remaining_usd(self) -> float:
        """Return the uncommitted portion of the experiment ceiling."""
        return max(0.0, self.ceiling_usd - self.committed_usd)

    def to_json(self) -> JsonObject:
        """Return the stable plan representation."""
        return {
            "observed_usd": self.observed_usd,
            "reserved_usd": self.reserved_usd,
            "committed_usd": self.committed_usd,
            "ceiling_usd": self.ceiling_usd,
            "remaining_usd": self.remaining_usd,
        }


class CommandRunner(Protocol):
    """Structural interface for checked subprocess execution."""

    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        check: bool,
    ) -> CompletedProcess[bytes]: ...
