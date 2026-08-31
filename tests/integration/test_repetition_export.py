"""Optional SimAI-backed repetition and Zero Bubble integration checks."""

from benchmark_generate.simai.preemptive_export import (
    build_synthetic_input,
    build_workload,
    to_preemptive_benchmark,
)
from experiments.simai.repetition import scan_repetition
from experiments.simai.repetition_study import _raw_b_to_w_edges


def test_scanner_separates_repetition_from_exchangeability() -> None:
    header, items = build_synthetic_input(pp=2, ga=4, layers=2)
    benchmark = to_preemptive_benchmark(
        build_workload("1f1b", header, items), "repeat_scan",
        category="random",
    )
    report = scan_repetition(benchmark)

    assert report.detected_period == 1
    assert report.structural_repetition > 0.5
    assert report.conservative_exchangeable_task_fraction == 0.0
    assert report.cross_microbatch_conflict_fraction > 0.5


def test_zero_bubble_separates_data_fork_from_compute_order() -> None:
    header, items = build_synthetic_input(pp=2, tp=2, dp=2, ga=4, layers=2)
    built = build_workload("zero_bubble", header, items)
    benchmark = to_preemptive_benchmark(
        built, "zero_bubble_semantics",
        category="random",
    )

    assert _raw_b_to_w_edges(built) == 0
    assert scan_repetition(benchmark).direct_b_to_w_edges > 0

