"""Shared contracts for non-preemptive Stage 4 runtime code."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Mode = Literal["optional_idle", "work_conserving"]
PolicyName = Literal[
    "fifo",
    "fixed_order",
    "longest_tail",
    "spt",
    "lpt",
    "job_fixed_order",
    "job_round_robin",
    "job_age",
    "shortest_remaining_job",
    "job_aware_longest_tail",
    "starvation_safeguard",
]


@dataclass(frozen=True)
class JobIndex:
    """Immutable job membership index shared by baseline decision paths."""

    task_to_job: dict[str, str]
    job_to_tasks: dict[str, tuple[str, ...]]
    job_arrival: dict[str, int]
    job_weight: dict[str, float]
    job_order: tuple[str, ...]

    @classmethod
    def from_model(cls, model) -> "JobIndex":
        task_to_job: dict[str, str] = {}
        job_to_tasks: dict[str, list[str]] = {}
        arrivals: dict[str, int] = {}
        for task in model.tasks:
            labels = dict(getattr(task, "labels", ()))
            job = labels.get("job_id", task.task_id.split("::", 1)[0] if "::" in task.task_id else "job0")
            task_to_job[task.task_id] = job
            job_to_tasks.setdefault(job, []).append(task.task_id)
            if task.task_id.endswith("::__arrival__"):
                arrivals[job] = task.duration
        ordered = tuple(sorted(job_to_tasks))
        return cls(
            task_to_job,
            {job: tuple(items) for job, items in job_to_tasks.items()},
            arrivals,
            {job: 1.0 for job in ordered},
            ordered,
        )

    def job_of(self, task_id: str) -> str:
        return self.task_to_job.get(task_id, "job0")

    def with_weights(self, weights: dict[str, float]) -> "JobIndex":
        return JobIndex(
            self.task_to_job,
            self.job_to_tasks,
            self.job_arrival,
            {job: float(weights.get(job, 1.0)) for job in self.job_order},
            self.job_order,
        )


@dataclass(frozen=True, order=True)
class ActionSignature:
    kind: Literal["flow", "start", "wait"]
    task_ids: tuple[str, ...] = ()
    next_event_time: int | None = None


@dataclass(frozen=True)
class ReplaySummary:
    makespan: int
    trace_valid: bool
    voluntary_waits: int
    voluntary_wait_time: int
    forced_waits: int
    forced_wait_time: int


@dataclass(frozen=True)
class DecisionContext:
    """Read-only observations for one immutable simulator decision state."""

    state: object
    mode: Mode
    ready: tuple[str, ...]
    active_computes: tuple[str, ...]
    active_communications: tuple[str, ...]
    legal_actions: tuple[object, ...]
    tails: dict[str, int]
    next_event_distance: int | None
    occupied_resources: tuple[str, ...]
    free_resources: tuple[str, ...]
    transition_cache: dict = field(default_factory=dict, compare=False)
    completion_cache: dict = field(default_factory=dict, compare=False)
