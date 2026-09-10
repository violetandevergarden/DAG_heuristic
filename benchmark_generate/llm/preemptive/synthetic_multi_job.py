"""Small J0--J6 multi-job workloads with fixed-resource provenance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from core.dag import DAG, Task


@dataclass(frozen=True)
class JobSpec:
    job_id: str
    dag: DAG
    arrival: int = 0
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.job_id or "::" in self.job_id or self.arrival < 0 or self.weight <= 0:
            raise ValueError("invalid job specification")


@dataclass(frozen=True)
class MultiJobInstance:
    dag: DAG
    jobs: tuple[JobSpec, ...]
    task_job: Mapping[str, str]
    original_task: Mapping[str, str]


def build_parallel_chain_job(
    name: str, chains: Sequence[tuple[int, Sequence[int], Sequence[int]]]
) -> DAG:
    tasks: list[Task] = []
    for chain_index, (release, communications, computes) in enumerate(chains):
        if len(communications) != len(computes):
            raise ValueError("communication and compute sequences must align")
        previous = None
        if release:
            previous = f"c{chain_index}_release"
            tasks.append(Task(previous, "compute", release, labels=(("task_role", "RELEASE"),)))
        for operation, (communication, compute) in enumerate(zip(communications, computes, strict=True)):
            flow = f"c{chain_index}_flow{operation}"
            tasks.append(Task(flow, "comm", communication, () if previous is None else (previous,),
                              labels=(("task_role", f"CHAIN_{chain_index}_COMM"),)))
            previous = f"c{chain_index}_compute{operation}"
            tasks.append(Task(previous, "compute", compute, (flow,),
                              labels=(("task_role", f"CHAIN_{chain_index}_COMPUTE"),)))
    return DAG(name, tuple(tasks), context=(("category", "multi_job_fixture"),))


def compose_jobs(specs: Sequence[JobSpec]) -> MultiJobInstance:
    jobs = tuple(specs)
    if not jobs or len({job.job_id for job in jobs}) != len(jobs):
        raise ValueError("jobs must be non-empty and have unique ids")
    tasks: list[Task] = []
    task_job: dict[str, str] = {}
    original_task: dict[str, str] = {}
    for job in jobs:
        if job.dag.validate():
            raise ValueError(f"invalid job DAG {job.job_id}")
        release = f"{job.job_id}::__arrival__"
        tasks.append(Task(release, "compute", job.arrival, labels=(("task_role", "JOB_ARRIVAL"),)))
        task_job[release] = job.job_id
        original_task[release] = "__arrival__"
        for task in job.dag.tasks:
            task_id = f"{job.job_id}::{task.task_id}"
            dependencies = tuple(f"{job.job_id}::{dep}" for dep in task.deps) or (release,)
            tasks.append(Task(task_id, task.kind, task.duration, dependencies, labels=task.labels))
            task_job[task_id] = job.job_id
            original_task[task_id] = task.task_id
    dag = DAG("multi_job__" + "__".join(job.job_id for job in jobs), tuple(tasks),
              context=(("category", "multi_job"),))
    if dag.validate():
        raise ValueError("invalid composed DAG")
    return MultiJobInstance(dag, jobs, task_job, original_task)


@dataclass(frozen=True)
class MultiJobWorkload:
    family: str
    instance: MultiJobInstance
    resources: dict[str, frozenset[str]]
    description: str


def _resources(instance, mode: str):
    result = {}
    for task_id, original in instance.original_task.items():
        if original == "__arrival__" or instance.dag.task_map()[task_id].kind != "comm":
            continue
        owner = instance.task_job[task_id]
        chain = original.split("_")[0]
        if mode == "shared":
            footprint = {"fabric"}
        elif mode == "complementary":
            footprint = {f"link_{owner}"}
        elif mode == "hotspot":
            footprint = {"fabric", f"link_{owner}"} if chain == "c0" else {f"link_{owner}"}
        else:
            footprint = {"fabric"} if chain == "c0" else {f"private_{owner}"}
        result[task_id] = frozenset(footprint)
    return result


def multi_job_workloads() -> tuple[MultiJobWorkload, ...]:
    short = build_parallel_chain_job("short", ((0, (2, 2), (4, 2)),))
    long = build_parallel_chain_job("long", ((0, (5, 4), (7, 5)), (1, (3,), (4,))))
    phase = build_parallel_chain_job("phase", ((0, (2, 3), (6, 1)), (3, (2,), (5,))))
    specs = (
        ("J0", (JobSpec("A", short), JobSpec("B", short)), "shared", "isomorphic simultaneous jobs"),
        ("J1", (JobSpec("A", short), JobSpec("B", short, arrival=3)), "shared", "arrival offset"),
        ("J2", (JobSpec("A", phase), JobSpec("B", phase, arrival=2)), "complementary", "phase-offset complementary resources"),
        ("J3", (JobSpec("A", short), JobSpec("B", long)), "shared", "heterogeneous remaining work"),
        ("J4", (JobSpec("TP", phase), JobSpec("DP", long)), "mixed", "different LLM-role-shaped chains"),
        ("J5", (JobSpec("A", long), JobSpec("B", phase)), "hotspot", "heterogeneous resource footprints"),
        ("J6", (JobSpec("VIP", long, weight=4), JobSpec("S", short), JobSpec("L", long)), "shared", "weight and starvation adversarial"),
    )
    rows = []
    for family, jobs, mode, description in specs:
        instance = compose_jobs(jobs)
        rows.append(MultiJobWorkload(family, instance, _resources(instance, mode), description))
    return tuple(rows)
