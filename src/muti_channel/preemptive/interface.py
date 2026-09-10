"""Public interface for fixed-resource preemptive scheduling."""

from __future__ import annotations

from core.dag import DAG
from core.oracle.pree_multi import exact_oracle, exact_oracle_uncompressed
from .search import rollout_sets, schedule_bounded_packing
from .solver import schedule_pack, schedule_set_policy

ALGORITHM_NAMES = (
    "longest_tail_pack",
    "resource_pack",
    "bottleneck_pack",
    "resource_downstream_pack",
    "union_downstream_set",
    "rollout_sets2d2",
    "bounded_packing",
    "exact",
    "exact_uncompressed",
)


def solve(
    dag: DAG,
    resources: dict[str, frozenset[str]],
    algorithm: str = "longest_tail_pack",
):
    algorithms = {
        "longest_tail_pack": schedule_pack,
        "resource_pack": lambda item, values: schedule_pack(
            item, values, "resource_tail"
        ),
        "bottleneck_pack": lambda item, values: schedule_pack(
            item, values, "bottleneck"
        ),
        "resource_downstream_pack": lambda item, values: schedule_pack(
            item, values, "resource_downstream"
        ),
        "union_downstream_set": schedule_set_policy,
        "rollout_sets2d2": lambda item, values: rollout_sets(
            item, values, top_k=2, depth=2
        ),
        "bounded_packing": schedule_bounded_packing,
        "exact": exact_oracle,
        "exact_uncompressed": exact_oracle_uncompressed,
    }
    try:
        implementation = algorithms[algorithm]
    except KeyError as error:
        raise ValueError(f"unknown preemptive multi-resource algorithm: {algorithm}") from error
    return implementation(dag, resources)
