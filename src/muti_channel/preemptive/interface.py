"""Public interface for fixed-resource preemptive scheduling."""

from __future__ import annotations

from core.dag import BenchmarkDAG
from muti_channel.preemptive import solver


def solve(
    dag: BenchmarkDAG,
    resources: dict[str, frozenset[str]],
    algorithm: str = "longest_tail_pack",
):
    algorithms = {
        "longest_tail_pack": solver.schedule_pack,
        "rollout_sets2": solver.rollout_sets,
        "exact": solver.exact_oracle,
    }
    try:
        implementation = algorithms[algorithm]
    except KeyError as error:
        raise ValueError(f"unknown preemptive multi-resource algorithm: {algorithm}") from error
    return implementation(dag, resources)
