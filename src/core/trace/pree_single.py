"""Independent replay validator for single-channel preemptive traces.

This module deliberately does not import or call ``PreeSingleModel``.  It
derives timing, completion, precedence, event and action legality from the
immutable DAG and serialized trace fields.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import TYPE_CHECKING

from core.dag import DAG
from core.trace.contracts import ReplaySummary

if TYPE_CHECKING:
    from core.execution.preemptive import ExecutionInterval, ScheduleTrace, TimelineEvent


_EVENT_ORDER = {
    "compute_completed": 0,
    "communication_completed": 1,
    "communication_paused": 2,
    "compute_started": 3,
    "communication_started": 4,
    "communication_resumed": 5,
}


def _event_key(event: TimelineEvent) -> tuple[int, int, str]:
    if event.kind not in _EVENT_ORDER:
        raise AssertionError(f"unknown trace event kind: {event.kind}")
    return (event.time, _EVENT_ORDER[event.kind], event.task_id)


def _interval_key(interval: ExecutionInterval) -> tuple[str, str, int, int]:
    return (interval.task_id, interval.kind, interval.start, interval.end)


def replay_preemptive_trace(dag: DAG, trace: ScheduleTrace) -> ReplaySummary:
    errors = dag.validate()
    if errors:
        raise AssertionError(f"cannot replay invalid DAG {dag.name}: {errors}")
    task_map = dag.task_map()
    expected_ids = tuple(dag.topological_order())
    if tuple(trace.task_ids) != expected_ids:
        raise AssertionError(f"trace task order mismatch: {trace.task_ids} != {expected_ids}")
    if trace.final_state.time < 0:
        raise AssertionError("negative makespan")

    by_task: dict[str, list[ExecutionInterval]] = defaultdict(list)
    for interval in trace.intervals:
        task = task_map.get(interval.task_id)
        if task is None:
            raise AssertionError(f"interval references unknown task {interval.task_id}")
        expected_kind = "compute" if task.kind == "compute" else "comm"
        if interval.kind != expected_kind:
            raise AssertionError(
                f"interval kind mismatch for {interval.task_id}: {interval.kind} != {expected_kind}"
            )
        if interval.start < 0 or interval.end < interval.start:
            raise AssertionError(f"invalid interval: {interval}")
        if task.kind == "comm" and interval.end == interval.start:
            raise AssertionError(f"zero-duration communication interval: {interval}")
        by_task[interval.task_id].append(interval)

    started: dict[str, int] = {}
    completed: dict[str, int] = {}
    service: dict[str, int] = {}
    for task_id, task in task_map.items():
        spans = sorted(by_task.get(task_id, ()), key=lambda span: (span.start, span.end))
        actual = sum(span.end - span.start for span in spans)
        service[task_id] = actual
        if actual != task.duration:
            raise AssertionError(f"duration mismatch for {task_id}: {actual} != {task.duration}")
        if task.kind == "compute" and len(spans) != 1:
            raise AssertionError(f"compute {task_id} must have exactly one continuous interval")
        if not spans:
            raise AssertionError(f"task {task_id} has no execution interval")
        for previous, current in zip(spans, spans[1:]):
            if current.start < previous.end:
                raise AssertionError(f"overlapping intervals for {task_id}")
        started[task_id] = spans[0].start
        completed[task_id] = spans[-1].end

    for task_id, task in task_map.items():
        release = max((completed[parent] for parent in task.deps), default=0)
        if started[task_id] < release:
            raise AssertionError(
                f"precedence violation for {task_id}: start={started[task_id]}, release={release}"
            )

    communications = sorted(
        (span for span in trace.intervals if span.kind == "comm"),
        key=lambda span: (span.start, span.end, span.task_id),
    )
    for previous, current in zip(communications, communications[1:]):
        if current.start < previous.end:
            raise AssertionError(f"single-channel overlap: {previous} and {current}")

    expected_events = []
    for task_id, task in task_map.items():
        spans = sorted(by_task[task_id], key=lambda span: (span.start, span.end))
        if task.kind == "compute":
            expected_events.extend(
                (
                    _make_event(spans[0].start, "compute_started", task_id),
                    _make_event(spans[0].end, "compute_completed", task_id),
                )
            )
        else:
            for index, span in enumerate(spans):
                expected_events.append(
                    _make_event(
                        span.start,
                        "communication_started" if index == 0 else "communication_resumed",
                        task_id,
                    )
                )
                expected_events.append(
                    _make_event(
                        span.end,
                        "communication_completed" if index == len(spans) - 1 else "communication_paused",
                        task_id,
                    )
                )
    expected_events.sort(key=_event_key)
    actual_events = list(trace.events)
    if actual_events != sorted(actual_events, key=_event_key):
        raise AssertionError("trace events are not in deterministic order")
    if Counter(actual_events) != Counter(expected_events):
        raise AssertionError("trace events do not match interval boundaries")

    initial_events = [
        event
        for event in expected_events
        if event.time == 0 and event.kind.startswith("compute_")
    ]
    transition_events = [event for transition in trace.transitions for event in transition.events]
    remaining_events = list(expected_events)
    for event in initial_events:
        remaining_events.remove(event)
    if Counter(transition_events) != Counter(remaining_events):
        raise AssertionError("transition events do not reconstruct the trace")

    initial_zero_intervals = [
        span
        for span in trace.intervals
        if span.kind == "compute" and span.start == span.end == 0
    ]
    transition_intervals = [
        span for transition in trace.transitions for span in transition.intervals
    ]
    remaining_intervals = list(trace.intervals)
    for span in initial_zero_intervals:
        remaining_intervals.remove(span)
    if Counter(map(_interval_key, transition_intervals)) != Counter(
        map(_interval_key, remaining_intervals)
    ):
        raise AssertionError("transition intervals do not reconstruct the trace")

    previous_after = None
    for transition in trace.transitions:
        if previous_after is not None and transition.before != previous_after:
            raise AssertionError("transition state chain is discontinuous")
        if transition.after.time <= transition.before.time:
            raise AssertionError("transition does not advance time")
        eligible = tuple(
            task_id
            for task_id, task in task_map.items()
            if task.kind == "comm"
            and completed[task_id] > transition.before.time
            and all(completed[parent] <= transition.before.time for parent in task.deps)
        )
        if eligible:
            if transition.action.kind != "run" or transition.action.task_id not in eligible:
                raise AssertionError(
                    f"non-work-conserving action at t={transition.before.time}: "
                    f"{transition.action}, eligible={eligible}"
                )
        elif transition.action.kind != "wait":
            raise AssertionError(f"RUN without eligible communication at t={transition.before.time}")
        previous_after = transition.after
    if trace.transitions and trace.transitions[-1].after != trace.final_state:
        raise AssertionError("last transition does not end at final_state")

    makespan = max(completed.values(), default=0)
    if trace.makespan != makespan:
        raise AssertionError(f"makespan mismatch: {trace.makespan} != {makespan}")
    if len(trace.final_state.tasks) != len(expected_ids):
        raise AssertionError("final_state task count mismatch")
    for task_id, runtime in zip(expected_ids, trace.final_state.tasks, strict=True):
        if runtime.status != "completed" or runtime.remaining != 0:
            raise AssertionError(f"final state does not complete {task_id}")
        if runtime.started_at != started[task_id] or runtime.completed_at != completed[task_id]:
            raise AssertionError(f"final state timing mismatch for {task_id}")
    return ReplaySummary(makespan, started, completed, service)


def assert_preemptive_trace(model_or_dag, trace: ScheduleTrace) -> None:
    """Compatibility assertion accepting either a DAG or model with ``dag``."""

    dag = model_or_dag if isinstance(model_or_dag, DAG) else model_or_dag.dag
    replay_preemptive_trace(dag, trace)


def _make_event(time: int, kind: str, task_id: str):
    # Import only the immutable record type, never the transition engine.
    from core.execution.preemptive import TimelineEvent

    return TimelineEvent(time, kind, task_id)
