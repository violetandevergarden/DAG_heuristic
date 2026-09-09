"""Trace validation for fixed-resource non-preemptive schedules."""

from __future__ import annotations

from collections import defaultdict
from itertools import pairwise

from core.dag import DAG
from core.execution.nonpreemptive import ResourceInterval, ResourceState


def assert_nonpreemptive_multi_trace(
    dag: DAG,
    resources: dict[str, frozenset[str]],
    intervals: tuple[ResourceInterval, ...],
    *,
    final_state: ResourceState | None = None,
) -> None:
    errors = dag.validate()
    if errors:
        raise AssertionError(f"cannot replay invalid DAG {dag.name}: {errors}")
    task_map = dag.task_map()
    comm_ids = {task.task_id for task in dag.tasks if task.kind == "comm"}
    if set(resources) != comm_ids or any(not value for value in resources.values()):
        raise AssertionError("invalid fixed-resource map")
    by_task: dict[str, list[ResourceInterval]] = defaultdict(list)
    for interval in intervals:
        if interval.task_id not in task_map:
            raise AssertionError(f"interval references unknown task {interval.task_id}")
        if interval.end < interval.start:
            raise AssertionError(f"invalid interval: {interval}")
        by_task[interval.task_id].append(interval)
    started: dict[str, int] = {}
    completed: dict[str, int] = {}
    task_order = tuple(dag.topological_order())
    for task_id, task in task_map.items():
        spans = sorted(by_task.get(task_id, ()), key=lambda item: (item.start, item.end))
        if not spans and task.kind == "compute":
            if final_state is not None:
                runtime = final_state.tasks[task_order.index(task_id)]
                if runtime.started_at is not None and runtime.completed_at is not None:
                    if runtime.completed_at - runtime.started_at != task.duration:
                        raise AssertionError(f"duration mismatch for {task_id}")
                    started[task_id], completed[task_id] = runtime.started_at, runtime.completed_at
            continue
        if len(spans) != 1:
            raise AssertionError(f"task {task_id} is split into {len(spans)} intervals")
        span = spans[0]
        if span.kind != task.kind or span.end - span.start != task.duration:
            raise AssertionError(f"duration or kind mismatch for {task_id}")
        started[task_id], completed[task_id] = span.start, span.end
    for task_id, task in task_map.items():
        if task_id not in started:
            continue
        release = max((completed[parent] for parent in task.deps if parent in completed), default=0)
        if started[task_id] < release:
            raise AssertionError(f"precedence violation for {task_id}")
    by_resource: dict[str, list[ResourceInterval]] = defaultdict(list)
    for interval in intervals:
        if interval.kind != "comm":
            continue
        for resource in resources[interval.task_id]:
            by_resource[resource].append(
                ResourceInterval(resource, interval.task_id, interval.start, interval.end)
            )
    for resource, spans in by_resource.items():
        spans.sort(key=lambda item: (item.start, item.end, item.task_id))
        if any(current.start < previous.end for previous, current in pairwise(spans)):
            raise AssertionError(f"resource overlap on {resource}")


assert_route_reservations = assert_nonpreemptive_multi_trace

__all__ = ["assert_nonpreemptive_multi_trace", "assert_route_reservations"]
