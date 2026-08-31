"""Controlled fixed-resource motifs for Stage 4f."""

from __future__ import annotations

from dataclasses import dataclass

from core.dag import BenchmarkDAG, BenchTask


@dataclass(frozen=True)
class PackingMotif:
    name: str
    family: str
    dag: BenchmarkDAG
    resources: dict[str, frozenset[str]]
    target: str


def packing_motifs() -> tuple[PackingMotif, ...]:
    def independent(name, footprints, tails, target):
        tasks = []
        resources = {}
        for index, (footprint, (duration, tail)) in enumerate(zip(footprints, tails, strict=True)):
            flow = f"x{index}"
            tasks.extend((BenchTask(flow, "comm", duration), BenchTask(f"c{index}", "compute", tail, (flow,))))
            resources[flow] = frozenset(footprint)
        return PackingMotif(name, name.split("_")[0], BenchmarkDAG(name, "adversarial", tuple(tasks)), resources, target)

    base = (
        independent("clique_tail", (("r",),) * 3, ((2, 8), (3, 4), (1, 1)), "score_order"),
        independent("empty_parallel", (("a",), ("b",), ("c",)), ((3, 4), (2, 2), (1, 1)), "unique_maximal_set"),
        independent("star_wide_vs_pair", (("a", "b"), ("a",), ("b",)), ((2, 7), (3, 5), (3, 5)), "packing_choice"),
        independent("path_future_value", (("a",), ("a", "b"), ("b", "c"), ("c",)), ((2, 9), (5, 7), (5, 0), (5, 3)), "same_graph_future_value"),
        independent("exchange_repairs_lt", (("a", "b"), ("a", "c"), ("b",), ("c",)), ((2, 9), (5, 7), (5, 0), (5, 3)), "greedy_failure_repaired"),
        independent("hyperedge_hotspot", (("a", "b", "c"), ("a",), ("b",), ("c",)), ((2, 6), (2, 4), (2, 4), (2, 4)), "hyperedge_projection"),
    )
    # Each extension below isolates a review-required failure mode.  They are
    # controlled regression inputs, not evidence of its frequency in AICB DAGs.
    paired_graph_changed_future = independent(
        "path_future_value_reversed", (("a",), ("a", "b"), ("b", "c"), ("c",)),
        ((2, 1), (5, 2), (5, 11), (5, 8)), "same_graph_different_downstream",
    )
    shared_downstream = PackingMotif(
        "shared_downstream_overlap", "shared", BenchmarkDAG("shared_downstream_overlap", "adversarial", (
            BenchTask("wide", "comm", 2), BenchTask("left", "comm", 3), BenchTask("right", "comm", 3),
            BenchTask("join", "compute", 8, ("left", "right")),
            BenchTask("wide_tail", "compute", 7, ("wide",)),
        )), {"wide": frozenset({"a", "b"}), "left": frozenset({"a"}), "right": frozenset({"b"})},
        "shared_downstream_no_double_count",
    )
    hotspot_mislead = PackingMotif(
        "hotspot_not_critical", "hotspot", BenchmarkDAG("hotspot_not_critical", "adversarial", (
            BenchTask("hot", "comm", 2), BenchTask("critical", "comm", 4), BenchTask("side", "comm", 4),
            BenchTask("hot_tail", "compute", 1, ("hot",)),
            BenchTask("critical_tail", "compute", 9, ("critical",)),
            BenchTask("side_tail", "compute", 1, ("side",)),
        )), {"hot": frozenset({"a", "b"}), "critical": frozenset({"a"}), "side": frozenset({"b"})},
        "hotspot_not_final_critical_path",
    )
    preemption = PackingMotif(
        "preemption_without_gain", "preemption", BenchmarkDAG("preemption_without_gain", "adversarial", (
            BenchTask("release", "compute", 1), BenchTask("wide", "comm", 4),
            BenchTask("urgent", "comm", 1, ("release",)), BenchTask("tail", "compute", 3, ("wide",)),
        )), {"wide": frozenset({"a", "b"}), "urgent": frozenset({"a"})},
        "extra_preemption_no_makespan_gain",
    )
    return (*base, paired_graph_changed_future, shared_downstream, hotspot_mislead, preemption)
