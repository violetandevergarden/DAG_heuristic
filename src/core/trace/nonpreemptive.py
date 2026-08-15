"""Trace validation for the maintenance non-preemptive execution model."""

from __future__ import annotations

from itertools import pairwise

from core.execution.nonpreemptive import ExecutionInterval, ScheduleTrace


def assert_nonpreemptive_trace(trace: ScheduleTrace) -> None:
    """Preserve the historical v1 trace contract during directory migration."""

    by_task: dict[str, list[ExecutionInterval]] = {}
    for interval in trace.intervals:
        if interval.end < interval.start:
            raise AssertionError(f"negative interval: {interval}")
        if interval.kind == "comm" and interval.end == interval.start:
            raise AssertionError(f"zero-duration communication: {interval}")
        by_task.setdefault(interval.task_id, []).append(interval)
    duplicates = {task_id: spans for task_id, spans in by_task.items() if len(spans) > 1}
    if duplicates:
        raise AssertionError(f"tasks executed in multiple intervals: {duplicates}")
    for task_id, runtime in zip(trace.task_ids, trace.final_state.tasks, strict=True):
        spans = by_task.get(task_id, [])
        if runtime.status == "completed" and len(spans) != 1:
            raise AssertionError(
                f"completed task {task_id} has {len(spans)} execution intervals"
            )
        if spans and (
            spans[0].start != runtime.started_at
            or spans[0].end != runtime.completed_at
        ):
            raise AssertionError(
                f"interval/runtime mismatch for {task_id}: {spans[0]} vs {runtime}"
            )
    comms = sorted(
        (interval for interval in trace.intervals if interval.kind == "comm"),
        key=lambda interval: interval.start,
    )
    for previous, current in pairwise(comms):
        if previous.end > current.start:
            raise AssertionError(
                f"communication intervals overlap: {previous} and {current}"
            )
