"""Read-only residual barrier features for LLM-structured scheduling.

The module deliberately contains no clock advancement, action validation, or
schedule selection.  It accepts either the public single-channel or fixed
multi-resource model/state pair and derives structural quantities from the
current residual state.  Exact quantities and estimates are kept explicit in
the returned snapshots so callers cannot silently treat a heuristic signal as
an oracle value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.dag import BenchTask, topological_order


@dataclass(frozen=True)
class BarrierFeatureSnapshot:
    """Per-communication residual feature snapshot.

    ``estimated_arrival_spread`` and ``paused_tail_penalty`` are estimates;
    all other values are structural/residual quantities computed from the
    supplied state.  ``residual_tail`` includes the candidate's remaining
    work, while ``exclusive_tail`` removes that own work.
    """

    task_id: str
    remaining_work: int
    residual_tail: int
    immediate_compute_release: int
    reachable_compute_release: int
    last_missing_join_count: int
    local_last_missing_count: int
    global_last_missing_count: int
    downstream_join_tail: int
    estimated_arrival_spread: int
    resource_count: int
    hotspot_conflict_degree: int
    compatible_completion_gain: int
    paused_tail_penalty: int
    exclusive_tail: int
    label_hint: str = ""
    quantity_modes: tuple[tuple[str, str], ...] = (
        ("remaining_work", "residual_exact"),
        ("residual_tail", "structural_exact"),
        ("immediate_compute_release", "residual_exact"),
        ("reachable_compute_release", "structural_exact"),
        ("last_missing_join_count", "structural_exact"),
        ("local_last_missing_count", "structural_exact"),
        ("global_last_missing_count", "structural_exact"),
        ("downstream_join_tail", "structural_exact"),
        ("estimated_arrival_spread", "heuristic_estimate"),
        ("resource_count", "residual_exact"),
        ("hotspot_conflict_degree", "residual_exact"),
        ("compatible_completion_gain", "structural_exact"),
        ("paused_tail_penalty", "heuristic_estimate"),
        ("exclusive_tail", "structural_exact"),
    )


@dataclass(frozen=True)
class BarrierActionFeatures:
    """Whole-action features for a legal single or maximal multi-resource action."""

    communication_ids: tuple[str, ...]
    union_released_compute: int
    union_downstream_tail: int
    completed_join_count: int
    barrier_spread_reduction: int
    occupied_resource_count: int
    excluded_candidate_count: int
    packing_complementarity: int
    shared_downstream_count: int
    quantity_modes: tuple[tuple[str, str], ...] = (
        ("union_released_compute", "structural_exact"),
        ("union_downstream_tail", "structural_exact"),
        ("completed_join_count", "structural_exact"),
        ("barrier_spread_reduction", "heuristic_estimate"),
        ("occupied_resource_count", "residual_exact"),
        ("excluded_candidate_count", "residual_exact"),
        ("packing_complementarity", "structural_exact"),
        ("shared_downstream_count", "structural_exact"),
    )


@dataclass(frozen=True)
class BarrierAnalysisContext:
    """Shared immutable analysis data for one stable decision state."""

    model: Any
    state: Any
    tasks: dict[str, BenchTask]
    order: tuple[str, ...]
    children: dict[str, tuple[str, ...]]
    completed: frozenset[str]
    tails: dict[str, int]
    eligible: tuple[str, ...]
    active: frozenset[str]
    resources: dict[str, frozenset[str]]


def build_context(
    model: Any, state: Any, *, roots: tuple[str, ...] | None = None
) -> BarrierAnalysisContext:
    """Build a context once and reuse it for all candidates in a state."""

    order = tuple(model.task_ids)
    tasks = model.task_map
    children = model.children
    completed = frozenset(
        task_id
        for task_id in order
        if _runtime(model, state, task_id).status == "completed"
    )
    if roots is None:
        tail_order = order
    else:
        reachable = set(roots)
        pending = list(roots)
        while pending:
            current = pending.pop()
            for child in children[current]:
                if child not in reachable:
                    reachable.add(child)
                    pending.append(child)
        tail_order = tuple(sorted(reachable, key=model.index.__getitem__))
    tails: dict[str, int] = {}
    for task_id in reversed(tail_order):
        tails[task_id] = _own_remaining(model, state, task_id, tasks[task_id]) + max(
            (tails[child] for child in children[task_id]), default=0
        )
    eligible = tuple(
        model.eligible_communications(state)
        if hasattr(model, "eligible_communications")
        else model.eligible(state)
    )
    if hasattr(model, "active_computes"):
        active_raw = model.active_computes(state)
        active = frozenset(
            item if isinstance(item, str) else model.tasks[item].task_id
            for item in active_raw
        )
    else:
        active = frozenset()
    if hasattr(model, "eligible_communications"):
        resources = {task_id: frozenset({"channel:0"}) for task_id in eligible}
    else:
        resources = {
            task_id: frozenset(getattr(model, "resources", {}).get(task_id, ()))
            for task_id in eligible
        }
    return BarrierAnalysisContext(
        model,
        state,
        tasks,
        order,
        children,
        completed,
        tails,
        eligible,
        active,
        resources,
    )


def feature_snapshot(
    context: BarrierAnalysisContext, task_id: str
) -> BarrierFeatureSnapshot:
    """Return a deterministic, read-only feature snapshot for one candidate."""

    if task_id not in context.eligible:
        raise ValueError(f"candidate {task_id!r} is not eligible")
    task = context.tasks[task_id]
    remaining = _own_remaining(context.model, context.state, task_id, task)
    joins = _last_missing_joins(context, task_id)
    local = 0
    global_count = 0
    downstream_join_tail = 0
    for join_id in joins:
        downstream_join_tail = max(downstream_join_tail, context.tails[join_id])
        sinks = _reachable_sinks(context, join_id)
        all_sinks = _residual_sinks(context)
        if all_sinks and all_sinks <= sinks:
            global_count += 1
        else:
            local += 1
    immediate_compute = _immediate_compute_release(context, task_id)
    reachable_compute = sum(
        _own_remaining(context.model, context.state, item, context.tasks[item])
        for item in _descendants(context, (task_id,))
        if context.tasks[item].kind == "compute" and item not in context.completed
    )
    candidate_resources = context.resources.get(task_id, frozenset())
    hotspot = sum(
        bool(candidate_resources & context.resources.get(other, frozenset()))
        for other in context.eligible
        if other != task_id
    )
    arrival_spread = _arrival_spread(context, joins)
    paused_penalty = max(
        (
            context.tails[item] - _own_remaining(
                context.model, context.state, item, context.tasks[item]
            )
            for item in context.active
            if item != task_id
        ),
        default=0,
    )
    return BarrierFeatureSnapshot(
        task_id=task_id,
        remaining_work=remaining,
        residual_tail=context.tails[task_id],
        immediate_compute_release=immediate_compute,
        reachable_compute_release=reachable_compute,
        last_missing_join_count=len(joins),
        local_last_missing_count=local,
        global_last_missing_count=global_count,
        downstream_join_tail=downstream_join_tail,
        estimated_arrival_spread=arrival_spread,
        resource_count=len(candidate_resources),
        hotspot_conflict_degree=hotspot,
        compatible_completion_gain=immediate_compute + reachable_compute,
        paused_tail_penalty=paused_penalty,
        exclusive_tail=max(0, context.tails[task_id] - remaining),
        label_hint=task.label_map().get("collective_type", task.role),
    )


def priority_key(
    context: BarrierAnalysisContext, task_id: str, mode: str = "tail_barrier"
) -> tuple[object, ...]:
    """Compute only fields used by an online priority comparison.

    ``feature_snapshot`` intentionally remains comprehensive for audits.  A
    scheduler must not pay for descendant unions, global-sink classification,
    resource diagnostics and label extraction when its key does not use them.
    """

    if task_id not in context.eligible:
        raise ValueError(f"candidate {task_id!r} is not eligible")
    task = context.tasks[task_id]
    remaining = _own_remaining(context.model, context.state, task_id, task)
    joins = _last_missing_joins(context, task_id)
    downstream_join_tail = max(
        (context.tails[join_id] for join_id in joins), default=0
    )
    immediate_compute = (
        _immediate_compute_release(context, task_id)
        if mode in {"unlock_only", "tail_unlock", "tail_barrier", "barrier_aware", "tail_unlock_barrier"}
        else 0
    )
    exclusive_tail = max(0, context.tails[task_id] - remaining)
    if mode == "barrier_only":
        return (-len(joins), -downstream_join_tail, task_id)
    if mode == "unlock_only":
        return (-immediate_compute, task_id)
    if mode == "tail":
        return (-exclusive_tail, task_id)
    if mode == "tail_unlock":
        return (-exclusive_tail, -immediate_compute, task_id)
    if mode in {"tail_barrier", "barrier_aware"}:
        return (
            -exclusive_tail,
            -len(joins),
            -downstream_join_tail,
            -immediate_compute,
            task_id,
        )
    if mode == "tail_unlock_barrier":
        return (
            -exclusive_tail,
            -immediate_compute,
            -len(joins),
            -downstream_join_tail,
            task_id,
        )
    raise ValueError(f"unknown barrier score mode: {mode}")


def has_barrier_signal(context: BarrierAnalysisContext, task_id: str) -> bool:
    """Return whether a candidate closes a join or releases compute now."""

    return bool(_last_missing_joins(context, task_id)) or bool(
        _immediate_compute_release(context, task_id)
    )


def action_features(
    context: BarrierAnalysisContext, communication_ids: tuple[str, ...]
) -> BarrierActionFeatures:
    """Compute shared-downstream de-duplicated features for an action."""

    selected = tuple(sorted(set(communication_ids)))
    if not selected or not set(selected) <= set(context.eligible):
        raise ValueError("action must contain eligible communications")
    descendants = _descendants(context, selected)
    compute_union = sum(
        _own_remaining(context.model, context.state, item, context.tasks[item])
        for item in descendants
        if context.tasks[item].kind == "compute" and item not in context.completed
    )
    joins = {
        join_id
        for task_id in selected
        for join_id in _last_missing_joins(context, task_id)
    }
    completed_join_count = len(joins)
    tails = [context.tails[item] for item in descendants if item not in context.completed]
    occupied = set().union(*(context.resources.get(item, frozenset()) for item in selected))
    excluded = set(context.eligible) - set(selected)
    complementarity = sum(
        1
        for item in excluded
        if not (context.resources.get(item, frozenset()) & occupied)
    )
    join_ids = tuple(sorted(joins))
    before_spread = _arrival_spread(context, join_ids)
    after_spread = _arrival_spread(context, join_ids, selected)
    return BarrierActionFeatures(
        communication_ids=selected,
        union_released_compute=compute_union,
        union_downstream_tail=max(tails, default=0),
        completed_join_count=completed_join_count,
        barrier_spread_reduction=max(0, before_spread - after_spread),
        occupied_resource_count=len(occupied),
        excluded_candidate_count=len(excluded),
        packing_complementarity=complementarity,
        shared_downstream_count=max(0, sum(len(_descendants(context, (item,))) for item in selected) - len(descendants)),
    )


def score_snapshot(
    snapshot: BarrierFeatureSnapshot, mode: str = "tail_barrier"
) -> tuple[object, ...]:
    """Stable dictionary-free score for ablations and policy experiments."""

    if mode == "barrier_only":
        return (-snapshot.last_missing_join_count, -snapshot.downstream_join_tail, snapshot.task_id)
    if mode == "unlock_only":
        return (-snapshot.immediate_compute_release, snapshot.task_id)
    if mode == "tail":
        return (-snapshot.exclusive_tail, snapshot.task_id)
    if mode == "tail_unlock":
        return (-snapshot.exclusive_tail, -snapshot.immediate_compute_release, snapshot.task_id)
    if mode in {"tail_barrier", "barrier_aware"}:
        return (
            -snapshot.exclusive_tail,
            -snapshot.last_missing_join_count,
            -snapshot.downstream_join_tail,
            -snapshot.immediate_compute_release,
            snapshot.task_id,
        )
    if mode == "tail_unlock_barrier":
        return (
            -snapshot.exclusive_tail,
            -snapshot.immediate_compute_release,
            -snapshot.last_missing_join_count,
            -snapshot.downstream_join_tail,
            snapshot.task_id,
        )
    raise ValueError(f"unknown barrier score mode: {mode}")


def _runtime(model: Any, state: Any, task_id: str) -> Any:
    if hasattr(model, "task_runtime"):
        return model.task_runtime(state, task_id)
    return state.tasks[model.index[task_id]]


def _own_remaining(model: Any, state: Any, task_id: str, task: BenchTask) -> int:
    runtime = _runtime(model, state, task_id)
    if runtime.status == "completed":
        return 0
    return runtime.remaining or task.duration


def _descendants(context: BarrierAnalysisContext, roots: tuple[str, ...]) -> frozenset[str]:
    seen = set(roots)
    stack = list(roots)
    while stack:
        current = stack.pop()
        for child in context.children[current]:
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return frozenset(seen)


def _last_missing_joins(context: BarrierAnalysisContext, task_id: str) -> tuple[str, ...]:
    result = []
    for child in context.children[task_id]:
        deps = context.tasks[child].deps
        if len(deps) > 1 and all(
            dependency == task_id or dependency in context.completed for dependency in deps
        ):
            result.append(child)
    return tuple(sorted(result))


def _immediate_compute_release(context: BarrierAnalysisContext, task_id: str) -> int:
    completed = set(context.completed)
    completed.add(task_id)
    changed = True
    while changed:
        changed = False
        for item in context.order:
            task = context.tasks[item]
            if item in completed or task.kind != "compute":
                continue
            runtime = _runtime(context.model, context.state, item)
            if runtime.status == "pending" and task.duration == 0 and set(task.deps) <= completed:
                completed.add(item)
                changed = True
    already_ready = set(context.eligible) | set(context.active)
    return sum(
        task.duration
        for item, task in context.tasks.items()
        if item not in completed
        and item not in already_ready
        and task.kind == "compute"
        and _runtime(context.model, context.state, item).status == "pending"
        and set(task.deps) <= completed
    )


def _reachable_sinks(context: BarrierAnalysisContext, root: str) -> frozenset[str]:
    reachable = _descendants(context, (root,))
    return frozenset(
        item for item in reachable if not context.children[item]
    )


def _residual_sinks(context: BarrierAnalysisContext) -> frozenset[str]:
    return frozenset(
        item
        for item in context.order
        if not context.children[item] and item not in context.completed
    )


def _arrival_spread(
    context: BarrierAnalysisContext,
    joins: tuple[str, ...],
    extra_completed: tuple[str, ...] = (),
) -> int:
    completed = context.completed | frozenset(extra_completed)
    estimates = []
    for join_id in joins:
        estimates.extend(
            0
            if dependency in completed
            else context.tails[dependency]
            for dependency in context.tasks[join_id].deps
        )
    return max(estimates, default=0) - min(estimates, default=0)
