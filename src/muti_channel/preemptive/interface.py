"""Public interface for fixed-resource preemptive scheduling."""

from __future__ import annotations

from core.dag import BenchmarkDAG
from muti_channel.preemptive import solver

ALGORITHM_NAMES = (
    "longest_tail_pack",
    "resource_pack",
    "bottleneck_pack",
    "resource_downstream_pack",
    "union_downstream_set",
    "barrier_safeguarded",
    "barrier_selective_rollout",
    "rollout_sets2d2",
    "exact",
    "exact_uncompressed",
)


def solve(
    dag: BenchmarkDAG,
    resources: dict[str, frozenset[str]],
    algorithm: str = "longest_tail_pack",
):
    algorithms = {
        "longest_tail_pack": solver.schedule_pack,
        "resource_pack": lambda item, values: solver.schedule_pack(
            item, values, "resource_tail"
        ),
        "bottleneck_pack": lambda item, values: solver.schedule_pack(
            item, values, "bottleneck"
        ),
        "resource_downstream_pack": lambda item, values: solver.schedule_pack(
            item, values, "resource_downstream"
        ),
        "union_downstream_set": solver.schedule_set_policy,
        "barrier_safeguarded": solver.schedule_barrier_set_safeguarded,
        "barrier_selective_rollout": solver.schedule_selective_barrier_rollout,
        "rollout_sets2d2": lambda item, values: solver.rollout_sets(
            item, values, top_k=2, depth=2
        ),
        "exact": solver.exact_oracle,
        "exact_uncompressed": solver.exact_oracle_uncompressed,
    }
    try:
        implementation = algorithms[algorithm]
    except KeyError as error:
        raise ValueError(f"unknown preemptive multi-resource algorithm: {algorithm}") from error
    return implementation(dag, resources)
