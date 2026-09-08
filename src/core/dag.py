"""Shared small-DAG data types, construction helpers, and lower bounds."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Hashable


@dataclass(frozen=True)
class Task:
    task_id: str
    kind: str
    duration: int
    deps: tuple[str, ...] = ()
    labels: tuple[tuple[str, str], ...] = ()
    resources: frozenset[Hashable] = frozenset()
    # label包含role，用来早期分析可能的优先级策略，可能包含PP、DP、barrier等信息
    # label包含cut，用于计算同一个cut的lower_bounds，需要手动设置，非自动生成
    # label还会包含(phase, micro-batch, pipeline stage, parallelism dimension, 
    # collective type, layer/block and repetition group)等别的信息
    def __post_init__(self) -> None:
        object.__setattr__(self, "resources", frozenset(self.resources))
        if self.kind not in {"compute", "comm"}:
            raise ValueError(f"unknown task kind: {self.kind}")
        if self.duration < 0:
            raise ValueError("task duration must be non-negative")
        if self.kind == "compute" and self.resources:
            raise ValueError("compute tasks cannot require resources")
        if any(resource is None for resource in self.resources):
            raise ValueError("task resource ids cannot be None")
        keys: set[str] = set()
        for key, value in self.labels:
            if not key:
                raise ValueError("task label keys must be non-empty")
            if key in keys:
                raise ValueError(f"duplicate task label key: {key}")
            keys.add(key)

    def label_map(self) -> dict[str, str]:
        return dict(self.labels)


@dataclass(frozen=True)
class DAG:
    name: str
    tasks: tuple[Task, ...]
    context: tuple[tuple[str, str], ...] = ()
    parameters: tuple[tuple[str, str], ...] = ()
    # context包含category，用来分辨此DAG属于random、adverse等类别
    # context包含description，用于描述此DAG，供人类阅读

    def context_map(self) -> dict[str, str]:
        return dict(self.context)

    @property
    def resources(self) -> dict[str, frozenset[Hashable]]:
        """Return fixed resource requirements indexed by communication id."""
        return {
            task.task_id: task.resources
            for task in self.tasks
            if task.kind == "comm"
        }

    @property
    def dag(self) -> DAG:
        """Self-reference retained while callers migrate from instance wrappers."""
        return self

    def with_resources(
        self, resources: dict[str, frozenset[Hashable]]
    ) -> DAG:
        task_ids = {task.task_id for task in self.tasks}
        unknown = set(resources) - task_ids
        if unknown:
            raise ValueError(f"resources for unknown tasks: {sorted(unknown)}")
        return replace(
            self,
            tasks=tuple(
                replace(task, resources=frozenset(resources.get(task.task_id, ())))
                for task in self.tasks
            ),
        )

    def task_map(self) -> dict[str, Task]:
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
            self.topological_order()
        except ValueError as error:
            errors.append(str(error))
        return errors

    def topological_order(self) -> list[str]:
        tasks = self.task_map()
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

    def lower_bounds(self) -> dict[str, int]:
        """Return P, Q, L, window, cut and their maximum."""
        # P：所有通信任务的总持续时间
        # Q：所有纯计算路径的最大累计时间
        # L：所有任务的最早完成时间的最大值
        # cut：同一cut标签的最长总持续时间
        order = self.topological_order()
        tasks = self.task_map()
        children: dict[str, list[str]] = {task_id: [] for task_id in order}
        for task in tasks.values():
            for dependency in task.deps:
                children[dependency].append(task.task_id)

        earliest_finish: dict[str, int] = {}
        pure_compute: dict[str, int] = {}
        for task_id in order:
            task = tasks[task_id]
            predecessor_finish = max(
                (earliest_finish[item] for item in task.deps), default=0
            )
            predecessor_compute = max(
                (pure_compute[item] for item in task.deps), default=0
            )
            earliest_finish[task_id] = predecessor_finish + task.duration
            pure_compute[task_id] = predecessor_compute + (
                task.duration if task.kind == "compute" else 0
            )

        downstream: dict[str, int] = {}
        for task_id in reversed(order):
            downstream[task_id] = max(
                (tasks[child].duration + downstream[child] for child in children[task_id]),
                default=0,
            )

        communications = [task for task in tasks.values() if task.kind == "comm"]
        communication_load = sum(task.duration for task in communications)
        compute_path = max(pure_compute.values(), default=0)
        critical_path = max(earliest_finish.values(), default=0)
        cut_loads: Counter[str] = Counter()
        for task in communications:
            cut = task.label_map().get("cut", "")
            if cut:
                cut_loads[cut] += task.duration
        cut_load = max(cut_loads.values(), default=0)

        base = max(communication_load, compute_path, critical_path, cut_load)
        releases = {
            task.task_id: max((earliest_finish[item] for item in task.deps), default=0)
            for task in communications
        }

        def demand_feasible(horizon: int) -> bool:
            windows = [
                (releases[task.task_id], horizon - downstream[task.task_id], task.duration)
                for task in communications
            ]
            if any(release + duration > deadline for release, deadline, duration in windows):
                return False
            starts = {0, *(release for release, _deadline, _duration in windows)}
            ends = {horizon, *(deadline for _release, deadline, _duration in windows)}
            for start in starts:
                for end in ends:
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
        result = {
            "P": communication_load,
            "Q": compute_path,
            "L": critical_path,
            "window": min(window_bound, serial_horizon),
            "cut": cut_load,
        }
        result["combined"] = max(result.values())
        return result


@dataclass
class DAGBuilder:
    name: str
    context: tuple[tuple[str, str], ...] = ()
    tasks: list[Task] = field(default_factory=list)

    def add(
        self,
        task_id: str,
        kind: str,
        duration: int,
        deps: Iterable[str] = (),
        *,
        labels: tuple[tuple[str, str], ...] = (),
        resources: frozenset[Hashable] = frozenset(),
    ) -> str:
        self.tasks.append(Task(task_id, kind, duration, tuple(deps), labels, resources))
        return task_id

    def finish(self, **parameters: object) -> DAG:
        dag = DAG(
            self.name,
            tuple(self.tasks),
            context=self.context,
            parameters=tuple(sorted((key, str(value)) for key, value in parameters.items())),
        )
        errors = dag.validate()
        if errors:
            raise ValueError(f"invalid generated DAG {dag.name}: {errors}")
        return dag
