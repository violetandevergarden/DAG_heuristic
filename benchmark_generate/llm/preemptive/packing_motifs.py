"""Controlled fixed-resource motifs for Stage 4f."""

from __future__ import annotations

from dataclasses import dataclass

from core.dag import DAG, Task


@dataclass(frozen=True)
class PackingMotif:
    name: str
    family: str
    dag: DAG
    resources: dict[str, frozenset[str]]
    target: str


def packing_motifs() -> tuple[PackingMotif, ...]:
    def independent(name, footprints, tails, target):
        tasks = []
        resources = {}
        for index, (footprint, (duration, tail)) in enumerate(zip(footprints, tails, strict=True)):
            flow = f"x{index}"
            tasks.extend((Task(flow, "comm", duration), Task(f"c{index}", "compute", tail, (flow,))))
            resources[flow] = frozenset(footprint)
        return PackingMotif(name, name.split("_")[0], DAG(name, tuple(tasks), context=(('category', 'adversarial'),)), resources, target)

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
        "shared_downstream_overlap", "shared", DAG('shared_downstream_overlap', (Task('wide', 'comm', 2), Task('left', 'comm', 3), Task('right', 'comm', 3), Task('join', 'compute', 8, ('left', 'right')), Task('wide_tail', 'compute', 7, ('wide',))), context=(('category', 'adversarial'),)), {"wide": frozenset({"a", "b"}), "left": frozenset({"a"}), "right": frozenset({"b"})},
        "shared_downstream_no_double_count",
    )
    hotspot_mislead = PackingMotif(
        "hotspot_not_critical", "hotspot", DAG('hotspot_not_critical', (Task('hot', 'comm', 2), Task('critical', 'comm', 4), Task('side', 'comm', 4), Task('hot_tail', 'compute', 1, ('hot',)), Task('critical_tail', 'compute', 9, ('critical',)), Task('side_tail', 'compute', 1, ('side',))), context=(('category', 'adversarial'),)), {"hot": frozenset({"a", "b"}), "critical": frozenset({"a"}), "side": frozenset({"b"})},
        "hotspot_not_final_critical_path",
    )
    preemption = PackingMotif(
        "preemption_without_gain", "preemption", DAG('preemption_without_gain', (Task('release', 'compute', 1), Task('wide', 'comm', 4), Task('urgent', 'comm', 1, ('release',)), Task('tail', 'compute', 3, ('wide',))), context=(('category', 'adversarial'),)), {"wide": frozenset({"a", "b"}), "urgent": frozenset({"a"})},
        "extra_preemption_no_makespan_gain",
    )
    return (*base, paired_graph_changed_future, shared_downstream, hotspot_mislead, preemption)
