"""Event-driven model where communication may pause and resume.

Compute tasks start automatically and remain non-preemptive.  A dispatched
communication runs until it completes or until the next compute completion.
At that event the scheduler may continue it or switch to another eligible
communication. Pausing releases the channel and preserves progress. Forced
idle is represented by WAIT only when no communication is eligible.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

from core.dag import BenchmarkDAG, topological_order
from core.execution.common import (
    DeadlockError,
    IllegalActionError,
    SchedulerTaskView,
    SchedulerView,
)

TaskStatus = Literal["pending", "running", "suspended", "completed"]
ActionKind = Literal["run", "wait"]


@dataclass(frozen=True)
class RuntimeTask:
    status: TaskStatus = "pending"
    remaining: int = 0
    started_at: int | None = None
    completed_at: int | None = None


@dataclass(frozen=True)
class ScheduleState:
    """Stable state at a task event, before the next dispatch decision."""

    time: int
    tasks: tuple[RuntimeTask, ...]
    last_communication: str | None = None


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    task_id: str | None = None

    @classmethod
    def run(cls, task_id: str) -> Action:
        return cls("run", task_id)

    @classmethod
    def wait(cls) -> Action:
        return cls("wait")


@dataclass(frozen=True)
class TimelineEvent:
    time: int
    kind: str
    task_id: str


@dataclass(frozen=True)
class ExecutionInterval:
    task_id: str
    kind: Literal["compute", "comm"]
    start: int
    end: int


@dataclass(frozen=True)
class Transition:
    action: Action
    before: ScheduleState
    after: ScheduleState
    events: tuple[TimelineEvent, ...]
    intervals: tuple[ExecutionInterval, ...]


@dataclass(frozen=True)
class ScheduleTrace:
    final_state: ScheduleState
    transitions: tuple[Transition, ...]
    events: tuple[TimelineEvent, ...]
    intervals: tuple[ExecutionInterval, ...]
    task_ids: tuple[str, ...]

    @property
    def makespan(self) -> int:
        return self.final_state.time


@dataclass(frozen=True)
class PreemptiveScheduleResult:
    makespan: int
    trace: ScheduleTrace
    dispatches: int
    preemptions: int
    explored_states: int = 0
    generated_transitions: int = 0
    deduplicated_states: int = 0
    pruned_states: int = 0
    incumbent_prunes: int = 0
    lower_bound_prunes: int = 0
    peak_states: int = 0
    lower_bound: int = 0
    runtime_ms: float = 0.0
    status: Literal["feasible", "optimal"] = "feasible"
    termination_reason: str | None = None
    expanded_nodes: int = 0
    evaluated_candidates: int = 0
    fallback_count: int = 0


class PreemptiveDAGModel:
    """Single-channel, zero-cost communication pause/resume state machine."""

    def __init__(self, dag: BenchmarkDAG):
        errors = dag.validate()
        if errors:
            raise ValueError(f"invalid benchmark DAG {dag.name}: {errors}")
        if any(task.kind == "comm" and task.duration <= 0 for task in dag.tasks):
            raise ValueError("preemptive model requires positive communication durations")
        order = topological_order(dag)
        task_map = dag.task_map()
        self.dag = dag
        self.task_ids = tuple(order)
        self.tasks = tuple(task_map[task_id] for task_id in order)
        self.index = {task_id: index for index, task_id in enumerate(order)}
        self.deps = tuple(tuple(self.index[parent] for parent in task.deps) for task in self.tasks)

    def initial_state(self) -> ScheduleState:
        state = ScheduleState(0, tuple(RuntimeTask() for _ in self.tasks))
        state, _events, _intervals = self._start_ready_computes(state)
        return state

    def initial_events(self, state: ScheduleState) -> tuple[TimelineEvent, ...]:
        events: list[TimelineEvent] = []
        for task, runtime in zip(self.tasks, state.tasks, strict=True):
            if task.kind != "compute" or runtime.started_at != 0:
                continue
            events.append(TimelineEvent(0, "compute_started", task.task_id))
            if runtime.completed_at == 0:
                events.append(TimelineEvent(0, "compute_completed", task.task_id))
        return tuple(self._sort_events(events))

    def initial_intervals(self, state: ScheduleState) -> tuple[ExecutionInterval, ...]:
        return tuple(
            ExecutionInterval(task.task_id, "compute", 0, 0)
            for task, runtime in zip(self.tasks, state.tasks, strict=True)
            if task.kind == "compute" and runtime.completed_at == 0
        )

    def task_runtime(self, state: ScheduleState, task_id: str) -> RuntimeTask:
        return state.tasks[self.index[task_id]]

    def eligible_communications(self, state: ScheduleState) -> tuple[str, ...]:
        eligible = []
        for index, task in enumerate(self.tasks):
            runtime = state.tasks[index]
            if task.kind != "comm" or runtime.status == "completed":
                continue
            if runtime.status == "suspended" or self._deps_completed(state.tasks, index):
                eligible.append(task.task_id)
        return tuple(eligible)

    def active_computes(self, state: ScheduleState) -> tuple[str, ...]:
        return tuple(
            task.task_id
            for task, runtime in zip(self.tasks, state.tasks, strict=True)
            if task.kind == "compute" and runtime.status == "running"
        )

    def legal_actions(self, state: ScheduleState) -> tuple[Action, ...]:
        eligible = self.eligible_communications(state)
        if eligible:
            return tuple(Action.run(task_id) for task_id in eligible)
        if self.active_computes(state):
            return (Action.wait(),)
        return ()

    def scheduler_view(self, state: ScheduleState) -> SchedulerView:
        """Return an immutable snapshot containing no benchmark metadata."""

        return SchedulerView(
            state.time,
            self.eligible_communications(state),
            self.active_computes(state),
            tuple(
                SchedulerTaskView(
                    task.task_id,
                    task.kind,
                    runtime.status,
                    runtime.remaining,
                    frozenset({"channel:0"}) if task.kind == "comm" else frozenset(),
                )
                for task, runtime in zip(self.tasks, state.tasks, strict=True)
            ),
        )

    def is_finished(self, state: ScheduleState) -> bool:
        return all(runtime.status == "completed" for runtime in state.tasks)

    def step(self, state: ScheduleState, action: Action) -> Transition:
        if action not in self.legal_actions(state):
            eligible = self.eligible_communications(state)
            active = self.active_computes(state)
            if action.kind == "wait" and eligible:
                reason = "voluntary WAIT is forbidden while communication is eligible"
            elif not eligible and not active and not self.is_finished(state):
                reason = "unfinished state has no future event (deadlock)"
            else:
                reason = "action is not legal in the current stable state"
            error_type = DeadlockError if "deadlock" in reason else IllegalActionError
            raise error_type(
                f"{reason} at t={state.time}: action={action}, "
                f"eligible={eligible}, active_compute={active}"
            )
        if action.kind == "wait":
            return self._wait(state, action)
        assert action.task_id is not None
        return self._dispatch(state, action)

    def run(self, actions: Sequence[Action]) -> ScheduleTrace:
        state = self.initial_state()
        transitions: list[Transition] = []
        events = list(self.initial_events(state))
        intervals = list(self.initial_intervals(state))
        for action in actions:
            transition = self.step(state, action)
            transitions.append(transition)
            events.extend(transition.events)
            intervals.extend(transition.intervals)
            state = transition.after
        return ScheduleTrace(
            state,
            tuple(transitions),
            tuple(self._sort_events(events)),
            tuple(intervals),
            self.task_ids,
        )

    def _dispatch(self, state: ScheduleState, action: Action) -> Transition:
        task_id = action.task_id
        assert task_id is not None
        index = self.index[task_id]
        runtime = state.tasks[index]
        remaining = runtime.remaining or self.tasks[index].duration
        running_computes = self._running_compute_indices(state)
        next_compute = min((state.tasks[item].remaining for item in running_computes), default=None)
        delta = remaining if next_compute is None else min(remaining, next_compute)
        start = state.time
        end = start + delta

        values = list(state.tasks)
        first_start = runtime.started_at if runtime.started_at is not None else start
        values[index] = RuntimeTask("running", remaining, first_start, None)
        working = ScheduleState(start, tuple(values), task_id)
        event_kind = (
            "communication_started" if runtime.started_at is None else "communication_resumed"
        )
        events = [TimelineEvent(start, event_kind, task_id)]
        working, compute_events, compute_intervals = self._advance_computes(working, delta)
        events.extend(compute_events)

        values = list(working.tasks)
        comm_runtime = values[index]
        if comm_runtime.remaining == 0:
            values[index] = RuntimeTask("completed", 0, first_start, end)
            events.append(TimelineEvent(end, "communication_completed", task_id))
        else:
            values[index] = RuntimeTask("suspended", comm_runtime.remaining, first_start, None)
            events.append(TimelineEvent(end, "communication_paused", task_id))
        working = ScheduleState(end, tuple(values), task_id)
        working, start_events, start_intervals = self._start_ready_computes(working)
        events.extend(start_events)
        intervals = [ExecutionInterval(task_id, "comm", start, end)]
        intervals.extend(compute_intervals)
        intervals.extend(start_intervals)
        return Transition(
            action, state, working, tuple(self._sort_events(events)), tuple(intervals)
        )

    def _wait(self, state: ScheduleState, action: Action) -> Transition:
        running = self._running_compute_indices(state)
        if not running:
            raise ValueError("WAIT requires a future compute completion")
        delta = min(state.tasks[index].remaining for index in running)
        after, events, intervals = self._advance_computes(state, delta)
        return Transition(action, state, after, tuple(events), tuple(intervals))

    def _advance_computes(
        self, state: ScheduleState, delta: int
    ) -> tuple[ScheduleState, list[TimelineEvent], list[ExecutionInterval]]:
        if delta <= 0:
            raise ValueError("time advancement must be positive")
        end = state.time + delta
        values = list(state.tasks)
        events: list[TimelineEvent] = []
        intervals: list[ExecutionInterval] = []
        for index in self._running_compute_indices(state):
            runtime = values[index]
            remaining = runtime.remaining - delta
            if remaining == 0:
                values[index] = RuntimeTask("completed", 0, runtime.started_at, end)
                task_id = self.tasks[index].task_id
                events.append(TimelineEvent(end, "compute_completed", task_id))
                assert runtime.started_at is not None
                intervals.append(ExecutionInterval(task_id, "compute", runtime.started_at, end))
            else:
                values[index] = RuntimeTask("running", remaining, runtime.started_at, None)
        if state.last_communication is not None:
            index = self.index[state.last_communication]
            runtime = values[index]
            if runtime.status == "running":
                values[index] = RuntimeTask(
                    "running", runtime.remaining - delta, runtime.started_at, None
                )
        advanced = ScheduleState(end, tuple(values), state.last_communication)
        advanced, start_events, start_intervals = self._start_ready_computes(advanced)
        events.extend(start_events)
        intervals.extend(start_intervals)
        return advanced, self._sort_events(events), intervals

    def _start_ready_computes(
        self, state: ScheduleState
    ) -> tuple[ScheduleState, list[TimelineEvent], list[ExecutionInterval]]:
        values = list(state.tasks)
        events: list[TimelineEvent] = []
        intervals: list[ExecutionInterval] = []
        changed = True
        while changed:
            changed = False
            for index, task in enumerate(self.tasks):
                if task.kind != "compute" or values[index].status != "pending":
                    continue
                if not self._deps_completed(values, index):
                    continue
                events.append(TimelineEvent(state.time, "compute_started", task.task_id))
                if task.duration == 0:
                    values[index] = RuntimeTask("completed", 0, state.time, state.time)
                    events.append(TimelineEvent(state.time, "compute_completed", task.task_id))
                    intervals.append(
                        ExecutionInterval(task.task_id, "compute", state.time, state.time)
                    )
                else:
                    values[index] = RuntimeTask("running", task.duration, state.time, None)
                changed = True
        return (
            ScheduleState(state.time, tuple(values), state.last_communication),
            self._sort_events(events),
            intervals,
        )

    def _deps_completed(self, runtimes: Sequence[RuntimeTask], index: int) -> bool:
        return all(runtimes[parent].status == "completed" for parent in self.deps[index])

    def _running_compute_indices(self, state: ScheduleState) -> list[int]:
        return [
            index
            for index, (task, runtime) in enumerate(zip(self.tasks, state.tasks, strict=True))
            if task.kind == "compute" and runtime.status == "running"
        ]

    @staticmethod
    def _sort_events(events: list[TimelineEvent]) -> list[TimelineEvent]:
        order = {
            "compute_completed": 0,
            "communication_completed": 1,
            "communication_paused": 2,
            "compute_started": 3,
            "communication_started": 4,
            "communication_resumed": 5,
        }
        return sorted(events, key=lambda event: (event.time, order[event.kind], event.task_id))


def result_from_trace(trace: ScheduleTrace) -> PreemptiveScheduleResult:
    communications = [span for span in trace.intervals if span.kind == "comm"]
    by_task: dict[str, list[ExecutionInterval]] = {}
    for span in communications:
        by_task.setdefault(span.task_id, []).append(span)
    preemptions = 0
    for spans in by_task.values():
        spans.sort(key=lambda item: (item.start, item.end))
        preemptions += sum(
            current.start > previous.end for previous, current in pairwise(spans)
        )
    return PreemptiveScheduleResult(trace.makespan, trace, len(communications), preemptions)
