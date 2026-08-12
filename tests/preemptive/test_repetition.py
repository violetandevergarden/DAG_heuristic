from __future__ import annotations

from benchmark_generate.simai.export import (
    build_synthetic_input,
    build_workload,
    to_benchmark,
)
from benchmark_generate.simai.repetition import scan_repetition
from benchmark_generate.simai.repetition_study import _raw_b_to_w_edges
from preemptive.repetition import (
    build_exchangeable_replicas,
    build_pp_dp_repetition,
    exact_oracle_component_symmetry,
    schedule_coupling_aware,
    schedule_role_copy,
)
from preemptive.single_channel.solver import exact_oracle


def test_scanner_separates_repetition_from_exchangeability() -> None:
    header, items = build_synthetic_input(pp=2, ga=4, layers=2)
    benchmark = to_benchmark(
        build_workload("1f1b", header, items),
        "repeat_scan",
    )
    report = scan_repetition(benchmark)

    assert report.detected_period == 1
    assert report.structural_repetition > 0.5
    assert report.conservative_exchangeable_task_fraction == 0.0
    assert report.cross_microbatch_conflict_fraction > 0.5


def test_zero_bubble_separates_data_fork_from_compute_order() -> None:
    header, items = build_synthetic_input(
        pp=2, tp=2, dp=2, ga=4, layers=2,
    )
    built = build_workload("zero_bubble", header, items)
    benchmark = to_benchmark(built, "zero_bubble_semantics")

    # The source data DAG has no same-pair B -> W dependency.  The exported
    # benchmark still encodes the serializer's single-GPU compute order.
    assert _raw_b_to_w_edges(built) == 0
    assert scan_repetition(benchmark).direct_b_to_w_edges > 0


def test_independent_local_optimum_does_not_safely_copy() -> None:
    one = build_pp_dp_repetition(1)
    many = build_pp_dp_repetition(8)

    # DP first is strictly better in the isolated period.
    assert schedule_role_copy(one, "DP").makespan < schedule_role_copy(one, "PP").makespan
    exact = exact_oracle(many)
    copied = schedule_role_copy(many, "DP")
    aware = schedule_coupling_aware(many)

    assert copied.makespan > exact.makespan
    assert aware.makespan == exact.makespan


def test_component_symmetry_is_exact_and_reduces_states() -> None:
    dag, components = build_exchangeable_replicas(5)
    generic = exact_oracle(dag, max_states=100_000)
    compressed = exact_oracle_component_symmetry(dag, components, max_states=100_000)

    assert compressed.makespan == generic.makespan
    assert compressed.explored_states < generic.explored_states / 10
