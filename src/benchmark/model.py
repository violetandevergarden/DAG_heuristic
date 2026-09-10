"""Neutral in-memory representation of a DAG benchmark file."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


TaskKind = Literal["compute", "communication"]
Scenario = Literal["single_channel", "muti_channel"]


@dataclass(frozen=True)
class SchedulingSemantics:
    """Execution contract carried by every self-contained benchmark."""

    preemption: Literal["none", "communication_resume"] = "none"
    decision_epoch: Literal["task_completion", "task_event"] = "task_completion"
    optional_idle: bool = True
    compute_model: Literal["unbounded_parallel"] = "unbounded_parallel"
    resource_model: Literal["exclusive", "exclusive_fixed_set"] = "exclusive"
    preemption_cost: int = 0
    minimum_quantum: int = 0

    @property
    def is_preemptive(self) -> bool:
        return self.preemption != "none"

    @property
    def work_conserving(self) -> bool:
        return not self.optional_idle


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
    semantics: SchedulingSemantics = field(default_factory=SchedulingSemantics)
    time_unit: str = "tick"
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0"
    objective: str = "makespan"

    def task_map(self) -> dict[str, Task]:
        return {task.task_id: task for task in self.tasks}

    def resource_map(self) -> dict[str, Resource]:
        return {resource.resource_id: resource for resource in self.resources}
