"""Neutral in-memory representation of a DAG benchmark file."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


TaskKind = Literal["compute", "communication"]
Scenario = Literal["single_channel", "muti_channel"]


@dataclass(frozen=True)
class Resource:
    resource_id: str
    kind: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Task:
    task_id: str
    kind: TaskKind
    duration: int
    dependencies: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Benchmark:
    benchmark_id: str
    scenario: Scenario
    family: str
    category: str
    tasks: tuple[Task, ...]
    resources: tuple[Resource, ...]
    time_unit: str = "tick"
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0"
    objective: str = "makespan"

    def task_map(self) -> dict[str, Task]:
        return {task.task_id: task for task in self.tasks}

    def resource_map(self) -> dict[str, Resource]:
        return {resource.resource_id: resource for resource in self.resources}
