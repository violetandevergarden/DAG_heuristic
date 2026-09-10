"""Real-derived exact slices from AICB-exported benchmarks.

A slice keeps a documented window of the original DAG (micro-batch range and
layer range) together with every dependency that stays inside the window.
Boundary dependencies that leave the window are cut and recorded, so the slice
is a projection, never a claim of strict equivalence with the full graph.
"""

from __future__ import annotations

from dataclasses import replace

from benchmark import Benchmark, validate_benchmark


def microbatch_layer_slice(
    benchmark: Benchmark,
    *,
    max_microbatch: int = 0,
    max_layer: int | None = None,
    suffix: str = "slice",
) -> Benchmark:
    """Keep tasks in [0..max_microbatch] x [..max_layer] plus in-slice deps."""
    kept: set[str] = set()
    for task in benchmark.tasks:
        metadata = task.metadata
        microbatch = metadata.get("microbatch_id", -1)
        layer = metadata.get("layer_id", -1)
        if isinstance(microbatch, int) and 0 <= microbatch <= max_microbatch:
            if max_layer is None or (isinstance(layer, int) and 0 <= layer <= max_layer):
                kept.add(task.task_id)
    if not kept:
        raise ValueError("slice predicate keeps no tasks")

    # Dependency closure inside the window: a kept task may only depend on
    # tasks that are also kept.  Boundary deps are cut and counted.
    cut_edges: list[tuple[str, str]] = []
    tasks = []
    for task in benchmark.tasks:
        if task.task_id not in kept:
            continue
        dependencies = tuple(
            parent for parent in task.dependencies
            if parent in kept
        )
        for parent in task.dependencies:
            if parent not in kept:
                cut_edges.append((parent, task.task_id))
        tasks.append(replace(task, dependencies=dependencies))

    used_resources = {
        resource_id
        for task in tasks
        for resource_id in task.resources
    }
    resources = tuple(
        resource for resource in benchmark.resources
        if resource.resource_id in used_resources
    )
    sliced = replace(
        benchmark,
        benchmark_id=f"{benchmark.benchmark_id}_{suffix}",
        tasks=tuple(tasks),
        resources=resources,
        metadata={
            **benchmark.metadata,
            "slice_relation": {
                "max_microbatch": max_microbatch,
                "max_layer": max_layer,
                "kept_task_count": len(tasks),
                "original_task_count": len(benchmark.tasks),
                "cut_boundary_edges": len(cut_edges),
                "cut_edge_examples": cut_edges[:20],
            },
            "projection_relation": (
                f"{benchmark.metadata.get('projection_relation')}+real_derived_slice"
            ),
            "transform_log": [
                *(benchmark.metadata.get("transform_log") or []),
                (
                    f"real-derived slice: tasks with microbatch_id <= {max_microbatch} "
                    f"{'and layer_id <= ' + str(max_layer) if max_layer is not None else ''}; "
                    f"{len(cut_edges)} boundary edges cut and recorded"
                ),
            ],
        },
    )
    validate_benchmark(sliced)
    return sliced
