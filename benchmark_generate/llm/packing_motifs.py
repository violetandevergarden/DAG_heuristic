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

    return (
        independent("clique_tail", (("r",),) * 3, ((2, 8), (3, 4), (1, 1)), "score_order"),
        independent("empty_parallel", (("a",), ("b",), ("c",)), ((3, 4), (2, 2), (1, 1)), "unique_maximal_set"),
        independent("star_wide_vs_pair", (("a", "b"), ("a",), ("b",)), ((2, 7), (3, 5), (3, 5)), "packing_choice"),
        independent("path_future_value", (("a",), ("a", "b"), ("b", "c"), ("c",)), ((2, 9), (5, 7), (5, 0), (5, 3)), "same_graph_future_value"),
        independent("exchange_repairs_lt", (("a", "b"), ("a", "c"), ("b",), ("c",)), ((2, 9), (5, 7), (5, 0), (5, 3)), "greedy_failure_repaired"),
        independent("hyperedge_hotspot", (("a", "b", "c"), ("a",), ("b",), ("c",)), ((2, 6), (2, 4), (2, 4), (2, 4)), "hyperedge_projection"),
    )
