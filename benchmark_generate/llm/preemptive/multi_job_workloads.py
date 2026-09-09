"""Small J0--J6 multi-job workloads with fixed-resource provenance."""

from __future__ import annotations

from dataclasses import dataclass

from llm_structured.preemptive.multi_job.solver import JobSpec, MultiJobInstance, build_parallel_chain_job, compose_jobs


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
