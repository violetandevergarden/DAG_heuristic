"""Small immutable scheduler-facing contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

StateT = TypeVar("StateT")
ActionT = TypeVar("ActionT")


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
    active_communications: tuple[str, ...] = ()
    available_resources: frozenset[str] = frozenset()
    can_wait: bool = False


class ExecutionContractError(ValueError):
    """Base class for reproducible execution-contract failures."""


class IllegalActionError(ExecutionContractError):
    """A scheduler returned an action outside the legal action set."""


class DeadlockError(ExecutionContractError):
    """An unfinished state has no eligible work and no future event."""


@dataclass(frozen=True)
class RuntimeTask:
    status: str = "pending"
    remaining: int = 0
    started_at: int | None = None
    completed_at: int | None = None


@dataclass(frozen=True)
class Action:
    kind: str
    task_id: str | None = None

    @classmethod
    def flow(cls, task_id: str) -> "Action":
        return cls("flow", task_id)

    @classmethod
    def run(cls, task_id: str) -> "Action":
        return cls("run", task_id)

    @classmethod
    def wait(cls) -> "Action":
        return cls("wait")


@dataclass(frozen=True)
class TimelineEvent:
    time: int
    kind: str
    task_id: str


@dataclass(frozen=True)
class ExecutionInterval:
    task_id: str
    kind: str
    start: int
    end: int


@dataclass(frozen=True)
class Transition(Generic[StateT, ActionT]):
    action: ActionT
    before: StateT
    after: StateT
    events: tuple[TimelineEvent, ...]
    intervals: tuple[ExecutionInterval, ...]


@dataclass(frozen=True)
class ExecutionTrace(Generic[StateT]):
    final_state: StateT
    events: tuple[TimelineEvent, ...]
    intervals: tuple[ExecutionInterval, ...]
    task_ids: tuple[str, ...]

    @property
    def makespan(self) -> int:
        return self.final_state.time


@dataclass(frozen=True)
class ScheduleTrace(ExecutionTrace[StateT], Generic[StateT, ActionT]):
    transitions: tuple[Transition[StateT, ActionT], ...] = ()


@dataclass(frozen=True)
class ExecutionResult:
    """The complete, solver-independent result of executing a schedule."""

    trace: ExecutionTrace
    dispatches: int = 0
    preemptions: int = 0

    @property
    def makespan(self) -> int:
        return self.trace.makespan


EVENT_PRIORITY = {
    "compute_completed": 0,
    "flow_completed": 1,
    "communication_completed": 1,
    "communication_paused": 2,
    "compute_started": 3,
    "flow_started": 3,
    "communication_started": 4,
    "communication_resumed": 5,
}


def sort_events(
    events: list[TimelineEvent], *, preemptive: bool = False
) -> list[TimelineEvent]:
    priority = dict(EVENT_PRIORITY)
    if preemptive:
        priority.update(
            {
                "compute_started": 3,
                "communication_started": 4,
                "communication_resumed": 5,
            }
        )
    else:
        priority.update({"compute_started": 2, "flow_started": 3})
    return sorted(
        events,
        key=lambda event: (event.time, priority[event.kind], event.task_id),
    )
