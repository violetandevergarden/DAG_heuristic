"""Barrier-aware structural features for fixed-resource Stage 4 policies."""

from __future__ import annotations

from dataclasses import dataclass

from core.execution.preemptive import MultiResourceAction, MultiResourceState, PreeMultiModel


@dataclass(frozen=True)
class FeatureContext:
    model: PreeMultiModel
    state: MultiResourceState
    eligible: tuple[str, ...]
    completed: frozenset[str]
    tails: dict[str, int]


@dataclass(frozen=True)
class ActionFeatures:
    communication_ids: tuple[str, ...]
    newly_ready_compute_work: int
    completed_direct_join_count: int
    union_downstream_tail: int


def _remaining(model: PreeMultiModel, state: MultiResourceState, task_id: str) -> int:
    runtime = state.tasks[model.index[task_id]]
    return 0 if runtime.status == "completed" else runtime.remaining or model.task_map[task_id].duration


def _children(model: PreeMultiModel, task_id: str) -> tuple[str, ...]:
    return model.children[task_id]


def _descendants(model: PreeMultiModel, roots: tuple[str, ...]) -> frozenset[str]:
    seen = set(roots)
    stack = list(roots)
    while stack:
        current = stack.pop()
        for child in _children(model, current):
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return frozenset(seen)


def build_context(
    model: PreeMultiModel,
    state: MultiResourceState,
    *,
    roots: tuple[str, ...] | None = None,
) -> FeatureContext:
    del roots
    completed = frozenset(
        task_id for task_id in model.task_ids
        if state.tasks[model.index[task_id]].status == "completed"
    )
    tails: dict[str, int] = {}
    for task_id in reversed(model.task_ids):
        tails[task_id] = _remaining(model, state, task_id) + max(
            (tails[child] for child in _children(model, task_id)), default=0
        )
    return FeatureContext(model, state, tuple(model.eligible(state)), completed, tails)


def _direct_join_count(context: FeatureContext, task_id: str) -> int:
    return sum(
        len(context.model.task_map[child].deps) > 1
        and all(dep == task_id or dep in context.completed for dep in context.model.task_map[child].deps)
        for child in _children(context.model, task_id)
    )


def _new_compute_work(context: FeatureContext, task_id: str) -> int:
    completed = set(context.completed)
    completed.add(task_id)
    return sum(
        task.duration
        for item, task in context.model.task_map.items()
        if task.kind == "compute"
        and item not in completed
        and set(task.deps) <= completed
    )


def priority_key(context: FeatureContext, task_id: str, mode: str) -> tuple:
    if task_id not in context.eligible:
        raise ValueError(f"candidate {task_id!r} is not eligible")
    remaining = _remaining(context.model, context.state, task_id)
    exclusive_tail = max(0, context.tails[task_id] - remaining)
    joins = _direct_join_count(context, task_id)
    release = _new_compute_work(context, task_id)
    if mode == "barrier_only":
        return (-joins, -max((context.tails[item] for item in _children(context.model, task_id)), default=0), task_id)
    if mode == "unlock_only":
        return (-release, task_id)
    if mode in {"tail", "tail_barrier", "barrier_aware"}:
        return (-exclusive_tail, -joins, -release, task_id)
    if mode in {"tail_unlock", "tail_unlock_barrier"}:
        return (-exclusive_tail, -release, -joins, task_id)
    raise ValueError(f"unknown feature mode: {mode}")


def has_barrier_signal(context: FeatureContext, task_id: str) -> bool:
    return _direct_join_count(context, task_id) > 0 or _new_compute_work(context, task_id) > 0


def action_features(
    context: FeatureContext,
    action: MultiResourceAction | tuple[str, ...],
) -> ActionFeatures:
    selected = tuple(sorted(action.communications if isinstance(action, MultiResourceAction) else action))
    if not selected or not set(selected) <= set(context.eligible):
        raise ValueError("action must contain eligible communications")
    descendants = _descendants(context.model, selected)
    return ActionFeatures(
        selected,
        sum(_new_compute_work(context, item) for item in selected),
        sum(_direct_join_count(context, item) for item in selected),
        max((context.tails[item] for item in descendants), default=0),
    )


__all__ = [
    "ActionFeatures",
    "FeatureContext",
    "action_features",
    "build_context",
    "has_barrier_signal",
    "priority_key",
]
