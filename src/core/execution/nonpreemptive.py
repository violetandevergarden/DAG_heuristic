"""Non-preemptive single-channel DAG scheduling semantics.

This module is deliberately isolated from the production executor.  It is the
reference transition system for the revised heuristic studies:

* every communication occupies the full channel in one contiguous interval;
* every compute runs continuously after its dependencies complete;
* computes may overlap one another and the active communication;
* scheduling decisions are made only while the channel is idle;
* an explicit WAIT action may advance to the next compute completion.

The benchmark DAG uses integer time quanta.  A stable ``ScheduleState`` is a
decision epoch, so ``active_flow`` is always ``None`` at its boundary.  A FLOW
transition records the busy interval and all compute events inside it, but it
does not expose those intermediate events as preemption points.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Hashable, Iterable
from typing import Literal, Sequence

from core.dag import DAG, Task
from core.execution.contracts import (
    Action,
    ExecutionInterval,
    RuntimeTask,
    ScheduleTrace,
    TimelineEvent,
    Transition,
)
from core.execution.contracts import sort_events
from core.execution.dag_support import (
    DAGTopology,
    advance_running_computes,
    dependencies_completed,
    running_compute_indices,
    start_ready_computes,
)


TaskStatus = Literal["pending", "running", "completed"]
ActionKind = Literal["flow", "wait"]


@dataclass(frozen=True)
class ScheduleState:
    """A stable decision state at which the communication channel is idle."""

    time: int
    tasks: tuple[RuntimeTask, ...]
    active_flow: str | None = None


class NonPreeSingleModel:
    """Reference state machine for whole-flow, optional-idle scheduling."""

    def __init__(self, dag: DAG):
        errors = dag.validate()
        if errors:
            raise ValueError(f"invalid benchmark DAG {dag.name}: {errors}")
        if any(task.kind == "comm" and task.duration <= 0 for task in dag.tasks):
            raise ValueError("R0 reference model requires positive flow durations")

        topology = DAGTopology.from_dag(dag)
        self.dag = topology.dag
        self.task_ids = topology.task_ids
        self.tasks = topology.tasks
        self.index = topology.index
        self.deps = topology.deps
        self.compute_indices = topology.compute_indices
        self.communication_indices = topology.communication_indices

    def initial_state(self) -> ScheduleState:
        values, _events, _intervals = start_ready_computes(
            self.tasks, self.deps, 0, tuple(RuntimeTask() for _ in self.tasks)
        )
        return ScheduleState(0, tuple(values))

    def initial_events(self, state: ScheduleState) -> tuple[TimelineEvent, ...]:
        if state.time != 0:
            raise ValueError("initial events require the t=0 state")
        events: list[TimelineEvent] = []
        for task, runtime in zip(self.tasks, state.tasks, strict=True):
            if task.kind != "compute" or runtime.started_at != 0:
                continue
            events.append(TimelineEvent(0, "compute_started", task.task_id))
            if runtime.status == "completed" and runtime.completed_at == 0:
                events.append(TimelineEvent(0, "compute_completed", task.task_id))
        return tuple(self._sort_events(events))

    def initial_intervals(self, state: ScheduleState) -> tuple[ExecutionInterval, ...]:
        return tuple(
            ExecutionInterval(task.task_id, "compute", 0, 0)
            for task, runtime in zip(self.tasks, state.tasks, strict=True)
            if task.kind == "compute"
            and runtime.status == "completed"
            and runtime.started_at == 0
            and runtime.completed_at == 0
        )

    def task_runtime(self, state: ScheduleState, task_id: str) -> RuntimeTask:
        return state.tasks[self.index[task_id]]

    def ready_flows(self, state: ScheduleState) -> tuple[str, ...]:
        self._require_stable(state)
        ready = []
        for index in self.communication_indices:
            task = self.tasks[index]
            runtime = state.tasks[index]
            if (
                task.kind == "comm"
                and runtime.status == "pending"
                and dependencies_completed(state.tasks, self.deps, index)
            ):
                ready.append(task.task_id)
        return tuple(ready)

    def active_computes(self, state: ScheduleState) -> tuple[str, ...]:
        return tuple(
            self.tasks[index].task_id
            for index in self.compute_indices
            if state.tasks[index].status == "running"
        )

    def scheduler_view(self, state: ScheduleState, *, include_tasks: bool = False):
        """Expose the stable state without leaking model internals."""
        from core.execution.contracts import SchedulerTaskView, SchedulerView

        return SchedulerView(
            time=state.time,
            eligible_communications=self.ready_flows(state),
            active_computes=self.active_computes(state),
            tasks=tuple(
                SchedulerTaskView(
                    task.task_id,
                    task.kind,
                    runtime.status,
                    runtime.remaining,
                    task.resources,
                )
                for task, runtime in zip(self.tasks, state.tasks, strict=True)
            ) if include_tasks else (),
            can_wait=bool(self.active_computes(state)),
        )

    def legal_actions(self, state: ScheduleState) -> tuple[Action, ...]:
        """Return whole-flow starts plus WAIT when a real future event exists."""

        actions = [Action.flow(task_id) for task_id in self.ready_flows(state)]
        if self.active_computes(state):
            actions.append(Action.wait())
        return tuple(actions)

    def is_finished(self, state: ScheduleState) -> bool:
        return all(runtime.status == "completed" for runtime in state.tasks)

    def step(self, state: ScheduleState, action: Action) -> Transition:
        self._require_stable(state)
        if action.kind == "wait":
            if not running_compute_indices(self.compute_indices, state.tasks):
                raise ValueError("illegal action: WAIT requires an active compute completion event")
            return self._wait(state, action)
        if action.kind != "flow" or action.task_id is None:
            raise ValueError(f"illegal action at t={state.time}: {action}")
        if action.task_id not in self.index:
            raise ValueError(f"unknown flow at t={state.time}: {action.task_id}")
        index = self.index[action.task_id]
        runtime = state.tasks[index]
        if (
            self.tasks[index].kind != "comm"
            or runtime.status != "pending"
            or not dependencies_completed(state.tasks, self.deps, index)
        ):
            raise ValueError(f"illegal flow at t={state.time}: {action.task_id}")
        return self._run_flow(state, action)

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

    def _run_flow(self, state: ScheduleState, action: Action) -> Transition:
        task_id = action.task_id
        assert task_id is not None
        index = self.index[task_id]
        task = self.tasks[index]
        start = state.time
        end = start + task.duration
        values = list(state.tasks)
        values[index] = RuntimeTask("running", task.duration, start, None)
        working = ScheduleState(start, tuple(values), task_id)
        events: list[TimelineEvent] = [TimelineEvent(start, "flow_started", task_id)]
        compute_intervals: list[ExecutionInterval] = []

        # Compute completions are observed for dependency release, but never
        # become scheduler decision points while this flow owns the channel.
        while working.time < end:
            running = running_compute_indices(self.compute_indices, working.tasks)
            next_compute = min(
                (working.tasks[item].remaining for item in running), default=None
            )
            delta = end - working.time
            if next_compute is not None:
                delta = min(delta, next_compute)
            working, new_events, new_intervals = self._advance_computes(working, delta)
            events.extend(new_events)
            compute_intervals.extend(new_intervals)

        values = list(working.tasks)
        values[index] = RuntimeTask("completed", 0, start, end)
        working = ScheduleState(end, tuple(values), None)
        events.append(TimelineEvent(end, "flow_completed", task_id))
        values, start_events, start_intervals = start_ready_computes(
            self.tasks, self.deps, working.time, working.tasks
        )
        working = ScheduleState(working.time, tuple(values), working.active_flow)
        events.extend(start_events)
        compute_intervals.extend(start_intervals)

        interval = ExecutionInterval(task_id, "comm", start, end)
        return Transition(
            action,
            state,
            working,
            tuple(self._sort_events(events)),
            (interval, *compute_intervals),
        )

    def _wait(self, state: ScheduleState, action: Action) -> Transition:
        running = running_compute_indices(self.compute_indices, state.tasks)
        if not running:
            raise ValueError("WAIT requires an active compute completion event")
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
        if state.active_flow is not None:
            flow_index = self.index[state.active_flow]
            flow_runtime = values[flow_index]
            flow_remaining = flow_runtime.remaining - delta
            if flow_remaining < 0:
                raise AssertionError("advanced beyond active flow completion")
            values[flow_index] = RuntimeTask(
                "running", flow_remaining, flow_runtime.started_at, None
            )
        values, start_events, start_intervals = start_ready_computes(
            self.tasks, self.deps, end, values
        )
        advanced = ScheduleState(end, tuple(values), state.active_flow)
        events.extend(start_events)
        intervals.extend(start_intervals)
        return advanced, self._sort_events(events), intervals

    @staticmethod
    def _sort_events(events: list[TimelineEvent]) -> list[TimelineEvent]:
        return sort_events(events)

    @staticmethod
    def _require_stable(state: ScheduleState) -> None:
        if state.active_flow is not None:
            raise ValueError("scheduler decisions require an idle channel")


Resource = Hashable
Status = Literal["pending", "running", "completed"]
OracleMode = Literal["optional_idle", "work_conserving"]


@dataclass(frozen=True)
class ResourceRuntime:
    status: Status = "pending"
    remaining: int = 0
    started_at: int | None = None
    completed_at: int | None = None


@dataclass(frozen=True)
class ResourceState:
    time: int
    tasks: tuple[ResourceRuntime, ...]


@dataclass(frozen=True)
class ResourceAction:
    starts: tuple[str, ...] = ()

    @property
    def kind(self) -> str:
        return "start" if self.starts else "wait"

    @classmethod
    def start(cls, task_ids: Iterable[str]) -> ResourceAction:
        values = tuple(sorted(task_ids))
        if not values:
            raise ValueError("START action requires at least one flow")
        return cls(values)

    @classmethod
    def wait(cls) -> ResourceAction:
        return cls()


@dataclass(frozen=True)
class ResourceInterval:
    task_id: str
    kind: str
    start: int
    end: int


@dataclass(frozen=True)
class ResourceTransition:
    action: ResourceAction
    before: ResourceState
    after: ResourceState
    completed: tuple[str, ...]
    intervals: tuple[ResourceInterval, ...]


class NonPreeMultiModel:
    """Event-driven state machine with persistent route reservations."""

    def __init__(self, dag: DAG):
        errors = dag.validate()
        if errors:
            raise ValueError(errors)
        communications = [task for task in dag.tasks if task.kind == "comm"]
        if any(not task.resources for task in communications):
            raise ValueError("every communication must have a non-empty fixed resource set")
        if any(task.duration <= 0 for task in communications):
            raise ValueError("nonpreemptive model requires positive communication durations")
        topology = DAGTopology.from_dag(dag)
        self.dag = topology.dag
        self.order = topology.task_ids
        self.tasks = topology.tasks
        self.index = topology.index
        self.deps = topology.deps
        self.children = topology.children
        self.compute_indices = topology.compute_indices
        self.communication_indices = topology.communication_indices
        self.resources = tuple(dag.resources.get(task.task_id, frozenset()) for task in self.tasks)

    def initial_state(self) -> ResourceState:
        return self._start_ready_computes(ResourceState(0, tuple(ResourceRuntime() for _ in self.tasks)))[0]

    def is_finished(self, state: ResourceState) -> bool:
        return all(state.tasks[index].status == "completed" for index in range(len(self.tasks)))

    def ready_flows(self, state: ResourceState) -> tuple[str, ...]:
        return tuple(
            self.tasks[index].task_id
            for index in self.communication_indices
            if state.tasks[index].status == "pending"
            and self._deps_completed(state.tasks, index)
        )

    def active_flows(self, state: ResourceState) -> tuple[str, ...]:
        return tuple(
            self.tasks[index].task_id
            for index in self.communication_indices
            if state.tasks[index].status == "running"
        )

    def active_computes(self, state: ResourceState) -> tuple[str, ...]:
        return tuple(
            self.tasks[index].task_id
            for index in self.compute_indices
            if state.tasks[index].status == "running"
        )

    def occupied_resources(self, state: ResourceState) -> frozenset[Resource]:
        return frozenset(resource for task_id in self.active_flows(state) for resource in self.resources[self.index[task_id]])

    def compatible(self, state: ResourceState, task_ids: Iterable[str]) -> bool:
        occupied = set(self.occupied_resources(state))
        for task_id in task_ids:
            resources = self.resources[self.index[task_id]]
            if occupied & resources:
                return False
            occupied.update(resources)
        return True

    def startable_flows(self, state: ResourceState) -> tuple[str, ...]:
        occupied = self.occupied_resources(state)
        return tuple(task_id for task_id in self.ready_flows(state) if not (occupied & self.resources[self.index[task_id]]))

    def has_future_event(self, state: ResourceState) -> bool:
        return self._has_active_task(state)

    def is_maximal_start(self, state: ResourceState, task_ids: Iterable[str]) -> bool:
        selected = tuple(task_ids)
        if not selected or len(selected) != len(set(selected)):
            return False
        startable = set(self.startable_flows(state))
        if any(task_id not in startable for task_id in selected) or not self.compatible(state, selected):
            return False
        used = set(self.occupied_resources(state))
        for task_id in selected:
            used.update(self.resources[self.index[task_id]])
        return all(used & self.resources[self.index[task_id]] for task_id in startable.difference(selected))

    def validate_action(self, state: ResourceState, action: ResourceAction, mode: OracleMode) -> None:
        if mode not in ("optional_idle", "work_conserving"):
            raise ValueError(f"unknown oracle mode: {mode}")
        startable = set(self.startable_flows(state))
        if action.kind == "wait":
            if not self.has_future_event(state):
                raise ValueError("WAIT requires a real future event")
            if mode == "work_conserving" and startable:
                raise ValueError("work-conserving mode forbids WAIT when a flow is startable")
            return
        if len(action.starts) != len(set(action.starts)) or any(task_id not in startable for task_id in action.starts):
            raise ValueError("START contains a duplicate or non-startable flow")
        if not self.compatible(state, action.starts):
            raise ValueError("START contains conflicting routes")
        if mode == "work_conserving" and not self.is_maximal_start(state, action.starts):
            raise ValueError("work-conserving START must be inclusion-maximal")

    def start_subsets(self, state: ResourceState, *, maximal_only: bool) -> tuple[tuple[str, ...], ...]:
        ready = tuple(sorted(self.startable_flows(state)))
        if maximal_only:
            if not ready:
                return ()
            compatible = {
                task_id: {
                    other
                    for other in ready
                    if other != task_id
                    and self.resources[self.index[task_id]].isdisjoint(
                        self.resources[self.index[other]]
                    )
                }
                for task_id in ready
            }
            maximal: list[tuple[str, ...]] = []

            def visit(
                chosen: set[str], candidates: set[str], excluded: set[str]
            ) -> None:
                if not candidates and not excluded:
                    maximal.append(tuple(sorted(chosen)))
                    return
                pivot = max(candidates | excluded, key=lambda item: len(candidates & compatible[item]), default=None)
                extensions = candidates - (compatible[pivot] if pivot is not None else set())
                for task_id in sorted(extensions):
                    visit(
                        chosen | {task_id},
                        candidates & compatible[task_id],
                        excluded & compatible[task_id],
                    )
                    candidates.remove(task_id)
                    excluded.add(task_id)

            visit(set(), set(ready), set())
            return tuple(sorted(set(maximal)))

        subsets: list[tuple[str, ...]] = []
        def visit(position: int, chosen: tuple[str, ...], used: frozenset[Resource]) -> None:
            if position == len(ready):
                if chosen: subsets.append(chosen)
                return
            task_id = ready[position]
            visit(position + 1, chosen, used)
            resources = self.resources[self.index[task_id]]
            if not (used & resources): visit(position + 1, (*chosen, task_id), used | resources)
        visit(0, (), self.occupied_resources(state))
        return tuple(sorted(set(subsets)))

    def legal_actions(self, state: ResourceState, mode: OracleMode) -> tuple[ResourceAction, ...]:
        if mode not in ("optional_idle", "work_conserving"):
            raise ValueError(f"unknown oracle mode: {mode}")
        starts = self.start_subsets(state, maximal_only=mode == "work_conserving")
        if starts:
            actions = tuple(ResourceAction.start(items) for items in starts)
            if mode == "optional_idle" and self._has_active_task(state): return (*actions, ResourceAction.wait())
            return actions
        return (ResourceAction.wait(),) if self._has_active_task(state) else ()

    def step(self, state: ResourceState, action: ResourceAction) -> ResourceTransition:
        starts = action.starts
        if starts:
            ready = set(self.ready_flows(state))
            if (
                len(starts) != len(set(starts))
                or any(task_id not in ready for task_id in starts)
                or not self.compatible(state, starts)
            ):
                raise ValueError("invalid START action")
        elif not self._has_active_task(state): raise ValueError("WAIT requires an active completion event")
        values = list(state.tasks)
        for task_id in starts:
            index = self.index[task_id]; values[index] = ResourceRuntime("running", self.tasks[index].duration, state.time, None)
        working = ResourceState(state.time, tuple(values)); delta = min(runtime.remaining for runtime in working.tasks if runtime.status == "running"); end = state.time + delta
        completed, intervals, values = [], [], list(working.tasks)
        for index, runtime in enumerate(working.tasks):
            if runtime.status != "running": continue
            remaining = runtime.remaining - delta
            if remaining: values[index] = ResourceRuntime("running", remaining, runtime.started_at, None); continue
            values[index] = ResourceRuntime("completed", 0, runtime.started_at, end); completed.append(self.tasks[index].task_id)
            assert runtime.started_at is not None
            intervals.append(ResourceInterval(self.tasks[index].task_id, self.tasks[index].kind, runtime.started_at, end))
        after, compute_intervals = self._start_ready_computes(ResourceState(end, tuple(values)))
        return ResourceTransition(action, state, after, tuple(sorted(completed)), tuple((*intervals, *compute_intervals)))

    def residual_features(self, state: ResourceState) -> tuple[tuple[int, ...], tuple[int, ...]]:
        remaining = [self.remaining(state, index) for index in range(len(self.tasks))]; path = [0] * len(self.tasks); tail = [0] * len(self.tasks)
        for index in reversed(range(len(self.tasks))):
            if remaining[index]: tail[index] = max((path[child] for child in self.children[index]), default=0); path[index] = remaining[index] + tail[index]
        return tuple(path), tuple(tail)

    def remaining(self, state: ResourceState, index: int) -> int:
        runtime = state.tasks[index]
        return 0 if runtime.status == "completed" else runtime.remaining if runtime.status == "running" else self.tasks[index].duration

    def _start_ready_computes(self, state: ResourceState) -> tuple[ResourceState, list[ResourceInterval]]:
        values, intervals = list(state.tasks), []
        for index in self.compute_indices:
            task = self.tasks[index]
            if values[index].status != "pending" or not self._deps_completed(values, index):
                continue
            if task.duration == 0:
                values[index] = ResourceRuntime("completed", 0, state.time, state.time)
                intervals.append(ResourceInterval(task.task_id, "compute", state.time, state.time))
            else:
                values[index] = ResourceRuntime("running", task.duration, state.time, None)
        return ResourceState(state.time, tuple(values)), intervals

    def _deps_completed(
        self, runtimes: Sequence[ResourceRuntime], task_index: int
    ) -> bool:
        return all(
            runtimes[parent].status == "completed"
            for parent in self.deps[task_index]
        )

    @staticmethod
    def _has_active_task(state: ResourceState) -> bool:
        return any(runtime.status == "running" for runtime in state.tasks)
