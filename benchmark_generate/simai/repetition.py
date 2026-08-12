"""Language-neutral repetition metrics for exported SimAI DAG benchmarks.

This module deliberately scans the standalone :class:`benchmark.Benchmark`
representation.  SimAI is needed to create a snapshot, but not to inspect a
snapshot or consume the resulting JSON report.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from itertools import combinations
from typing import Any, Hashable

from benchmark import Benchmark, Task


@dataclass(frozen=True)
class RepetitionReport:
    benchmark_id: str
    pipeline_mode: str
    task_count: int
    communication_count: int
    microbatch_count: int
    structural_repetition: float
    resource_repetition: float
    timing_repetition: float
    detected_period: int | None
    periodic_microbatch_fraction: float
    cross_microbatch_dependency_fraction: float
    cross_microbatch_conflict_fraction: float
    communication_conflict_density: float
    join_task_fraction: float
    conservative_exchangeable_task_fraction: float
    direct_b_to_w_edges: int
    role_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def scan_repetition(benchmark: Benchmark) -> RepetitionReport:
    """Measure three levels of repetition and cross-unit coupling.

    ``structural_repetition`` ignores concrete routes and durations;
    ``resource_repetition`` additionally requires the same fixed resource set;
    ``timing_repetition`` additionally requires equal integer durations.
    A task is counted as repeated only if its normalized local DAG signature
    occurs in at least two distinct micro-batches, so TP ranks within one
    micro-batch cannot inflate the result.
    """

    tasks = benchmark.task_map()
    children: dict[str, list[str]] = {task_id: [] for task_id in tasks}
    for task in benchmark.tasks:
        for parent in task.dependencies:
            children[parent].append(task.task_id)
    microbatches = sorted({mb for task in benchmark.tasks if (mb := _mb(task)) >= 0})
    eligible = [task for task in benchmark.tasks if _mb(task) >= 0]

    signatures: dict[str, dict[str, Hashable]] = {
        level: {
            task.task_id: _local_signature(
                task, tasks, children,
                include_resources=level in {"resource", "timing"},
                include_timing=level == "timing",
            )
            for task in eligible
        }
        for level in ("structural", "resource", "timing")
    }

    repetition = {
        level: _repeated_fraction(eligible, values)
        for level, values in signatures.items()
    }
    motif_labels = {
        task.task_id: _node_label(task, include_resources=False, include_timing=False)
        for task in eligible
    }
    period, periodic_fraction = _detect_period(eligible, motif_labels)
    dependency_fraction = _cross_dependency_fraction(benchmark)
    conflict_fraction, conflict_density = _conflict_metrics(benchmark)
    joins = sum(len(task.dependencies) >= 2 for task in benchmark.tasks)
    exchangeable = _conservative_exchangeable_fraction(benchmark, children)
    b_to_w = sum(
        _role(task) == "W"
        and any(_is_same_pair_b_parent(task, tasks[parent]) for parent in task.dependencies)
        for task in benchmark.tasks
    )
    role_counts = Counter(_role(task) for task in benchmark.tasks)
    communications = sum(task.kind == "communication" for task in benchmark.tasks)
    return RepetitionReport(
        benchmark_id=benchmark.benchmark_id,
        pipeline_mode=str(benchmark.metadata.get("pipeline_mode", "unknown")),
        task_count=len(benchmark.tasks),
        communication_count=communications,
        microbatch_count=len(microbatches),
        structural_repetition=repetition["structural"],
        resource_repetition=repetition["resource"],
        timing_repetition=repetition["timing"],
        detected_period=period,
        periodic_microbatch_fraction=periodic_fraction,
        cross_microbatch_dependency_fraction=dependency_fraction,
        cross_microbatch_conflict_fraction=conflict_fraction,
        communication_conflict_density=conflict_density,
        join_task_fraction=joins / len(benchmark.tasks) if benchmark.tasks else 0.0,
        conservative_exchangeable_task_fraction=exchangeable,
        direct_b_to_w_edges=b_to_w,
        role_counts=dict(sorted(role_counts.items())),
    )


def _mb(task: Task) -> int:
    return int(task.metadata.get("microbatch_id", task.metadata.get("iteration", -1)))


def _role(task: Task) -> str:
    if task.kind == "communication":
        comm_type = str(task.metadata.get("comm_type", ""))
        if comm_type == "pp_send":
            return "PP_ACT" if str(task.metadata.get("phase", "")) == "forward" else "PP_GRAD"
        if comm_type:
            return comm_type.split("_", 1)[0].upper()
    raw = str(task.metadata.get("task_role", task.metadata.get("role", "OTHER")))
    aliases = {
        "compute_forward": "F",
        "compute_backward_input": "B",
        "compute_backward_weight": "W",
        "pp_activation": "PP_ACT",
        "pp_gradient": "PP_GRAD",
    }
    return aliases.get(raw, raw.upper())


def _is_same_pair_b_parent(weight: Task, parent: Task) -> bool:
    """Return whether ``parent`` is the B result paired with this W task."""
    if _role(parent) != "B":
        return False
    weight_b = weight.metadata.get("b_task_id")
    parent_b = parent.metadata.get("b_task_id")
    if weight_b is not None and parent_b is not None:
        return int(weight_b) == int(parent_b)
    # Generic non-sidecar fallback: identify the same logical layer instance.
    fields = ("iteration", "layer_id", "item_id", "physical_stage_id")
    return all(weight.metadata.get(field) == parent.metadata.get(field) for field in fields)


def _node_label(
    task: Task,
    *,
    include_resources: bool,
    include_timing: bool,
) -> tuple[Hashable, ...]:
    metadata = task.metadata
    values: list[Hashable] = [
        task.kind,
        _role(task),
        str(metadata.get("phase", "")),
        int(metadata.get("physical_stage_id", -1)),
        int(metadata.get("model_chunk_id", metadata.get("chunk_id", -1)) or -1),
        int(metadata.get("layer_id", -1)),
        int(metadata.get("module_replica_id", -1)),
        str(metadata.get("direction", "")),
        str(metadata.get("comm_type", "")),
    ]
    if include_resources:
        values.append(tuple(sorted(task.resources)))
    if include_timing:
        values.append(task.duration)
    return tuple(values)


def _local_signature(
    task: Task,
    tasks: dict[str, Task],
    children: dict[str, list[str]],
    *,
    include_resources: bool,
    include_timing: bool,
) -> tuple[Hashable, ...]:
    own_mb = _mb(task)

    def endpoint(other: Task) -> tuple[Hashable, ...]:
        other_mb = _mb(other)
        delta = f"d{other_mb - own_mb:+d}" if own_mb >= 0 and other_mb >= 0 else "boundary"
        return (
            delta,
            _node_label(
                other,
                include_resources=include_resources,
                include_timing=include_timing,
            ),
        )

    parents = tuple(sorted(endpoint(tasks[item]) for item in task.dependencies))
    successors = tuple(sorted(endpoint(tasks[item]) for item in children[task.task_id]))
    return (
        _node_label(task, include_resources=include_resources, include_timing=include_timing),
        parents,
        successors,
    )


def _repeated_fraction(tasks: list[Task], signatures: dict[str, Hashable]) -> float:
    if not tasks:
        return 0.0
    occurrences: dict[Hashable, set[int]] = defaultdict(set)
    for task in tasks:
        occurrences[signatures[task.task_id]].add(_mb(task))
    repeated = sum(
        len(occurrences[signatures[task.task_id]]) >= 2
        for task in tasks
    )
    return repeated / len(tasks)


def _detect_period(
    tasks: list[Task], signatures: dict[str, Hashable]
) -> tuple[int | None, float]:
    profiles: dict[int, Counter[Hashable]] = defaultdict(Counter)
    for task in tasks:
        profiles[_mb(task)][signatures[task.task_id]] += 1
    indices = sorted(profiles)
    if len(indices) < 2:
        return None, 0.0
    best_period: int | None = None
    best_fraction = 0.0
    for period in range(1, len(indices)):
        comparisons = [
            profiles[left] == profiles[right]
            for left, right in zip(indices, indices[period:])
        ]
        fraction = sum(comparisons) / len(comparisons)
        if fraction > best_fraction or (
            fraction == best_fraction and best_period is not None and period < best_period
        ):
            best_period, best_fraction = period, fraction
        if fraction == 1.0:
            return period, fraction
    return best_period, best_fraction


def _cross_dependency_fraction(benchmark: Benchmark) -> float:
    tasks = benchmark.task_map()
    total = 0
    cross = 0
    for task in benchmark.tasks:
        task_mb = _mb(task)
        for parent_id in task.dependencies:
            parent_mb = _mb(tasks[parent_id])
            if task_mb < 0 or parent_mb < 0:
                continue
            total += 1
            cross += task_mb != parent_mb
    return cross / total if total else 0.0


def _conflict_metrics(benchmark: Benchmark) -> tuple[float, float]:
    communications = [task for task in benchmark.tasks if task.kind == "communication"]
    if len(communications) < 2:
        return 0.0, 0.0
    all_pairs = len(communications) * (len(communications) - 1) // 2
    # Single-channel snapshots admit an exact O(n) count.
    resource_sets = {task.resources for task in communications}
    if len(resource_sets) == 1:
        total = all_pairs
        by_mb = Counter(_mb(task) for task in communications)
        within = sum(count * (count - 1) // 2 for count in by_mb.values())
        return ((total - within) / total if total else 0.0), 1.0
    total = 0
    cross = 0
    for left, right in combinations(communications, 2):
        if not set(left.resources).intersection(right.resources):
            continue
        total += 1
        cross += _mb(left) != _mb(right)
    return (
        cross / total if total else 0.0,
        total / all_pairs if all_pairs else 0.0,
    )


def _conservative_exchangeable_fraction(
    benchmark: Benchmark, children: dict[str, list[str]]
) -> float:
    """Count only literal graph twins; this never assumes mere isomorphism."""

    groups: Counter[tuple[Hashable, ...]] = Counter()
    for task in benchmark.tasks:
        key = (
            task.kind,
            task.duration,
            tuple(sorted(task.dependencies)),
            tuple(sorted(children[task.task_id])),
            tuple(sorted(task.resources)),
        )
        groups[key] += 1
    repeated = sum(count for count in groups.values() if count >= 2)
    return repeated / len(benchmark.tasks) if benchmark.tasks else 0.0
