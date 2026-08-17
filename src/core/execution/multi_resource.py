"""Fixed-resource preemptive event execution shared by Stage 3 algorithms.

The model owns action validation, task-event advancement, compute closure and
forced idle.  Schedulers only choose a non-empty inclusion-maximal compatible
set at stable decision boundaries.  Communications never retain resource
ownership across a boundary; selecting one again means immediate resume.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from core.dag import BenchmarkDAG, topological_order
from core.execution.common import (
    DeadlockError,
    IllegalActionError,
    SchedulerTaskView,
    SchedulerView,
)
from core.execution.preemptive import ExecutionInterval, TimelineEvent
from core.trace.common import ForcedIdleInterval, ResourceInterval


@dataclass(frozen=True)
class MultiRuntimeTask:
    status: str = "pending"
    remaining: int = 0


@dataclass(frozen=True)
class MultiResourceState:
    time: int
    tasks: tuple[MultiRuntimeTask, ...]
    active_allocations: tuple[str, ...] = ()
    resource_owners: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class MultiResourceAction:
    communications: tuple[str, ...] = ()


@dataclass(frozen=True)
class MultiResourceDecision:
    start: int
    end: int
    action: MultiResourceAction


@dataclass(frozen=True)
class MultiResourceTrace:
    final_state: MultiResourceState
    decisions: tuple[MultiResourceDecision, ...]
    events: tuple[TimelineEvent, ...]
    intervals: tuple[ExecutionInterval, ...]
    resource_intervals: tuple[ResourceInterval, ...]
    forced_idle: tuple[ForcedIdleInterval, ...]
    task_ids: tuple[str, ...]

    @property
    def makespan(self) -> int:
        return self.final_state.time


class PreemptiveMultiResourceModel:
    """Stable-boundary fixed-resource event simulator.

    A stable state has no active communication allocation.  Running compute
    tasks are represented in ``tasks`` and continue across decisions.
    """

    def __init__(self, dag: BenchmarkDAG, resources: dict[str, frozenset[str]]):
        errors = dag.validate()
        if errors:
            raise ValueError(f"invalid DAG: {errors}")
        order = topological_order(dag)
        task_map = dag.task_map()
        self.dag = dag
        self.task_ids = tuple(order)
        self.tasks = tuple(task_map[item] for item in order)
        self.task_map = task_map
        self.index = {item: index for index, item in enumerate(order)}
        self.deps = tuple(
            tuple(self.index[parent] for parent in task.deps) for task in self.tasks
        )
        comm_ids = {task.task_id for task in self.tasks if task.kind == "comm"}
        if set(resources) != comm_ids or any(not resources[item] for item in comm_ids):
            raise ValueError("every communication must have a non-empty fixed resource set")
        if any(task.kind == "comm" and task.duration <= 0 for task in self.tasks):
            raise ValueError("preemptive model requires positive communication durations")
        self.resources = {
            task_id: frozenset(resource_set)
            for task_id, resource_set in resources.items()
        }
        child_lists: dict[str, list[str]] = {task_id: [] for task_id in self.task_ids}
        for task in self.tasks:
            for parent in task.deps:
                child_lists[parent].append(task.task_id)
        self.children = {task_id: tuple(values) for task_id, values in child_lists.items()}

    def initial_state(self) -> MultiResourceState:
        return self._compute_closure(
            MultiResourceState(0, tuple(MultiRuntimeTask() for _ in self.tasks))
        )

    def eligible(self, state: MultiResourceState) -> tuple[str, ...]:
        result = []
        for index, task in enumerate(self.tasks):
            runtime = state.tasks[index]
            if task.kind != "comm" or runtime.status == "completed":
                continue
            if runtime.status == "suspended" or self._deps_completed(state.tasks, index):
                result.append(task.task_id)
        return tuple(result)

    def active_computes(self, state: MultiResourceState) -> tuple[int, ...]:
        return tuple(
            index
            for index, (task, runtime) in enumerate(
                zip(self.tasks, state.tasks, strict=True)
            )
            if task.kind == "compute" and runtime.status == "running"
        )

    def compatible(self, items: Iterable[str]) -> bool:
        used: set[str] = set()
        for item in items:
            if item not in self.resources or used & self.resources[item]:
                return False
            used.update(self.resources[item])
        return True

    def maximal_actions(
        self, state: MultiResourceState
    ) -> tuple[MultiResourceAction, ...]:
        """Enumerate maximal compatible sets via maximal cliques.

        Vertices are eligible communications and edges denote compatibility.
        Bron--Kerbosch enumerates maximal cliques directly, avoiding the old
        generate-all-subsets-then-filter implementation.
        """

        eligible = self.eligible(state)
        if not eligible:
            return ()
        neighbors = {
            item: {
                other
                for other in eligible
                if other != item and self.resources[item].isdisjoint(self.resources[other])
            }
            for item in eligible
        }
        maximal: list[tuple[str, ...]] = []

        def visit(chosen: set[str], candidates: set[str], excluded: set[str]) -> None:
            if not candidates and not excluded:
                maximal.append(tuple(sorted(chosen)))
                return
            pivot_pool = candidates | excluded
            pivot = max(
                pivot_pool,
                key=lambda item: (len(candidates & neighbors[item]), item),
                default=None,
            )
            branch = candidates - (neighbors[pivot] if pivot is not None else set())
            for item in sorted(branch):
                visit(
                    chosen | {item},
                    candidates & neighbors[item],
                    excluded & neighbors[item],
                )
                candidates.remove(item)
                excluded.add(item)

        visit(set(), set(eligible), set())
        return tuple(MultiResourceAction(items) for items in sorted(set(maximal)))

    def legal_actions(
        self, state: MultiResourceState
    ) -> tuple[MultiResourceAction, ...]:
        return self.maximal_actions(state)

    def scheduler_view(self, state: MultiResourceState) -> SchedulerView:
        return SchedulerView(
            state.time,
            self.eligible(state),
            tuple(self.tasks[index].task_id for index in self.active_computes(state)),
            tuple(
                SchedulerTaskView(
                    task.task_id,
                    task.kind,
                    runtime.status,
                    runtime.remaining,
                    self.resources.get(task.task_id, frozenset()),
                )
                for task, runtime in zip(self.tasks, state.tasks, strict=True)
            ),
        )

    def step(
        self, state: MultiResourceState, action: MultiResourceAction
    ) -> MultiResourceState:
        self._assert_stable_boundary(state)
        selected = action.communications
        eligible = self.eligible(state)
        if len(selected) != len(set(selected)):
            raise IllegalActionError(
                f"duplicate communication at t={state.time}: action={action}"
            )
        if tuple(sorted(selected)) != selected:
            raise IllegalActionError(
                f"multi-resource action must use stable sorted IDs at t={state.time}: {action}"
            )
        if action not in self.legal_actions(state):
            if not selected:
                reason = "forced idle is simulator-owned; empty scheduler actions are forbidden"
            elif set(selected) <= set(eligible) and self.compatible(selected):
                reason = "compatible action is not inclusion-maximal"
            else:
                reason = "illegal multi-resource action"
            raise IllegalActionError(
                f"{reason} at t={state.time}: action={action}, eligible={eligible}"
            )
        return self._advance(state, selected)

    def advance_forced_idle(
        self, state: MultiResourceState
    ) -> tuple[MultiResourceState, ForcedIdleInterval | None]:
        """Advance a dependency-caused idle interval without a scheduler action."""

        self._assert_stable_boundary(state)
        if self.eligible(state) or self.finished(state):
            return state, None
        if not self.active_computes(state):
            raise DeadlockError(f"unfinished state has no future event at t={state.time}")
        after = self._advance(state, ())
        return after, ForcedIdleInterval(state.time, after.time)

    def normalize_decision_state(
        self, state: MultiResourceState
    ) -> tuple[MultiResourceState, tuple[ForcedIdleInterval, ...]]:
        intervals: list[ForcedIdleInterval] = []
        while not self.finished(state) and not self.eligible(state):
            state, interval = self.advance_forced_idle(state)
            assert interval is not None
            intervals.append(interval)
        return state, tuple(intervals)

    def run(self, actions: Sequence[MultiResourceAction]) -> MultiResourceTrace:
        state = self.initial_state()
        decisions: list[MultiResourceDecision] = []
        raw_intervals: list[ExecutionInterval] = []
        forced_idle: list[ForcedIdleInterval] = []
        for action in actions:
            while not self.finished(state) and not self.eligible(state):
                before_idle = state
                active_compute_ids = tuple(
                    self.tasks[index].task_id
                    for index in self.active_computes(before_idle)
                )
                state, interval = self.advance_forced_idle(before_idle)
                assert interval is not None
                forced_idle.append(interval)
                for task_id in active_compute_ids:
                    raw_intervals.append(
                        ExecutionInterval(
                            task_id, "compute", before_idle.time, state.time
                        )
                    )
            before = state
            active_compute_ids = tuple(
                self.tasks[index].task_id for index in self.active_computes(before)
            )
            state = self.step(before, action)
            decisions.append(MultiResourceDecision(before.time, state.time, action))
            for task_id in active_compute_ids:
                raw_intervals.append(
                    ExecutionInterval(task_id, "compute", before.time, state.time)
                )
            for task_id in action.communications:
                raw_intervals.append(
                    ExecutionInterval(task_id, "comm", before.time, state.time)
                )
        while not self.finished(state) and not self.eligible(state):
            before = state
            active_compute_ids = tuple(
                self.tasks[index].task_id for index in self.active_computes(before)
            )
            state, interval = self.advance_forced_idle(before)
            assert interval is not None
            forced_idle.append(interval)
            for task_id in active_compute_ids:
                raw_intervals.append(
                    ExecutionInterval(task_id, "compute", before.time, state.time)
                )
        if not self.finished(state):
            raise ValueError("action sequence does not complete every task")
        intervals = _complete_zero_compute_intervals(
            self, _merge_intervals(raw_intervals)
        )
        resource_intervals = tuple(
            ResourceInterval(resource, interval.task_id, interval.start, interval.end)
            for interval in intervals
            if interval.kind == "comm"
            for resource in sorted(self.resources[interval.task_id])
        )
        return MultiResourceTrace(
            state,
            tuple(decisions),
            _events_from_intervals(intervals),
            intervals,
            resource_intervals,
            tuple(forced_idle),
            self.task_ids,
        )

    def finished(self, state: MultiResourceState) -> bool:
        return all(item.status == "completed" for item in state.tasks)

    def _advance(
        self, state: MultiResourceState, selected: tuple[str, ...]
    ) -> MultiResourceState:
        self._assert_stable_boundary(state)
        deltas = [state.tasks[index].remaining for index in self.active_computes(state)]
        for task_id in selected:
            runtime = state.tasks[self.index[task_id]]
            deltas.append(runtime.remaining or self.tasks[self.index[task_id]].duration)
        if not deltas:
            raise DeadlockError(f"state cannot advance at t={state.time}")
        delta = min(deltas)
        values = list(state.tasks)
        for index in self.active_computes(state):
            remaining = values[index].remaining - delta
            values[index] = MultiRuntimeTask(
                "completed" if remaining == 0 else "running", remaining
            )
        for task_id in selected:
            index = self.index[task_id]
            runtime = values[index]
            remaining = (runtime.remaining or self.tasks[index].duration) - delta
            values[index] = MultiRuntimeTask(
                "completed" if remaining == 0 else "suspended", remaining
            )
        return self._compute_closure(
            MultiResourceState(state.time + delta, tuple(values))
        )

    def _compute_closure(self, state: MultiResourceState) -> MultiResourceState:
        values = list(state.tasks)
        changed = True
        while changed:
            changed = False
            for index, task in enumerate(self.tasks):
                if task.kind != "compute" or values[index].status != "pending":
                    continue
                if self._deps_completed(values, index):
                    values[index] = MultiRuntimeTask(
                        "completed" if task.duration == 0 else "running", task.duration
                    )
                    changed = True
        return MultiResourceState(
            state.time,
            tuple(values),
            state.active_allocations,
            state.resource_owners,
        )

    @staticmethod
    def _assert_stable_boundary(state: MultiResourceState) -> None:
        if state.active_allocations or state.resource_owners:
            raise AssertionError(
                "stable decision state must not retain communication allocations or resource owners"
            )

    def _deps_completed(
        self, runtimes: Sequence[MultiRuntimeTask], index: int
    ) -> bool:
        return all(runtimes[parent].status == "completed" for parent in self.deps[index])

def _merge_intervals(
    intervals: list[ExecutionInterval],
) -> tuple[ExecutionInterval, ...]:
    by_task: dict[tuple[str, str], list[ExecutionInterval]] = {}
    for interval in intervals:
        by_task.setdefault((interval.task_id, interval.kind), []).append(interval)
    merged: list[ExecutionInterval] = []
    for (task_id, kind), spans in by_task.items():
        spans.sort(key=lambda item: (item.start, item.end))
        task_spans: list[ExecutionInterval] = []
        for span in spans:
            if task_spans and task_spans[-1].end == span.start:
                previous = task_spans[-1]
                task_spans[-1] = ExecutionInterval(task_id, kind, previous.start, span.end)
            else:
                task_spans.append(span)
        merged.extend(task_spans)
    return tuple(sorted(merged, key=lambda item: (item.start, item.end, item.task_id)))


def _complete_zero_compute_intervals(
    model: PreemptiveMultiResourceModel,
    intervals: tuple[ExecutionInterval, ...],
) -> tuple[ExecutionInterval, ...]:
    completed = {interval.task_id: interval.end for interval in intervals}
    result = list(intervals)
    task_map = model.dag.task_map()
    for task_id in topological_order(model.dag):
        task = task_map[task_id]
        if task.kind != "compute" or task.duration != 0:
            continue
        time = max((completed[parent] for parent in task.deps), default=0)
        result.append(ExecutionInterval(task_id, "compute", time, time))
        completed[task_id] = time
    return tuple(sorted(result, key=lambda item: (item.start, item.end, item.task_id)))


def _events_from_intervals(
    intervals: tuple[ExecutionInterval, ...],
) -> tuple[TimelineEvent, ...]:
    by_task: dict[str, list[ExecutionInterval]] = {}
    for interval in intervals:
        by_task.setdefault(interval.task_id, []).append(interval)
    events: list[TimelineEvent] = []
    for task_id, spans in by_task.items():
        spans.sort(key=lambda item: (item.start, item.end))
        if spans[0].kind == "compute":
            events.extend(
                (
                    TimelineEvent(spans[0].start, "compute_started", task_id),
                    TimelineEvent(spans[0].end, "compute_completed", task_id),
                )
            )
            continue
        for index, span in enumerate(spans):
            events.extend(
                (
                    TimelineEvent(
                        span.start,
                        "communication_started" if index == 0 else "communication_resumed",
                        task_id,
                    ),
                    TimelineEvent(
                        span.end,
                        "communication_completed" if index == len(spans) - 1 else "communication_paused",
                        task_id,
                    ),
                )
            )
    order = {
        "compute_completed": 0,
        "communication_completed": 1,
        "communication_paused": 2,
        "compute_started": 3,
        "communication_started": 4,
        "communication_resumed": 5,
    }
    return tuple(sorted(events, key=lambda item: (item.time, order[item.kind], item.task_id)))
