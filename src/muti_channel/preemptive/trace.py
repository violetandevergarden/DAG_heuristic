"""Independent replay validation for fixed-resource preemptive traces."""

from __future__ import annotations

from collections import Counter, defaultdict
from itertools import pairwise

from core.dag import BenchmarkDAG, topological_order
from core.execution.multi_resource import MultiResourceTrace
from core.execution.preemptive import ExecutionInterval, TimelineEvent
from core.trace.common import ReplaySummary, ResourceInterval

_EVENT_ORDER = {
    "compute_completed": 0,
    "communication_completed": 1,
    "communication_paused": 2,
    "compute_started": 3,
    "communication_started": 4,
    "communication_resumed": 5,
}


def assert_multi_resource_trace(
    dag: BenchmarkDAG,
    resources: dict[str, frozenset[str]],
    trace: MultiResourceTrace,
) -> ReplaySummary:
    errors = dag.validate()
    if errors:
        raise AssertionError(f"cannot replay invalid DAG {dag.name}: {errors}")
    task_map = dag.task_map()
    expected_ids = tuple(topological_order(dag))
    if trace.task_ids != expected_ids:
        raise AssertionError("trace task order mismatch")
    comm_ids = {task.task_id for task in dag.tasks if task.kind == "comm"}
    if set(resources) != comm_ids or any(not value for value in resources.values()):
        raise AssertionError("invalid fixed-resource map")

    by_task: dict[str, list[ExecutionInterval]] = defaultdict(list)
    for interval in trace.intervals:
        task = task_map.get(interval.task_id)
        if task is None:
            raise AssertionError(f"interval references unknown task {interval.task_id}")
        expected_kind = "compute" if task.kind == "compute" else "comm"
        if interval.kind != expected_kind:
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
        for previous, current in pairwise(spans):
            if current.start < previous.end:
                raise AssertionError(f"overlapping service for {task_id}")
        started[task_id] = spans[0].start
        completed[task_id] = spans[-1].end
        service[task_id] = actual

    for task_id, task in task_map.items():
        release = max((completed[parent] for parent in task.deps), default=0)
        if started[task_id] < release:
            raise AssertionError(f"precedence violation for {task_id}")

    expected_resource = tuple(
        ResourceInterval(resource, interval.task_id, interval.start, interval.end)
        for interval in trace.intervals
        if interval.kind == "comm"
        for resource in sorted(resources[interval.task_id])
    )
    if Counter(trace.resource_intervals) != Counter(expected_resource):
        raise AssertionError("resource intervals do not equal complete fixed resource acquisition")
    by_resource: dict[str, list[ResourceInterval]] = defaultdict(list)
    for interval in trace.resource_intervals:
        by_resource[interval.resource_id].append(interval)
    for resource, spans in by_resource.items():
        spans.sort(key=lambda item: (item.start, item.end, item.task_id))
        for previous, current in pairwise(spans):
            if current.start < previous.end:
                raise AssertionError(
                    f"resource overlap on {resource}: {previous.task_id}, {current.task_id}"
                )

    expected_events = _events_from_intervals(trace.intervals)
    if trace.events != tuple(sorted(trace.events, key=_event_key)):
        raise AssertionError("trace events are not deterministically ordered")
    if Counter(trace.events) != Counter(expected_events):
        raise AssertionError("events do not match interval boundaries")

    for decision in trace.decisions:
        if decision.end <= decision.start:
            raise AssertionError("decision interval must advance time")
        selected = decision.action.communications
        if len(selected) != len(set(selected)) or selected != tuple(sorted(selected)):
            raise AssertionError(f"unstable or duplicate selected set: {selected}")
        eligible = tuple(
            task_id
            for task_id in expected_ids
            if task_map[task_id].kind == "comm"
            and completed[task_id] > decision.start
            and all(completed[parent] <= decision.start for parent in task_map[task_id].deps)
        )
        if not selected:
            raise AssertionError("forced idle must not be recorded as a scheduler decision")
        if not set(selected) <= set(eligible):
            raise AssertionError(f"ineligible communication selected at t={decision.start}")
        used: set[str] = set()
        for task_id in selected:
            if used & resources[task_id]:
                raise AssertionError(f"selected set conflicts at t={decision.start}")
            used.update(resources[task_id])
            spans = by_task[task_id]
            if not any(
                span.start <= decision.start and span.end >= decision.end for span in spans
            ):
                raise AssertionError(f"selected {task_id} lacks service for decision interval")
        for task_id in eligible:
            if task_id not in selected and not (used & resources[task_id]):
                raise AssertionError(
                    f"selected set is not inclusion-maximal at t={decision.start}: add {task_id}"
                )

    for idle in trace.forced_idle:
        if idle.end <= idle.start:
            raise AssertionError("forced-idle interval must advance time")
        eligible = tuple(
            task_id
            for task_id in expected_ids
            if task_map[task_id].kind == "comm"
            and completed[task_id] > idle.start
            and all(completed[parent] <= idle.start for parent in task_map[task_id].deps)
        )
        if eligible:
            raise AssertionError(f"forced idle at t={idle.start} has eligible={eligible}")
        active_compute = any(
            span.kind == "compute" and span.start <= idle.start < span.end
            for span in trace.intervals
        )
        if not active_compute:
            raise AssertionError(f"forced idle has no future compute at t={idle.start}")

    timeline_segments = sorted(
        [
            *( (decision.start, decision.end, "decision") for decision in trace.decisions ),
            *( (idle.start, idle.end, "forced_idle") for idle in trace.forced_idle ),
        ],
        key=lambda item: (item[0], item[1], item[2]),
    )
    cursor = 0
    for start, end, kind in timeline_segments:
        if start != cursor:
            raise AssertionError(
                f"trace timeline has a gap or overlap before {kind}: {cursor} -> {start}"
            )
        cursor = end

    makespan = max(completed.values(), default=0)
    if cursor != makespan:
        raise AssertionError(f"trace timeline ends at {cursor}, expected {makespan}")
    if trace.makespan != makespan:
        raise AssertionError(f"makespan mismatch: {trace.makespan} != {makespan}")
    if len(trace.final_state.tasks) != len(expected_ids):
        raise AssertionError("final state task count mismatch")
    for task_id, runtime in zip(expected_ids, trace.final_state.tasks, strict=True):
        if runtime.status != "completed" or runtime.remaining != 0:
            raise AssertionError(f"final state does not complete {task_id}")
    return ReplaySummary(makespan, started, completed, service)


def _event_key(event: TimelineEvent) -> tuple[int, int, str]:
    if event.kind not in _EVENT_ORDER:
        raise AssertionError(f"unknown event kind: {event.kind}")
    return (event.time, _EVENT_ORDER[event.kind], event.task_id)


def _events_from_intervals(
    intervals: tuple[ExecutionInterval, ...],
) -> tuple[TimelineEvent, ...]:
    by_task: dict[str, list[ExecutionInterval]] = defaultdict(list)
    for interval in intervals:
        by_task[interval.task_id].append(interval)
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
        else:
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
    return tuple(sorted(events, key=_event_key))
