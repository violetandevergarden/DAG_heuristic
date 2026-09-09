"""Stage 4 fixed-resource algorithm entry points."""

from __future__ import annotations

from core.dag import DAG
from llm_structured.integrated import integrated_v0, schedule_multi
from muti_channel.preemptive import solver
from .multi_barrier import schedule_selective_barrier_rollout


def solve(
    dag: DAG,
    resources: dict[str, frozenset[str]],
    algorithm: str,
):
    if algorithm == "integrated_v0":
        return schedule_multi(dag, resources, integrated_v0("fixed_multi")).schedule
    if algorithm == "barrier_selective_rollout":
        return schedule_selective_barrier_rollout(dag, resources)
    raise ValueError(f"unknown Stage 4 multi-resource algorithm: {algorithm}")
