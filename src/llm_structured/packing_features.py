"""Cheap residual conflict/resource features for LLM-structured packing."""

from __future__ import annotations

from dataclasses import dataclass

from muti_channel.preemptive.packing import build_conflict_graph


@dataclass(frozen=True)
class PackingFeatures:
    eligible_count: int
    conflict_edges: int
    conflict_density: float
    maximum_conflict_degree: int
    resource_count: int
    maximum_footprint: int
    llm_role_diversity: int


def cheap_packing_features(model, state) -> PackingFeatures:
    graph = build_conflict_graph(model, state)
    roles = {
        model.task_map[item].label_map().get("task_role", "") or "OTHER"
        for item in graph.vertices
    }
    resources = {
        resource for item in graph.vertices for resource in model.resources[item]
    }
    return PackingFeatures(
        len(graph.vertices),
        len(graph.conflict_edges),
        graph.density,
        graph.maximum_degree,
        len(resources),
        max((len(model.resources[item]) for item in graph.vertices), default=0),
        len(roles),
    )
