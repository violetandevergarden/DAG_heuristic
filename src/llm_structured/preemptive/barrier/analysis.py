"""Read-only residual barrier features for structured scheduling.

The functions in this module never advance a clock or select an action. They
describe the current public simulator state only. A structural path quantity
is never labelled as a time or makespan benefit, and every arrival quantity is
explicitly a contention-free estimate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.dag import Task


@dataclass(frozen=True)
class BarrierFeatureSnapshot:
    """Features of one currently eligible communication.

    Only direct residual joins are represented: a join is counted when this
    candidate is its sole unfinished predecessor. Indirect barrier discovery
    is deliberately not inferred from task names or unbounded traversal.
    """

    task_id: str
    remaining_work: int
    residual_tail: int
    exclusive_tail: int
    newly_ready_compute_work: int
    newly_ready_compute_ids: tuple[str, ...]
    reachable_descendant_compute_work: int
    direct_last_missing_join_count: int
    direct_last_missing_join_ids: tuple[str, ...]
    downstream_join_tail: int
    estimated_latest_branch_arrival: int | None
    estimated_second_latest_branch_arrival: int | None
    estimated_candidate_branch_arrival: int | None
    estimated_barrier_slack: int | None
    estimated_arrival_spread: int | None
    resource_count: int
    hotspot_conflict_degree: int
    indirect_barrier_status: str = "not_computed"
    quantity_modes: tuple[tuple[str, str], ...] = (
        ("remaining_work", "residual_exact"),
        ("residual_tail", "structural_exact"),
        ("exclusive_tail", "structural_exact"),
        ("newly_ready_compute_work", "residual_exact"),
        ("newly_ready_compute_ids", "residual_exact"),
        ("reachable_descendant_compute_work", "structural_exact"),
        ("direct_last_missing_join_count", "structural_exact"),
        ("direct_last_missing_join_ids", "structural_exact"),
        ("downstream_join_tail", "structural_exact"),
        ("estimated_latest_branch_arrival", "heuristic_estimate"),
        ("estimated_second_latest_branch_arrival", "heuristic_estimate"),
        ("estimated_candidate_branch_arrival", "heuristic_estimate"),
        ("estimated_barrier_slack", "heuristic_estimate"),
        ("estimated_arrival_spread", "heuristic_estimate"),
        ("resource_count", "residual_exact"),
        ("hotspot_conflict_degree", "residual_exact"),
        ("indirect_barrier_status", "structural_exact"),
    )


@dataclass(frozen=True)
class BarrierActionFeatures:
    """De-duplicated features of one legal single or maximal multi action."""

    communication_ids: tuple[str, ...]
    newly_ready_compute_work: int
    newly_ready_compute_ids: tuple[str, ...]
    reachable_descendant_compute_work: int
    union_downstream_tail: int
    completed_direct_join_count: int
    completed_direct_join_ids: tuple[str, ...]
    occupied_resource_count: int
    excluded_candidate_count: int
    shared_downstream_count: int
    quantity_modes: tuple[tuple[str, str], ...] = (
        ("newly_ready_compute_work", "residual_exact"),
        ("newly_ready_compute_ids", "residual_exact"),
        ("reachable_descendant_compute_work", "structural_exact"),
        ("union_downstream_tail", "structural_exact"),
        ("completed_direct_join_count", "structural_exact"),
        ("completed_direct_join_ids", "structural_exact"),
        ("occupied_resource_count", "residual_exact"),
        ("excluded_candidate_count", "residual_exact"),
        ("shared_downstream_count", "structural_exact"),
    )


@dataclass(frozen=True)
class BarrierAnalysisContext:
    """Immutable data reused for all candidates at one decision boundary."""

    model: Any
    state: Any
    tasks: dict[str, Task]
    order: tuple[str, ...]
    children: dict[str, tuple[str, ...]]
    completed: frozenset[str]
    tails: dict[str, int]
    eligible: tuple[str, ...]
    resources: dict[str, frozenset[str]]


def build_context(
    model: Any, state: Any, *, roots: tuple[str, ...] | None = None
) -> BarrierAnalysisContext:
    """Build a full residual context; ``roots`` remains for API stability.

    Arrival estimates need every branch of a direct join, so selectively
    calculating tails from eligible roots would produce incomplete values.
    """

    del roots
    order = tuple(model.task_ids)
    tasks = model.task_map
    children = model.children
    completed = frozenset(
        task_id for task_id in order if _runtime(model, state, task_id).status == "completed"
    )
    tails: dict[str, int] = {}
    for task_id in reversed(order):
        tails[task_id] = _own_remaining(model, state, task_id, tasks[task_id]) + max(
            (tails[child] for child in children[task_id]), default=0
        )
    eligible = tuple(
        model.eligible_communications(state)
        if hasattr(model, "eligible_communications")
        else model.eligible(state)
    )
    resources = (
        {task_id: frozenset({"channel:0"}) for task_id in eligible}
        if hasattr(model, "eligible_communications")
        else {
            task_id: frozenset(getattr(model, "resources", {}).get(task_id, ()))
            for task_id in eligible
        }
    )
    return BarrierAnalysisContext(
        model, state, tasks, order, children, completed, tails, eligible, resources
    )


def feature_snapshot(context: BarrierAnalysisContext, task_id: str) -> BarrierFeatureSnapshot:
    """Return an auditable snapshot for one currently eligible communication."""

    if task_id not in context.eligible:
        raise ValueError(f"candidate {task_id!r} is not eligible")
    task = context.tasks[task_id]
    remaining = _own_remaining(context.model, context.state, task_id, task)
    joins = _direct_last_missing_joins(context, task_id)
    arrivals = _arrival_estimates(context, joins, task_id)
    newly_ready_ids = _newly_ready_compute_ids(context, (task_id,))
    descendants = _descendants(context, (task_id,))
    reachable_compute = sum(
        _own_remaining(context.model, context.state, item, context.tasks[item])
        for item in descendants
        if context.tasks[item].kind == "compute" and item not in context.completed
    )
    resources = context.resources.get(task_id, frozenset())
    hotspot = sum(
        bool(resources & context.resources.get(other, frozenset()))
        for other in context.eligible
        if other != task_id
    )
    return BarrierFeatureSnapshot(
        task_id=task_id,
        remaining_work=remaining,
        residual_tail=context.tails[task_id],
        exclusive_tail=max(0, context.tails[task_id] - remaining),
        newly_ready_compute_work=sum(context.tasks[item].duration for item in newly_ready_ids),
        newly_ready_compute_ids=newly_ready_ids,
        reachable_descendant_compute_work=reachable_compute,
        direct_last_missing_join_count=len(joins),
        direct_last_missing_join_ids=joins,
        downstream_join_tail=max((context.tails[item] for item in joins), default=0),
        estimated_latest_branch_arrival=arrivals[0],
        estimated_second_latest_branch_arrival=arrivals[1],
        estimated_candidate_branch_arrival=arrivals[2],
        estimated_barrier_slack=arrivals[3],
        estimated_arrival_spread=arrivals[4],
        resource_count=len(resources),
        hotspot_conflict_degree=hotspot,
    )


def priority_key(
    context: BarrierAnalysisContext, task_id: str, mode: str = "tail_barrier"
) -> tuple[object, ...]:
    """Dictionary-free online score used only by diagnostic policies."""

    snapshot = _online_inputs(context, task_id)
    if mode == "barrier_only":
        return (-snapshot.direct_last_missing_join_count, -snapshot.downstream_join_tail, task_id)
    if mode == "unlock_only":
        return (-snapshot.newly_ready_compute_work, task_id)
    if mode == "tail":
        return (-snapshot.exclusive_tail, task_id)
    if mode == "tail_unlock":
        return (-snapshot.exclusive_tail, -snapshot.newly_ready_compute_work, task_id)
    if mode in {"tail_barrier", "barrier_aware"}:
        return (-snapshot.exclusive_tail, -snapshot.direct_last_missing_join_count, -snapshot.downstream_join_tail, -snapshot.newly_ready_compute_work, task_id)
    if mode == "tail_unlock_barrier":
        return (-snapshot.exclusive_tail, -snapshot.newly_ready_compute_work, -snapshot.direct_last_missing_join_count, -snapshot.downstream_join_tail, task_id)
    raise ValueError(f"unknown barrier score mode: {mode}")


def has_barrier_signal(context: BarrierAnalysisContext, task_id: str) -> bool:
    """A direct last-missing join or a genuine immediate compute release."""

    snapshot = _online_inputs(context, task_id)
    return bool(snapshot.direct_last_missing_join_count or snapshot.newly_ready_compute_work)


@dataclass(frozen=True)
class OnlineBarrierInputs:
    """The bounded subset of fields used by online barrier policies.

    It intentionally omits descendant unions and arrival estimates. Those are
    audit fields and calculating them at every candidate would turn a small
    tie-break into an avoidable whole-reachable-subgraph scan.
    """

    exclusive_tail: int
    direct_last_missing_join_count: int
    newly_ready_compute_work: int
    downstream_join_tail: int


def online_barrier_inputs(
    context: BarrierAnalysisContext, task_id: str
) -> OnlineBarrierInputs:
    """Return only the residual fields consumed by online comparisons."""

    return _online_inputs(context, task_id)


def safe_barrier_prescreen(
    context: BarrierAnalysisContext,
    candidates: tuple[str, ...],
    longest_tail_action: str,
) -> tuple[str, ...]:
    """Return the candidates safe to retain before an LT decision.

    The current implementation recognizes direct joins only.  Absence of a
    direct signal cannot prove absence of an indirect barrier effect, so no
    non-LT candidate is removed.  This explicit no-op is preferable to an
    unverifiable filter and gives callers an auditable baseline for future
    stronger proofs.
    """

    if not candidates or longest_tail_action not in candidates:
        raise ValueError("prescreen requires a non-empty candidate set containing LT")
    if not set(candidates) <= set(context.eligible):
        raise ValueError("prescreen candidates must be currently eligible")
    return candidates


def action_features(
    context: BarrierAnalysisContext, communication_ids: tuple[str, ...]
) -> BarrierActionFeatures:
    """Compute set features with node unions, never per-member summation."""

    selected = tuple(sorted(set(communication_ids)))
    if not selected or not set(selected) <= set(context.eligible):
        raise ValueError("action must contain eligible communications")
    descendants = _descendants(context, selected)
    joins = tuple(sorted({join for item in selected for join in _direct_last_missing_joins(context, item)}))
    newly_ready_ids = _newly_ready_compute_ids(context, selected)
    occupied = set().union(*(context.resources.get(item, frozenset()) for item in selected))
    shared = sum(len(_descendants(context, (item,))) for item in selected) - len(descendants)
    return BarrierActionFeatures(
        communication_ids=selected,
        newly_ready_compute_work=sum(context.tasks[item].duration for item in newly_ready_ids),
        newly_ready_compute_ids=newly_ready_ids,
        reachable_descendant_compute_work=sum(
            _own_remaining(context.model, context.state, item, context.tasks[item])
            for item in descendants
            if context.tasks[item].kind == "compute" and item not in context.completed
        ),
        union_downstream_tail=max((context.tails[item] for item in descendants if item not in context.completed), default=0),
        completed_direct_join_count=len(joins),
        completed_direct_join_ids=joins,
        occupied_resource_count=len(occupied),
        excluded_candidate_count=len(set(context.eligible) - set(selected)),
        shared_downstream_count=max(0, shared),
    )


def score_snapshot(snapshot: BarrierFeatureSnapshot, mode: str = "tail_barrier") -> tuple[object, ...]:
    """Stable score used by diagnostic ablations, not an optimality claim."""

    if mode == "barrier_only":
        return (-snapshot.direct_last_missing_join_count, -snapshot.downstream_join_tail, snapshot.task_id)
    if mode == "unlock_only":
        return (-snapshot.newly_ready_compute_work, snapshot.task_id)
    if mode == "tail":
        return (-snapshot.exclusive_tail, snapshot.task_id)
    if mode == "tail_unlock":
        return (-snapshot.exclusive_tail, -snapshot.newly_ready_compute_work, snapshot.task_id)
    if mode in {"tail_barrier", "barrier_aware"}:
        return (-snapshot.exclusive_tail, -snapshot.direct_last_missing_join_count, -snapshot.downstream_join_tail, -snapshot.newly_ready_compute_work, snapshot.task_id)
    if mode == "tail_unlock_barrier":
        return (-snapshot.exclusive_tail, -snapshot.newly_ready_compute_work, -snapshot.direct_last_missing_join_count, -snapshot.downstream_join_tail, snapshot.task_id)
    raise ValueError(f"unknown barrier score mode: {mode}")


def _runtime(model: Any, state: Any, task_id: str) -> Any:
    return model.task_runtime(state, task_id) if hasattr(model, "task_runtime") else state.tasks[model.index[task_id]]


def _own_remaining(model: Any, state: Any, task_id: str, task: Task) -> int:
    runtime = _runtime(model, state, task_id)
    return 0 if runtime.status == "completed" else runtime.remaining or task.duration


def _online_inputs(context: BarrierAnalysisContext, task_id: str) -> OnlineBarrierInputs:
    if task_id not in context.eligible:
        raise ValueError(f"candidate {task_id!r} is not eligible")
    joins = _direct_last_missing_joins(context, task_id)
    remaining = _own_remaining(context.model, context.state, task_id, context.tasks[task_id])
    newly_ready = _newly_ready_compute_ids(context, (task_id,))
    return OnlineBarrierInputs(
        exclusive_tail=max(0, context.tails[task_id] - remaining),
        direct_last_missing_join_count=len(joins),
        newly_ready_compute_work=sum(context.tasks[item].duration for item in newly_ready),
        downstream_join_tail=max((context.tails[item] for item in joins), default=0),
    )


def _descendants(context: BarrierAnalysisContext, roots: tuple[str, ...]) -> frozenset[str]:
    seen, stack = set(roots), list(roots)
    while stack:
        current = stack.pop()
        for child in context.children[current]:
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return frozenset(seen)


def _direct_last_missing_joins(context: BarrierAnalysisContext, task_id: str) -> tuple[str, ...]:
    return tuple(sorted(
        child for child in context.children[task_id]
        if len(context.tasks[child].deps) > 1
        and all(dep == task_id or dep in context.completed for dep in context.tasks[child].deps)
    ))


def _newly_ready_compute_ids(
    context: BarrierAnalysisContext, completed_communications: tuple[str, ...]
) -> tuple[str, ...]:
    """Counterfactual completion plus same-time zero-compute closure.

    This reports only compute nodes that were pending beforehand and become
    ready after the selected communication(s) complete. It does not count
    descendants merely because they are structurally reachable.
    """

    completed = set(context.completed) | set(completed_communications)
    while True:
        newly_zero = [
            item for item in context.order
            if item not in completed
            and context.tasks[item].kind == "compute"
            and context.tasks[item].duration == 0
            and _runtime(context.model, context.state, item).status == "pending"
            and set(context.tasks[item].deps) <= completed
        ]
        if not newly_zero:
            break
        completed.update(newly_zero)
    return tuple(
        item for item in context.order
        if item not in completed
        and context.tasks[item].kind == "compute"
        and _runtime(context.model, context.state, item).status == "pending"
        and set(context.tasks[item].deps) <= completed
    )


def _path_estimate_to_join(
    context: BarrierAnalysisContext, start: str, join_id: str, memo: dict[str, int | None]
) -> int | None:
    if start in memo:
        return memo[start]
    if start == join_id:
        return 0
    children = [child for child in context.children[start] if join_id in _descendants(context, (child,))]
    if not children:
        memo[start] = None
        return None
    own = _own_remaining(context.model, context.state, start, context.tasks[start])
    values = [_path_estimate_to_join(context, child, join_id, memo) for child in children]
    values = [value for value in values if value is not None]
    memo[start] = own + max(values) if values else None
    return memo[start]


def _arrival_estimates(
    context: BarrierAnalysisContext, joins: tuple[str, ...], candidate: str
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    """Contention-free branch-to-join estimates for direct joins only."""

    rows: list[tuple[int, int, int]] = []
    for join_id in joins:
        values: list[tuple[str, int]] = []
        for dep in context.tasks[join_id].deps:
            if dep in context.completed:
                values.append((dep, 0))
            else:
                estimate = _path_estimate_to_join(context, dep, join_id, {})
                if estimate is not None:
                    values.append((dep, estimate))
        ordered = sorted((value for _dep, value in values), reverse=True)
        candidate_value = next((value for dep, value in values if dep == candidate), None)
        if ordered and candidate_value is not None:
            rows.append((ordered[0], ordered[1] if len(ordered) > 1 else 0, candidate_value))
    if not rows:
        return (None, None, None, None, None)
    latest, second, candidate_value = max(rows, key=lambda row: (row[0], row[1], row[2]))
    return (latest, second, candidate_value, max(0, latest - candidate_value), latest - min(second, candidate_value))


