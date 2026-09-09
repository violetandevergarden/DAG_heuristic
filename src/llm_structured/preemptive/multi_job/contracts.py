"""Immutable contracts for preemptive multi-job scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from core.dag import DAG
from core.execution.preemptive import PreemptiveScheduleResult
from core.oracle.pree_multi import MultiOracleResult as MultiResult


@dataclass(frozen=True)
class JobSpec:
    job_id: str
    dag: DAG
    arrival: int = 0
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.job_id or "::" in self.job_id:
            raise ValueError("job_id must be non-empty and may not contain '::'")
        if self.arrival < 0:
            raise ValueError("arrival must be non-negative")
        if self.weight <= 0:
            raise ValueError("weight must be positive")


@dataclass(frozen=True)
class MultiJobInstance:
    dag: DAG
    jobs: tuple[JobSpec, ...]
    task_job: Mapping[str, str]
    original_task: Mapping[str, str]


@dataclass(frozen=True)
class JobOutcome:
    job_id: str
    arrival: int
    completion: int
    jct: int
    weight: float
    slowdown: float | None


@dataclass(frozen=True)
class MultiJobResult:
    schedule: PreemptiveScheduleResult
    jobs: tuple[JobOutcome, ...]
    weighted_jct: float
    mean_jct: float
    max_slowdown: float | None
    candidate_evaluations: int = 0
    candidate_counts: tuple[int, ...] = ()

    @property
    def makespan(self) -> int:
        return self.schedule.makespan


@dataclass(frozen=True)
class MultiResourceJobResult:
    schedule: MultiResult
    jobs: tuple[JobOutcome, ...]
    weighted_jct: float
    mean_jct: float
    max_slowdown: float | None
    jain_slowdown_fairness: float | None

    @property
    def makespan(self) -> int:
        return self.schedule.makespan


@dataclass(frozen=True)
class JobSummary:
    job_id: str
    remaining_communication: int
    residual_critical_path: int
    ready_count: int
    active_compute_count: int
    attained_service: int
    service_vacation: int
