"""Causal-closure slices from real non-preemptive decision states."""

from __future__ import annotations

import json
from dataclasses import replace

from benchmark import Benchmark, validate_benchmark
from benchmark_generate.io import canonical_object_sha256


def _benchmark_hash(benchmark: Benchmark) -> str:
    from benchmark import benchmark_to_dict

    payload = json.loads(json.dumps(
        benchmark_to_dict(benchmark),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ))
    return canonical_object_sha256(payload)


def causal_closure_slice(
    benchmark: Benchmark,
    *,
    anchors: tuple[str, ...],
    max_tasks: int = 300,
    successor_depth: int = 2,
    suffix: str = "causal_slice",
) -> Benchmark:
    """Keep anchors, bounded successors, and every transitive predecessor.

    No boundary dependency is cut: if predecessor closure exceeds ``max_tasks``
    the candidate is rejected instead of modifying the real graph.
    """

    tasks = benchmark.task_map()
    if not anchors:
        raise ValueError("at least one real decision anchor is required")
    unknown = set(anchors) - set(tasks)
    if unknown:
        raise ValueError(f"unknown slice anchors: {sorted(unknown)}")
    children: dict[str, list[str]] = {task_id: [] for task_id in tasks}
    for task in benchmark.tasks:
        for parent in task.dependencies:
            children[parent].append(task.task_id)
    kept = set(anchors)
    frontier = set(anchors)
    boundary_successors: set[str] = set()
    for _depth in range(successor_depth):
        following = {child for item in frontier for child in children[item]}
        kept.update(following)
        frontier = following
    boundary_successors.update(
        child for item in frontier for child in children[item] if child not in kept
    )
    stack = list(kept)
    while stack:
        task_id = stack.pop()
        for parent in tasks[task_id].dependencies:
            if parent not in kept:
                kept.add(parent)
                stack.append(parent)
        if len(kept) > max_tasks:
            raise ValueError(f"causal predecessor closure exceeds max_tasks={max_tasks}")

    selected = tuple(task for task in benchmark.tasks if task.task_id in kept)
    used_resources = {resource for task in selected for resource in task.resources}
    result = replace(
        benchmark,
        benchmark_id=f"{benchmark.benchmark_id}_{suffix}",
        tasks=selected,
        resources=tuple(
            resource for resource in benchmark.resources if resource.resource_id in used_resources
        ),
        metadata={
            **benchmark.metadata,
            "stage4_layer": "real_derived",
            "slice_relation": {
                "source_benchmark_hash": _benchmark_hash(benchmark),
                "anchor_decision_tasks": list(anchors),
                "selection_rule": "bounded_successors_plus_full_predecessor_closure-v1",
                "successor_depth": successor_depth,
                "kept_task_count": len(selected),
                "removed_task_count": len(benchmark.tasks) - len(selected),
                "boundary_successors": sorted(boundary_successors),
                "dependencies_cut": 0,
                "duration_or_resource_changes": 0,
                "slice_scope": "local_self_contained_problem_only",
            },
        },
    )
    validate_benchmark(result)
    return result
