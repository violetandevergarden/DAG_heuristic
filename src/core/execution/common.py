"""Small immutable scheduler-facing contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SchedulerTaskView:
    task_id: str
    kind: str
    status: str
    remaining: int
    resources: frozenset[str] = frozenset()


@dataclass(frozen=True)
class SchedulerView:
    """Read-only stable state exposed to a scheduling policy."""

    time: int
    eligible_communications: tuple[str, ...]
    active_computes: tuple[str, ...]
    tasks: tuple[SchedulerTaskView, ...]


class ExecutionContractError(ValueError):
    """Base class for reproducible execution-contract failures."""


class IllegalActionError(ExecutionContractError):
    """A scheduler returned an action outside the legal action set."""


class DeadlockError(ExecutionContractError):
    """An unfinished state has no eligible work and no future event."""
