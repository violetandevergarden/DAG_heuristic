"""Trace validation for fixed-resource preemptive schedules."""

from __future__ import annotations

from collections import Counter, defaultdict
from itertools import pairwise

from core.dag import DAG
from core.execution.preemptive import (
    ExecutionInterval,
    MultiResourceTrace,
    TimelineEvent,
)
from core.trace.contracts import ReplaySummary, ResourceInterval

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
        raise AssertionError(f"unknown event kind: {event.kind}")
    return event.time, _EVENT_ORDER[event.kind], event.task_id


def _events(intervals: tuple[ExecutionInterval, ...]) -> tuple[TimelineEvent, ...]:
    by_task: dict[str, list[ExecutionInterval]] = defaultdict(list)
    for interval in intervals:
        by_task[interval.task_id].append(interval)
    result: list[TimelineEvent] = []
    for task_id, spans in by_task.items():
        spans.sort(key=lambda item: (item.start, item.end))
        if spans[0].kind == "compute":
            result.extend(
                (
                    TimelineEvent(spans[0].start, "compute_started", task_id),
                    TimelineEvent(spans[0].end, "compute_completed", task_id),
                )
            )
            continue
        for index, span in enumerate(spans):
            result.extend(
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
    return tuple(sorted(result, key=_event_key))


def assert_preemptive_multi_trace(
    dag: DAG,
    resources: dict[str, frozenset[str]],
    trace: MultiResourceTrace,
) -> ReplaySummary:
    errors = dag.validate()
    if errors:
        raise AssertionError(f"cannot replay invalid DAG {dag.name}: {errors}")
    task_map = dag.task_map()
    task_ids = tuple(dag.topological_order())
    if trace.task_ids != task_ids:
        raise AssertionError("trace task order mismatch")
    comm_ids = {task.task_id for task in dag.tasks if task.kind == "comm"}
    if set(resources) != comm_ids or any(not value for value in resources.values()):
        raise AssertionError("invalid fixed-resource map")

    by_task: dict[str, list[ExecutionInterval]] = defaultdict(list)
    for interval in trace.intervals:
        task = task_map.get(interval.task_id)
        if task is None:
            raise AssertionError(f"interval references unknown task {interval.task_id}")
        expected = "compute" if task.kind == "compute" else "comm"
        if interval.kind != expected:
            raise AssertionError(f"interval kind mismatch for {interval.task_id}")
        if interval.start < 0 or interval.end < interval.start:
            raise AssertionError(f"invalid interval: {interval}")
        if interval.kind == "comm" and interval.end == interval.start:
            raise AssertionError(f"zero communication interval: {interval}")
        by_task[interval.task_id].append(interval)

    started: dict[str, int] = {}
    completed: dict[str, int] = {}
    service: dict[str, int] = {}
    for task_id, task in task_map.items():
        spans = sorted(by_task.get(task_id, ()), key=lambda item: (item.start, item.end))
        if not spans:
            raise AssertionError(f"task {task_id} has no interval")
        actual = sum(span.end - span.start for span in spans)
        if actual != task.duration:
            raise AssertionError(f"duration mismatch for {task_id}: {actual} != {task.duration}")
        if task.kind == "compute" and len(spans) != 1:
            raise AssertionError(f"compute {task_id} is not continuous")
        if any(current.start < previous.end for previous, current in pairwise(spans)):
            raise AssertionError(f"overlapping service for {task_id}")
        started[task_id], completed[task_id], service[task_id] = spans[0].start, spans[-1].end, actual

    for task_id, task in task_map.items():
        release = max((completed[parent] for parent in task.deps), default=0)
        if started[task_id] < release:
            raise AssertionError(f"precedence violation for {task_id}")

    expected_resources = tuple(
        ResourceInterval(resource, interval.task_id, interval.start, interval.end)
        for interval in trace.intervals
        if interval.kind == "comm"
        for resource in sorted(resources[interval.task_id])
    )
    if Counter(trace.resource_intervals) != Counter(expected_resources):
        raise AssertionError("resource intervals do not equal complete fixed resource acquisition")
    by_resource: dict[str, list[ResourceInterval]] = defaultdict(list)
    for interval in trace.resource_intervals:
        by_resource[interval.resource_id].append(interval)
    for resource, spans in by_resource.items():
        spans.sort(key=lambda item: (item.start, item.end, item.task_id))
        if any(current.start < previous.end for previous, current in pairwise(spans)):
            raise AssertionError(f"resource overlap on {resource}")

    if trace.events != tuple(sorted(trace.events, key=_event_key)):
        raise AssertionError("trace events are not deterministically ordered")
    if Counter(trace.events) != Counter(_events(trace.intervals)):
        raise AssertionError("events do not match interval boundaries")

    for decision in trace.decisions:
        if decision.end <= decision.start or not decision.action.communications:
            raise AssertionError("invalid multi-resource decision interval")
        selected = decision.action.communications
        if selected != tuple(sorted(set(selected))):
            raise AssertionError("unstable or duplicate selected set")
        eligible = tuple(
            task_id
            for task_id in task_ids
            if task_map[task_id].kind == "comm"
            and completed[task_id] > decision.start
            and all(completed[parent] <= decision.start for parent in task_map[task_id].deps)
        )
        if not set(selected) <= set(eligible):
            raise AssertionError("ineligible communication selected")
        used: set[str] = set()
        for task_id in selected:
            if used & resources[task_id]:
                raise AssertionError("selected set has a resource conflict")
            used.update(resources[task_id])
        if any(
            task_id not in selected
            and used.isdisjoint(resources[task_id])
            for task_id in eligible
        ):
            raise AssertionError("selected set is not inclusion-maximal")

    for idle in trace.forced_idle:
        if idle.end <= idle.start:
            raise AssertionError("forced-idle interval must advance time")
        eligible = tuple(
            task_id
            for task_id in task_ids
            if task_map[task_id].kind == "comm"
            and completed[task_id] > idle.start
            and all(completed[parent] <= idle.start for parent in task_map[task_id].deps)
        )
        if eligible or not any(
            span.kind == "compute" and span.start <= idle.start < span.end
            for span in trace.intervals
        ):
            raise AssertionError("invalid forced-idle interval")

    timeline = sorted(
        [(item.start, item.end) for item in trace.decisions]
        + [(item.start, item.end) for item in trace.forced_idle]
    )
    cursor = 0
    for start, end in timeline:
        if start != cursor:
            raise AssertionError("trace timeline has a gap or overlap")
        cursor = end
    makespan = max(completed.values(), default=0)
    if cursor != makespan or trace.makespan != makespan:
        raise AssertionError("trace makespan mismatch")
    for task_id in task_ids:
        runtime = trace.final_state.tasks[task_ids.index(task_id)]
        if runtime.status != "completed" or runtime.remaining != 0:
            raise AssertionError(f"final state does not complete {task_id}")
    return ReplaySummary(makespan, started, completed, service)


assert_multi_resource_trace = assert_preemptive_multi_trace

__all__ = ["assert_multi_resource_trace", "assert_preemptive_multi_trace"]
