"""Independent replay validation for non-preemptive traces."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from itertools import pairwise
from typing import TYPE_CHECKING, Literal

from core.dag import DAG, Task
from core.execution.contracts import Action, ExecutionInterval, RuntimeTask, TimelineEvent
from core.trace.contracts import ReplaySummary

if TYPE_CHECKING:
    from core.execution.contracts import ScheduleTrace


NonPreemptiveMode = Literal["optional_idle", "work_conserving"]

_EVENT_ORDER = {
    "compute_completed": 0,
    "flow_completed": 1,
    "compute_started": 2,
    "flow_started": 3,
}


def replay_nonpreemptive_trace(
    dag: DAG,
    trace: ScheduleTrace,
    *,
    mode: NonPreemptiveMode | None = None,
) -> ReplaySummary:
    """Replay a trace without instantiating or calling the execution model."""

    errors = dag.validate()
    if errors:
        raise AssertionError(f"cannot replay invalid DAG {dag.name}: {errors}")
    if mode not in (None, "optional_idle", "work_conserving"):
        raise ValueError(f"unknown non-preemptive mode: {mode}")

    task_ids = tuple(dag.topological_order())
    index = {task_id: position for position, task_id in enumerate(task_ids)}
    task_map = dag.task_map()
    if tuple(trace.task_ids) != task_ids:
        raise AssertionError(f"trace task order mismatch: {trace.task_ids} != {task_ids}")
    if trace.final_state.time < 0:
        raise AssertionError("negative makespan")

    by_task = _collect_intervals(task_map, trace.intervals)
    started: dict[str, int] = {}
    completed: dict[str, int] = {}
    service: dict[str, int] = {}
    for task_id in task_ids:
        task = task_map[task_id]
        spans = by_task.get(task_id, [])
        if len(spans) != 1:
            raise AssertionError(f"task {task_id} has {len(spans)} execution intervals")
        span = spans[0]
        actual = span.end - span.start
        if actual != task.duration:
            raise AssertionError(f"duration mismatch for {task_id}: {actual} != {task.duration}")
        started[task_id] = span.start
        completed[task_id] = span.end
        service[task_id] = actual

    for task_id in task_ids:
        task = task_map[task_id]
        release = max((completed[parent] for parent in task.deps), default=0)
        if task.kind == "compute" and started[task_id] != release:
            raise AssertionError(
                f"compute {task_id} did not start immediately at release: "
                f"start={started[task_id]}, release={release}"
            )
        if task.kind == "comm" and started[task_id] < release:
            raise AssertionError(
                f"communication {task_id} started before release: "
                f"start={started[task_id]}, release={release}"
            )

    _validate_communication_exclusion(by_task)
    _validate_events(trace.intervals, trace.events)
    initial_events = _initial_events(task_ids, task_map, by_task)
    initial_intervals = tuple(
        span
        for task_id in task_ids
        for span in by_task[task_id]
        if task_map[task_id].kind == "compute" and span.start == span.end == 0
    )
    _validate_transitions(
        trace,
        task_ids,
        index,
        task_map,
        by_task,
        initial_events,
        initial_intervals,
        mode,
    )

    makespan = max(completed.values(), default=0)
    if trace.makespan != makespan:
        raise AssertionError(f"makespan mismatch: {trace.makespan} != {makespan}")
    _validate_final_state(trace, task_ids, started, completed)
    return ReplaySummary(makespan, started, completed, service)


def assert_nonpreemptive_trace(
    model_or_dag: DAG,
    trace: ScheduleTrace,
    *,
    mode: NonPreemptiveMode | None = None,
) -> None:
    """Assert a non-preemptive trace for a DAG or model exposing ``dag``."""

    dag = model_or_dag if isinstance(model_or_dag, DAG) else model_or_dag.dag
    replay_nonpreemptive_trace(dag, trace, mode=mode)


def _collect_intervals(
    task_map: Mapping[str, Task], intervals: tuple[ExecutionInterval, ...]
) -> dict[str, list[ExecutionInterval]]:
    by_task: dict[str, list[ExecutionInterval]] = defaultdict(list)
    for interval in intervals:
        task = task_map.get(interval.task_id)
        if task is None:
            raise AssertionError(f"interval references unknown task {interval.task_id}")
        expected_kind = "compute" if task.kind == "compute" else "comm"
        if interval.kind != expected_kind:
            raise AssertionError(
                f"interval kind mismatch for {interval.task_id}: "
                f"{interval.kind} != {expected_kind}"
            )
        if interval.start < 0 or interval.end < interval.start:
            raise AssertionError(f"invalid interval: {interval}")
        if task.kind == "comm" and interval.end == interval.start:
            raise AssertionError(f"zero-duration communication: {interval}")
        by_task[interval.task_id].append(interval)
    return by_task


def _validate_communication_exclusion(
    by_task: Mapping[str, list[ExecutionInterval]],
) -> None:
    communications = sorted(
        (span for spans in by_task.values() for span in spans if span.kind == "comm"),
        key=lambda span: (span.start, span.end, span.task_id),
    )
    for previous, current in pairwise(communications):
        if previous.end > current.start:
            raise AssertionError(f"communication intervals overlap: {previous} and {current}")


def _event_key(event: TimelineEvent) -> tuple[int, int, str]:
    if event.kind not in _EVENT_ORDER:
        raise AssertionError(f"unknown trace event kind: {event.kind}")
    return event.time, _EVENT_ORDER[event.kind], event.task_id


def _events_from_intervals(
    intervals: tuple[ExecutionInterval, ...],
) -> tuple[TimelineEvent, ...]:
    by_task: dict[str, list[ExecutionInterval]] = defaultdict(list)
    for interval in intervals:
        by_task[interval.task_id].append(interval)
    events: list[TimelineEvent] = []
    for task_id, spans in by_task.items():
        if len(spans) != 1:
            raise AssertionError(f"task {task_id} has multiple intervals")
        span = spans[0]
        start_kind = "compute_started" if span.kind == "compute" else "flow_started"
        end_kind = "compute_completed" if span.kind == "compute" else "flow_completed"
        events.extend(
            (
                TimelineEvent(span.start, start_kind, task_id),
                TimelineEvent(span.end, end_kind, task_id),
            )
        )
    return tuple(sorted(events, key=_event_key))


def _validate_events(
    intervals: tuple[ExecutionInterval, ...], events: tuple[TimelineEvent, ...]
) -> None:
    if events != tuple(sorted(events, key=_event_key)):
        raise AssertionError("trace events are not in deterministic order")
    if Counter(events) != Counter(_events_from_intervals(intervals)):
        raise AssertionError("trace events do not match interval boundaries")


def _initial_events(
    task_ids: tuple[str, ...],
    task_map: Mapping[str, Task],
    by_task: Mapping[str, list[ExecutionInterval]],
) -> tuple[TimelineEvent, ...]:
    initial = tuple(
        span
        for task_id in task_ids
        for span in by_task[task_id]
        if task_map[task_id].kind == "compute" and span.start == 0
    )
    return tuple(event for event in _events_from_intervals(initial) if event.time == 0)


def _validate_transitions(
    trace: ScheduleTrace,
    task_ids: tuple[str, ...],
    index: Mapping[str, int],
    task_map: Mapping[str, Task],
    by_task: Mapping[str, list[ExecutionInterval]],
    initial_events: tuple[TimelineEvent, ...],
    initial_intervals: tuple[ExecutionInterval, ...],
    mode: NonPreemptiveMode | None,
) -> None:
    expected_tasks = _initial_runtime(task_ids, task_map, index)
    expected_time = 0
    transition_events: list[TimelineEvent] = []
    transition_intervals: list[ExecutionInterval] = []
    cursor = 0

    for transition in trace.transitions:
        before = transition.before
        if (
            before.time != expected_time
            or before.tasks != expected_tasks
            or before.active_flow is not None
        ):
            raise AssertionError("transition before-state does not match replayed state")
        if transition.after.time <= before.time:
            raise AssertionError("transition does not advance time")
        if before.time != cursor:
            raise AssertionError(f"trace timeline has a gap or overlap: {cursor} -> {before.time}")

        ready = _ready_flows(task_ids, task_map, index, expected_tasks)
        active = _active_computes(task_ids, task_map, expected_tasks)
        action = transition.action
        if action.kind == "flow":
            if action.task_id not in ready:
                raise AssertionError(f"illegal FLOW at t={before.time}: {action}")
            expected_after_tasks, expected_after_time = _advance_state(
                task_ids, task_map, index, expected_tasks, before.time, action.task_id
            )
            expected_interval = by_task[action.task_id][0]
            if expected_interval.start != before.time or expected_interval.end != expected_after_time:
                raise AssertionError(f"FLOW interval mismatch for {action.task_id}")
        elif action.kind == "wait":
            if not active:
                raise AssertionError(f"illegal WAIT at t={before.time}: no active compute")
            if mode == "work_conserving" and ready:
                raise AssertionError(f"work-conserving WAIT at t={before.time}: ready={ready}")
            expected_after_tasks, expected_after_time = _advance_state(
                task_ids, task_map, index, expected_tasks, before.time, None
            )
        else:
            raise AssertionError(f"unknown non-preemptive action: {action}")

        if (
            transition.after.time != expected_after_time
            or transition.after.tasks != expected_after_tasks
            or transition.after.active_flow is not None
        ):
            raise AssertionError("transition after-state does not match replayed state")
        transition_events.extend(transition.events)
        transition_intervals.extend(transition.intervals)
        expected_tasks = expected_after_tasks
        expected_time = expected_after_time
        cursor = expected_after_time

    if Counter(transition_events) != Counter(trace.events) - Counter(initial_events):
        raise AssertionError("transition events do not reconstruct the trace")
    if Counter(transition_intervals) != Counter(trace.intervals) - Counter(initial_intervals):
        raise AssertionError("transition intervals do not reconstruct the trace")
    if trace.transitions and trace.transitions[-1].after != trace.final_state:
        raise AssertionError("last transition does not end at final_state")
    if not trace.transitions and trace.final_state.time != 0:
        raise AssertionError("non-empty trace has no transitions")
    if cursor != trace.makespan:
        raise AssertionError(f"trace timeline ends at {cursor}, expected {trace.makespan}")


def _initial_runtime(
    task_ids: tuple[str, ...], task_map: Mapping[str, Task], index: Mapping[str, int]
) -> tuple[RuntimeTask, ...]:
    values = [RuntimeTask() for _ in task_ids]
    for position, task_id in enumerate(task_ids):
        task = task_map[task_id]
        if task.kind != "compute" or not all(values[index[parent]].status == "completed" for parent in task.deps):
            continue
        values[position] = (
            RuntimeTask("completed", 0, 0, 0)
            if task.duration == 0
            else RuntimeTask("running", task.duration, 0, None)
        )
    return tuple(values)


def _ready_flows(
    task_ids: tuple[str, ...],
    task_map: Mapping[str, Task],
    index: Mapping[str, int],
    runtimes: tuple[RuntimeTask, ...],
) -> tuple[str, ...]:
    return tuple(
        task_id
        for task_id in task_ids
        if task_map[task_id].kind == "comm"
        and runtimes[index[task_id]].status == "pending"
        and all(runtimes[index[parent]].status == "completed" for parent in task_map[task_id].deps)
    )


def _active_computes(
    task_ids: tuple[str, ...], task_map: Mapping[str, Task], runtimes: tuple[RuntimeTask, ...]
) -> tuple[str, ...]:
    return tuple(
        task_id
        for position, task_id in enumerate(task_ids)
        if task_map[task_id].kind == "compute" and runtimes[position].status == "running"
    )


def _advance_state(
    task_ids: tuple[str, ...],
    task_map: Mapping[str, Task],
    index: Mapping[str, int],
    runtimes: tuple[RuntimeTask, ...],
    time: int,
    flow_id: str | None,
) -> tuple[tuple[RuntimeTask, ...], int]:
    values = list(runtimes)
    if flow_id is not None:
        flow_index = index[flow_id]
        values[flow_index] = RuntimeTask("running", task_map[flow_id].duration, time, None)
        end = time + task_map[flow_id].duration
    else:
        active = [
            runtime.remaining
            for position, runtime in enumerate(values)
            if task_map[task_ids[position]].kind == "compute" and runtime.status == "running"
        ]
        if not active:
            raise AssertionError("WAIT has no active compute")
        end = time + min(active)

    current = time
    while current < end:
        active = [
            runtime.remaining
            for position, runtime in enumerate(values)
            if task_map[task_ids[position]].kind == "compute" and runtime.status == "running"
        ]
        delta = min(end - current, min(active, default=end - current))
        segment_end = current + delta
        for position, task_id in enumerate(task_ids):
            runtime = values[position]
            if task_map[task_id].kind != "compute" or runtime.status != "running":
                continue
            remaining = runtime.remaining - delta
            if remaining < 0:
                raise AssertionError("replay advanced beyond compute completion")
            values[position] = RuntimeTask(
                "completed" if remaining == 0 else "running",
                remaining,
                runtime.started_at,
                segment_end if remaining == 0 else None,
            )
        current = segment_end
        _start_ready_computes(task_ids, task_map, index, values, current)

    if flow_id is not None:
        values[index[flow_id]] = RuntimeTask("completed", 0, time, end)
    _start_ready_computes(task_ids, task_map, index, values, end)
    return tuple(values), end


def _start_ready_computes(
    task_ids: tuple[str, ...],
    task_map: Mapping[str, Task],
    index: Mapping[str, int],
    values: list[RuntimeTask],
    time: int,
) -> None:
    for position, task_id in enumerate(task_ids):
        task = task_map[task_id]
        if task.kind != "compute" or values[position].status != "pending":
            continue
        if not all(values[index[parent]].status == "completed" for parent in task.deps):
            continue
        values[position] = (
            RuntimeTask("completed", 0, time, time)
            if task.duration == 0
            else RuntimeTask("running", task.duration, time, None)
        )


def _validate_final_state(
    trace: ScheduleTrace,
    task_ids: tuple[str, ...],
    started: Mapping[str, int],
    completed: Mapping[str, int],
) -> None:
    if len(trace.final_state.tasks) != len(task_ids):
        raise AssertionError("final state task count mismatch")
    for task_id, runtime in zip(task_ids, trace.final_state.tasks, strict=True):
        if runtime.status != "completed" or runtime.remaining != 0:
            raise AssertionError(f"final state does not complete {task_id}")
        if runtime.started_at != started[task_id] or runtime.completed_at != completed[task_id]:
            raise AssertionError(f"final state timing mismatch for {task_id}")
