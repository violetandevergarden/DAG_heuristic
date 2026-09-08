"""Shared DAG indexing and compute-runtime operations for execution models."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from core.dag import DAG, Task
from core.execution.contracts import ExecutionInterval, RuntimeTask, TimelineEvent


@dataclass(frozen=True)
class DAGTopology:
    """Immutable task ordering and dependency indexes derived from a DAG."""

    dag: DAG
    task_ids: tuple[str, ...]
    tasks: tuple[Task, ...]
    index: dict[str, int]
    deps: tuple[tuple[int, ...], ...]
    children: tuple[tuple[int, ...], ...]
    compute_indices: tuple[int, ...]
    communication_indices: tuple[int, ...]
    durations: tuple[int, ...]

    @classmethod
    def from_dag(cls, dag: DAG) -> "DAGTopology":
        task_ids = tuple(dag.topological_order())
        task_map = dag.task_map()
        tasks = tuple(task_map[task_id] for task_id in task_ids)
        index = {task_id: position for position, task_id in enumerate(task_ids)}
        deps = tuple(tuple(index[parent] for parent in task.deps) for task in tasks)
        child_lists: list[list[int]] = [[] for _ in tasks]
        for child, task in enumerate(tasks):
            for parent in task.deps:
                child_lists[index[parent]].append(child)
        return cls(
            dag,
            task_ids,
            tasks,
            index,
            deps,
            tuple(tuple(items) for items in child_lists),
            tuple(position for position, task in enumerate(tasks) if task.kind == "compute"),
            tuple(position for position, task in enumerate(tasks) if task.kind == "comm"),
            tuple(task.duration for task in tasks),
        )


def dependencies_completed(
    runtimes: Sequence[RuntimeTask], deps: Sequence[Sequence[int]], task_index: int
) -> bool:
    return all(runtimes[parent].status == "completed" for parent in deps[task_index])


def running_compute_indices(
    compute_indices: Sequence[int], runtimes: Sequence[RuntimeTask]
) -> list[int]:
    return [
        index
        for index in compute_indices
        if runtimes[index].status == "running"
    ]


def advance_running_computes(
    tasks: Sequence[Task],
    compute_indices: Sequence[int],
    runtimes: Sequence[RuntimeTask],
    start: int,
    delta: int,
) -> tuple[list[RuntimeTask], list[TimelineEvent], list[ExecutionInterval]]:
    if delta <= 0:
        raise ValueError("time advancement must be positive")
    end = start + delta
    values = list(runtimes)
    events: list[TimelineEvent] = []
    intervals: list[ExecutionInterval] = []
    for index in running_compute_indices(compute_indices, values):
        runtime = values[index]
        remaining = runtime.remaining - delta
        if remaining < 0:
            raise AssertionError("advanced beyond compute completion")
        if remaining == 0:
            values[index] = RuntimeTask("completed", 0, runtime.started_at, end)
            task_id = tasks[index].task_id
            events.append(TimelineEvent(end, "compute_completed", task_id))
            assert runtime.started_at is not None
            intervals.append(ExecutionInterval(task_id, "compute", runtime.started_at, end))
        else:
            values[index] = RuntimeTask("running", remaining, runtime.started_at, None)
    return values, events, intervals


def start_ready_computes(
    tasks: Sequence[Task],
    deps: Sequence[Sequence[int]],
    time: int,
    runtimes: Sequence[RuntimeTask],
) -> tuple[list[RuntimeTask], list[TimelineEvent], list[ExecutionInterval]]:
    values = list(runtimes)
    events: list[TimelineEvent] = []
    intervals: list[ExecutionInterval] = []
    for index, task in enumerate(tasks):
        if task.kind != "compute" or values[index].status != "pending":
            continue
        if not dependencies_completed(values, deps, index):
            continue
        events.append(TimelineEvent(time, "compute_started", task.task_id))
        if task.duration == 0:
            values[index] = RuntimeTask("completed", 0, time, time)
            events.append(TimelineEvent(time, "compute_completed", task.task_id))
            intervals.append(ExecutionInterval(task.task_id, "compute", time, time))
        else:
            values[index] = RuntimeTask("running", task.duration, time, None)
    return values, events, intervals
