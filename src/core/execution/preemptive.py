"""Event-driven model where communication may pause and resume.

Compute tasks start automatically and remain non-preemptive.  A dispatched
communication runs until it completes or until the next compute completion.
At that event the scheduler may continue it or switch to another eligible
communication. Pausing releases the channel and preserves progress. Forced
idle is represented by WAIT only when no communication is eligible.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from itertools import pairwise
from typing import Literal

from core.dag import DAG
from core.execution.contracts import (
    DeadlockError,
    IllegalActionError,
    SchedulerTaskView,
    SchedulerView,
)
from core.execution.contracts import (
    Action,
    ExecutionInterval,
    ExecutionTrace,
    RuntimeTask,
    ScheduleTrace,
    TimelineEvent,
    Transition,
)
from core.execution.contracts import sort_events
from core.execution.contracts import ExecutionResult
from core.execution.dag_support import (
    DAGTopology,
    advance_running_computes,
    dependencies_completed,
    running_compute_indices,
    start_ready_computes,
)
from core.trace.contracts import ForcedIdleInterval, ResourceInterval

TaskStatus = Literal["pending", "running", "suspended", "completed"]
ActionKind = Literal["run", "wait"]


@dataclass(frozen=True)
class AlgorithmStats:
    runtime_ms: float = 0.0
    explored_states: int = 0
    generated_transitions: int = 0
    pruned_states: int = 0
    cache_hits: int = 0
    status: str = "feasible"
    termination_reason: str | None = None
    deduplicated_states: int = 0
    memo_hits: int = 0
    incumbent_prunes: int = 0
    lower_bound_prunes: int = 0
    peak_states: int = 0
    lower_bound: int = 0
    expanded_nodes: int = 0
    evaluated_candidates: int = 0
    fallback_count: int = 0
    fallback_reasons: tuple[str, ...] = ()
    planner_decisions: int = 0
    planner_triggered: int = 0
    planner_improvements: int = 0
    completion_calls: int = 0
    choice_gate_ms: float = 0.0
    cheap_feature_ms: float = 0.0
    expensive_feature_ms: float = 0.0
    candidate_generation_ms: float = 0.0
    completion_ms: float = 0.0
    trigger_positives: int = 0
    completed_rollout_evaluations: int = 0
    budget_rejected_triggers: int = 0
    generated_candidates: int = 0
    max_actual_depth: int = 0
    trigger_reason_counts: tuple[tuple[str, int], ...] = ()
    fallback_details: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreemptiveScheduleResult:
    """A schedule's execution facts and the solver-specific accounting."""

    execution: ExecutionResult
    stats: AlgorithmStats = AlgorithmStats()

    def with_stats(self, **changes: object) -> "PreemptiveScheduleResult":
        return replace(self, stats=replace(self.stats, **changes))

    @property
    def makespan(self) -> int:
        return self.execution.makespan

    @property
    def trace(self) -> ExecutionTrace:
        return self.execution.trace

    @property
    def dispatches(self) -> int:
        return self.execution.dispatches

    @property
    def preemptions(self) -> int:
        return self.execution.preemptions

    @property
    def algorithm_stats(self) -> AlgorithmStats:
        return self.stats

    def __getattr__(self, name: str) -> object:
        if name in AlgorithmStats.__dataclass_fields__:
            return getattr(self.stats, name)
        raise AttributeError(name)


@dataclass(frozen=True)
class ScheduleState:
    """Stable state at a task event, before the next dispatch decision."""

    time: int
    tasks: tuple[RuntimeTask, ...]
    last_communication: str | None = None


class PreeSingleModel:
    """Single-channel, zero-cost communication pause/resume state machine."""

    def __init__(self, dag: DAG):
        errors = dag.validate()
        if errors:
            raise ValueError(f"invalid benchmark DAG {dag.name}: {errors}")
        if any(task.kind == "comm" and task.duration <= 0 for task in dag.tasks):
            raise ValueError("preemptive model requires positive communication durations")
        topology = DAGTopology.from_dag(dag)
        self.dag = topology.dag
        self.task_ids = topology.task_ids
        self.tasks = topology.tasks
        self.task_map = self.dag.task_map()
        self.index = topology.index
        self.deps = topology.deps
        self.compute_indices = topology.compute_indices
        self.communication_indices = topology.communication_indices
        self.children = {
            task_id: tuple(self.task_ids[child] for child in topology.children[index])
            for index, task_id in enumerate(self.task_ids)
        }

    def initial_state(self) -> ScheduleState:
        values, _events, _intervals = start_ready_computes(
            self.tasks, self.deps, 0, tuple(RuntimeTask() for _ in self.tasks)
        )
        return ScheduleState(0, tuple(values))

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
        for index in self.communication_indices:
            task = self.tasks[index]
            runtime = state.tasks[index]
            if task.kind != "comm" or runtime.status == "completed":
                continue
            if runtime.status == "suspended" or dependencies_completed(state.tasks, self.deps, index):
                eligible.append(task.task_id)
        return tuple(eligible)

    def active_computes(self, state: ScheduleState) -> tuple[str, ...]:
        return tuple(
            self.tasks[index].task_id
            for index in self.compute_indices
            if state.tasks[index].status == "running"
        )

    def legal_actions(self, state: ScheduleState) -> tuple[Action, ...]:
        eligible = self.eligible_communications(state)
        if eligible:
            return tuple(Action.run(task_id) for task_id in eligible)
        if self.active_computes(state):
            return (Action.wait(),)
        return ()

    def scheduler_view(
        self, state: ScheduleState, *, include_tasks: bool = False
    ) -> SchedulerView:
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
            ) if include_tasks else (),
        )

    def is_finished(self, state: ScheduleState) -> bool:
        return all(runtime.status == "completed" for runtime in state.tasks)

    def step(self, state: ScheduleState, action: Action) -> Transition:
        if action.kind == "wait":
            eligible = self.eligible_communications(state)
            active = running_compute_indices(self.compute_indices, state.tasks)
            if eligible:
                raise IllegalActionError(
                    f"voluntary WAIT is forbidden at t={state.time}: eligible={eligible}"
                )
            if not active:
                if not self.is_finished(state):
                    raise DeadlockError(f"state cannot advance at t={state.time}")
                raise IllegalActionError(f"schedule is already complete at t={state.time}")
            return self._wait(state, action)
        if action.kind != "run" or action.task_id is None:
            raise IllegalActionError(f"invalid action at t={state.time}: {action}")
        if action.task_id not in self.index:
            raise IllegalActionError(f"unknown communication at t={state.time}: {action.task_id}")
        index = self.index[action.task_id]
        runtime = state.tasks[index]
        if self.tasks[index].kind != "comm" or runtime.status == "completed":
            raise IllegalActionError(f"ineligible communication at t={state.time}: {action.task_id}")
        if runtime.status != "suspended" and not dependencies_completed(state.tasks, self.deps, index):
            raise IllegalActionError(f"communication dependencies are incomplete: {action.task_id}")
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
            final_state=state,
            events=tuple(self._sort_events(events)),
            intervals=tuple(intervals),
            task_ids=self.task_ids,
            transitions=tuple(transitions),
        )

    def _dispatch(self, state: ScheduleState, action: Action) -> Transition:
        task_id = action.task_id
        assert task_id is not None
        index = self.index[task_id]
        runtime = state.tasks[index]
        remaining = runtime.remaining or self.tasks[index].duration
        running_computes = running_compute_indices(self.compute_indices, state.tasks)
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
        values, start_events, start_intervals = start_ready_computes(
            self.tasks, self.deps, working.time, working.tasks
        )
        working = ScheduleState(working.time, tuple(values), working.last_communication)
        events.extend(start_events)
        intervals = [ExecutionInterval(task_id, "comm", start, end)]
        intervals.extend(compute_intervals)
        intervals.extend(start_intervals)
        return Transition(
            action, state, working, tuple(self._sort_events(events)), tuple(intervals)
        )

    def _wait(self, state: ScheduleState, action: Action) -> Transition:
        running = running_compute_indices(self.compute_indices, state.tasks)
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
        values, events, intervals = advance_running_computes(
            self.tasks, self.compute_indices, state.tasks, state.time, delta
        )
        if state.last_communication is not None:
            index = self.index[state.last_communication]
            runtime = values[index]
            if runtime.status == "running":
                values[index] = RuntimeTask(
                    "running", runtime.remaining - delta, runtime.started_at, None
                )
        values, start_events, start_intervals = start_ready_computes(
            self.tasks, self.deps, end, values
        )
        advanced = ScheduleState(end, tuple(values), state.last_communication)
        events.extend(start_events)
        intervals.extend(start_intervals)
        return advanced, self._sort_events(events), intervals

    @staticmethod
    def _sort_events(events: list[TimelineEvent]) -> list[TimelineEvent]:
        return sort_events(events, preemptive=True)


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
    return PreemptiveScheduleResult(
        ExecutionResult(trace, len(communications), preemptions)
    )


MultiRuntimeTask = RuntimeTask


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
class MultiResourceTrace(ExecutionTrace[MultiResourceState]):
    decisions: tuple[MultiResourceDecision, ...]
    resource_intervals: tuple[ResourceInterval, ...]
    forced_idle: tuple[ForcedIdleInterval, ...]


class PreeMultiModel:
    """Stable-boundary fixed-resource event simulator.

    A stable state has no active communication allocation.  Running compute
    tasks are represented in ``tasks`` and continue across decisions.
    """

    def __init__(
        self,
        dag: DAG,
        resources: dict[str, frozenset[str]] | None = None,
    ):
        if resources is None:
            resources = dag.resources
        errors = dag.validate()
        if errors:
            raise ValueError(f"invalid DAG: {errors}")
        topology = DAGTopology.from_dag(dag)
        self.dag = topology.dag
        self.task_ids = topology.task_ids
        self.tasks = topology.tasks
        self.task_map = self.dag.task_map()
        self.index = topology.index
        self.deps = topology.deps
        self.compute_indices = topology.compute_indices
        self.communication_indices = topology.communication_indices
        comm_ids = {task.task_id for task in self.tasks if task.kind == "comm"}
        if set(resources) != comm_ids or any(not resources[item] for item in comm_ids):
            raise ValueError("every communication must have a non-empty fixed resource set")
        if any(task.kind == "comm" and task.duration <= 0 for task in self.tasks):
            raise ValueError("preemptive model requires positive communication durations")
        self.resources = {
            task_id: frozenset(resource_set)
            for task_id, resource_set in resources.items()
        }
        self.children = {
            task_id: tuple(self.task_ids[child] for child in topology.children[index])
            for index, task_id in enumerate(self.task_ids)
        }

    def initial_state(self) -> MultiResourceState:
        return self._compute_closure(
            MultiResourceState(0, tuple(MultiRuntimeTask() for _ in self.tasks))
        )

    def eligible(self, state: MultiResourceState) -> tuple[str, ...]:
        result = []
        for index in self.communication_indices:
            task = self.tasks[index]
            runtime = state.tasks[index]
            if task.kind != "comm" or runtime.status == "completed":
                continue
            if runtime.status == "suspended" or self._deps_completed(state.tasks, index):
                result.append(task.task_id)
        return tuple(result)

    def active_computes(self, state: MultiResourceState) -> tuple[int, ...]:
        return tuple(
            index
            for index in self.compute_indices
            if state.tasks[index].status == "running"
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

    def scheduler_view(
        self, state: MultiResourceState, *, include_tasks: bool = False
    ) -> SchedulerView:
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
            ) if include_tasks else (),
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
        selected_set = set(selected)
        is_eligible = selected_set <= set(eligible)
        is_compatible = self.compatible(selected)
        is_maximal = is_eligible and is_compatible and all(
            not self.compatible((*selected, item))
            for item in eligible
            if item not in selected_set
        )
        if not selected or not is_maximal:
            if not selected:
                reason = "forced idle is simulator-owned; empty scheduler actions are forbidden"
            elif is_eligible and is_compatible:
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
            final_state=state,
            events=_events_from_intervals(intervals),
            intervals=intervals,
            task_ids=self.task_ids,
            decisions=tuple(decisions),
            resource_intervals=resource_intervals,
            forced_idle=tuple(forced_idle),
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
        for index in self.compute_indices:
            task = self.tasks[index]
            if values[index].status != "pending" or not self._deps_completed(values, index):
                continue
            values[index] = MultiRuntimeTask(
                "completed" if task.duration == 0 else "running", task.duration
            )
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
    model: PreeMultiModel,
    intervals: tuple[ExecutionInterval, ...],
) -> tuple[ExecutionInterval, ...]:
    completed = {interval.task_id: interval.end for interval in intervals}
    result = list(intervals)
    task_map = model.dag.task_map()
    for task_id in model.dag.topological_order():
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
