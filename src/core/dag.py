"""Small-DAG data types, fixtures, lower bounds, and JSON conversion.

Current non-preemptive scheduling uses :mod:`core.execution.nonpreemptive` and
:mod:`core.oracle`.  Historical benchmark helpers remain here
only because fixture generators reuse them; they are not the public oracle.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from functools import lru_cache
import json
from pathlib import Path
import random
from statistics import mean
import sys
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class BenchTask:
    task_id: str
    kind: str
    duration: int
    deps: tuple[str, ...] = ()
    role: str = ""
    cut: str = ""

    def __post_init__(self) -> None:
        if self.kind not in {"compute", "comm"}:
            raise ValueError(f"unknown task kind: {self.kind}")
        if self.duration < 0:
            raise ValueError("task duration must be non-negative")


@dataclass(frozen=True)
class BenchmarkDAG:
    name: str
    category: str
    tasks: tuple[BenchTask, ...]
    description: str = ""
    parameters: tuple[tuple[str, str], ...] = ()

    def task_map(self) -> dict[str, BenchTask]:
        return {task.task_id: task for task in self.tasks}

    def validate(self) -> list[str]:
        errors: list[str] = []
        ids = [task.task_id for task in self.tasks]
        if len(ids) != len(set(ids)):
            errors.append("duplicate task id")
        known = set(ids)
        for task in self.tasks:
            missing = set(task.deps) - known
            if missing:
                errors.append(f"{task.task_id}: unknown deps {sorted(missing)}")
        if errors:
            return errors
        try:
            topological_order(self)
        except ValueError as error:
            errors.append(str(error))
        return errors


@dataclass
class OracleResult:
    makespan: int
    decisions: list[str | None]
    explored_states: int
    lower_bounds: dict[str, int]


@dataclass
class _Builder:
    name: str
    category: str
    description: str
    tasks: list[BenchTask] = field(default_factory=list)

    def add(
        self,
        task_id: str,
        kind: str,
        duration: int,
        deps: Iterable[str] = (),
        *,
        role: str = "",
        cut: str = "",
    ) -> str:
        self.tasks.append(BenchTask(task_id, kind, duration, tuple(deps), role, cut))
        return task_id

    def finish(self, **parameters: object) -> BenchmarkDAG:
        dag = BenchmarkDAG(
            self.name,
            self.category,
            tuple(self.tasks),
            self.description,
            tuple(sorted((key, str(value)) for key, value in parameters.items())),
        )
        errors = dag.validate()
        if errors:
            raise ValueError(f"invalid generated DAG {dag.name}: {errors}")
        return dag


def topological_order(dag: BenchmarkDAG) -> list[str]:
    tasks = dag.task_map()
    children: dict[str, list[str]] = {task_id: [] for task_id in tasks}
    degree = {task_id: len(task.deps) for task_id, task in tasks.items()}
    for task in tasks.values():
        for dependency in task.deps:
            children[dependency].append(task.task_id)
    ready = sorted(task_id for task_id, value in degree.items() if value == 0)
    order: list[str] = []
    while ready:
        task_id = ready.pop(0)
        order.append(task_id)
        for child in children[task_id]:
            degree[child] -= 1
            if degree[child] == 0:
                ready.append(child)
        ready.sort()
    if len(order) != len(tasks):
        raise ValueError("benchmark graph contains a cycle")
    return order


def _indexed(dag: BenchmarkDAG):
    order = topological_order(dag)
    tasks = dag.task_map()
    index = {task_id: position for position, task_id in enumerate(order)}
    deps = tuple(tuple(index[item] for item in tasks[task_id].deps) for task_id in order)
    return order, tuple(tasks[task_id] for task_id in order), deps


# State value: -1=pending, 0=complete, >0=remaining and active/started.
State = tuple[int, ...]


def _compute_closure(tasks: tuple[BenchTask, ...], deps, state: State) -> State:
    values = list(state)
    changed = True
    while changed:
        changed = False
        for index, task in enumerate(tasks):
            if task.kind != "compute" or values[index] != -1:
                continue
            if all(values[parent] == 0 for parent in deps[index]):
                values[index] = task.duration
                changed = True
    return tuple(values)


def _ready_comms(tasks: tuple[BenchTask, ...], deps, state: State) -> list[int]:
    return [
        index
        for index, task in enumerate(tasks)
        if task.kind == "comm"
        and state[index] != 0
        and (state[index] > 0 or all(state[parent] == 0 for parent in deps[index]))
    ]


def _tick(
    tasks: tuple[BenchTask, ...],
    deps,
    state: State,
    selected: int | None,
) -> State:
    values = list(state)
    for index, task in enumerate(tasks):
        if task.kind == "compute" and values[index] > 0:
            values[index] -= 1
    if selected is not None:
        remaining = values[selected]
        if remaining == -1:
            remaining = tasks[selected].duration
        values[selected] = remaining - 1
    return tuple(values)


def _is_finished(state: State) -> bool:
    return all(value == 0 for value in state)


def _tail_lengths(dag: BenchmarkDAG) -> dict[str, int]:
    order = topological_order(dag)
    tasks = dag.task_map()
    children: dict[str, list[str]] = {task_id: [] for task_id in order}
    for task in tasks.values():
        for dependency in task.deps:
            children[dependency].append(task.task_id)
    tail: dict[str, int] = {}
    for task_id in reversed(order):
        tail[task_id] = max(
            (tasks[child].duration + tail[child] for child in children[task_id]),
            default=0,
        )
    return tail


def lower_bounds(dag: BenchmarkDAG) -> dict[str, int]:
    """Return P, Q, L, window, cut and their maximum.

    ``window`` is the smallest horizon satisfying all necessary preemptive
    release/deadline demand inequalities derived from precedence-only earliest
    starts and downstream tails.  ``cut`` is the largest explicitly labelled
    communication-cut load; under one channel it is intentionally dominated
    by P, but remains useful when the same benchmark is lifted to multi-link
    models.
    """

    order = topological_order(dag)
    tasks = dag.task_map()
    children: dict[str, list[str]] = {task_id: [] for task_id in order}
    for task in tasks.values():
        for dependency in task.deps:
            children[dependency].append(task.task_id)

    earliest_finish: dict[str, int] = {}
    pure_compute: dict[str, int] = {}
    for task_id in order:
        task = tasks[task_id]
        pred_finish = max((earliest_finish[item] for item in task.deps), default=0)
        pred_compute = max((pure_compute[item] for item in task.deps), default=0)
        earliest_finish[task_id] = pred_finish + task.duration
        pure_compute[task_id] = pred_compute + (
            task.duration if task.kind == "compute" else 0
        )

    downstream: dict[str, int] = {}
    for task_id in reversed(order):
        downstream[task_id] = max(
            (tasks[child].duration + downstream[child] for child in children[task_id]),
            default=0,
        )

    comms = [task for task in tasks.values() if task.kind == "comm"]
    p_bound = sum(task.duration for task in comms)
    q_bound = max(pure_compute.values(), default=0)
    l_bound = max(earliest_finish.values(), default=0)
    cut_loads: Counter[str] = Counter()
    for task in comms:
        if task.cut:
            cut_loads[task.cut] += task.duration
    cut_bound = max(cut_loads.values(), default=0)

    base = max(p_bound, q_bound, l_bound, cut_bound)
    releases = {
        task.task_id: max((earliest_finish[item] for item in task.deps), default=0)
        for task in comms
    }

    def demand_feasible(horizon: int) -> bool:
        windows = [
            (releases[task.task_id], horizon - downstream[task.task_id], task.duration)
            for task in comms
        ]
        if any(release + duration > deadline for release, deadline, duration in windows):
            return False
        endpoints_a = {0, *(release for release, _deadline, _duration in windows)}
        endpoints_b = {horizon, *(deadline for _release, deadline, _duration in windows)}
        for start in endpoints_a:
            for end in endpoints_b:
                if end < start:
                    continue
                demand = sum(
                    duration
                    for release, deadline, duration in windows
                    if release >= start and deadline <= end
                )
                if demand > end - start:
                    return False
        return True

    serial_horizon = sum(task.duration for task in tasks.values())
    window_bound = base
    while window_bound <= serial_horizon and not demand_feasible(window_bound):
        window_bound += 1
    if window_bound > serial_horizon:
        window_bound = serial_horizon
    result = {
        "P": p_bound,
        "Q": q_bound,
        "L": l_bound,
        "window": window_bound,
        "cut": cut_bound,
    }
    result["combined"] = max(result.values())
    return result
