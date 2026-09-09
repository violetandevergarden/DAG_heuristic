"""Composition of independently arriving jobs into one shared-channel DAG."""

from __future__ import annotations

from collections.abc import Sequence

from core.dag import DAG, Task

from .contracts import JobSpec, MultiJobInstance


def prefixed(job_id: str, task_id: str) -> str:
    return f"{job_id}::{task_id}"


def compose_jobs(specs: Sequence[JobSpec]) -> MultiJobInstance:
    """Prefix and combine jobs while encoding arrival as a release compute."""

    jobs = tuple(specs)
    if not jobs:
        raise ValueError("at least one job is required")
    if len({job.job_id for job in jobs}) != len(jobs):
        raise ValueError("job IDs must be unique")
    tasks: list[Task] = []
    task_job: dict[str, str] = {}
    original_task: dict[str, str] = {}
    for job in jobs:
        errors = job.dag.validate()
        if errors:
            raise ValueError(f"invalid job DAG {job.job_id}: {errors}")
        release = prefixed(job.job_id, "__arrival__")
        tasks.append(Task(release, "compute", job.arrival, labels=(("task_role", "JOB_ARRIVAL"),)))
        task_job[release] = job.job_id
        original_task[release] = "__arrival__"
        for task in job.dag.tasks:
            task_id = prefixed(job.job_id, task.task_id)
            dependencies = tuple(prefixed(job.job_id, dep) for dep in task.deps)
            if not task.deps:
                dependencies = (release,)
            tasks.append(Task(task_id, task.kind, task.duration, dependencies, labels=task.labels))
            task_job[task_id] = job.job_id
            original_task[task_id] = task.task_id
    dag = DAG(
        "multi_job__" + "__".join(job.job_id for job in jobs),
        tuple(tasks),
        context=(("category", "multi_job"), ("description", "Disjoint job DAGs coupled only by the shared communication channel.")),
        parameters=tuple((f"arrival:{job.job_id}", str(job.arrival)) for job in jobs),
    )
    errors = dag.validate()
    if errors:
        raise ValueError(f"invalid composed DAG: {errors}")
    return MultiJobInstance(dag, jobs, task_job, original_task)


def build_parallel_chain_job(
    name: str,
    chains: Sequence[tuple[int, Sequence[int], Sequence[int]]],
) -> DAG:
    """Build the small parallel-chain fixture used by multi-job studies."""

    tasks: list[Task] = []
    for chain_index, (release, communications, computes) in enumerate(chains):
        if len(communications) != len(computes):
            raise ValueError("communication and compute sequences must align")
        previous: str | None = None
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
