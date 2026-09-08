"""Active-reservation-aware conflict graph construction."""

from __future__ import annotations

from collections import defaultdict, deque

from muti_channel.nonpreemptive.solver import NonPreeMultiModel, ResourceState

from .contracts import ConflictGraphSnapshot, DecisionBudget


def build_conflict_graph(model: NonPreeMultiModel, state: ResourceState,
                         budget: DecisionBudget | None = None) -> ConflictGraphSnapshot:
    occupied = model.occupied_resources(state)
    ready = model.ready_flows(state)
    vertices = model.startable_flows(state)
    vertex_set = set(vertices)
    blocked = tuple(task_id for task_id in ready if task_id not in vertex_set)
    by_resource: dict[object, list[str]] = defaultdict(list)
    footprints = []
    for task_id in vertices:
        resources = model.resources[model.index[task_id]]
        footprints.append((task_id, resources))
        for resource in resources:
            by_resource[resource].append(task_id)
    edges: set[tuple[str, str]] = set()
    truncated = False
    for task_ids in by_resource.values():
        ordered = sorted(task_ids)
        for left in range(len(ordered)):
            for right in range(left + 1, len(ordered)):
                if budget is not None and not budget.reserve("pack_operations"):
                    truncated = True
                    break
                edges.add((ordered[left], ordered[right]))
            if truncated:
                break
        if truncated:
            break
    degree = defaultdict(int)
    adjacency: dict[str, set[str]] = {item: set() for item in vertices}
    for left, right in edges:
        degree[left] += 1; degree[right] += 1
        adjacency[left].add(right); adjacency[right].add(left)
    components = 0
    unseen = set(vertices)
    while unseen:
        components += 1
        queue = deque([unseen.pop()])
        while queue:
            for other in adjacency[queue.popleft()] & unseen:
                unseen.remove(other); queue.append(other)
    possible = len(vertices) * (len(vertices) - 1) // 2
    return ConflictGraphSnapshot(
        tuple(vertices), tuple(sorted(edges)), tuple(footprints),
        model.active_flows(state), occupied, blocked,
        len(edges) / possible if possible else 0.0,
        max(degree.values(), default=0), components, truncated,
    )
