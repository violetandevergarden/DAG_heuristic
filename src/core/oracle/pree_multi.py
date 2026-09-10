"""Exact search for fixed-resource preemptive DAG scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Literal

from core.dag import DAG
from core.execution.preemptive import (
    MultiResourceAction,
    MultiResourceState,
    MultiResourceTrace,
    PreeMultiModel,
)
from core.trace.pree_multi import assert_preemptive_multi_trace


@dataclass(frozen=True)
class ExactStats:
    explored_states: int = 0
    generated_transitions: int = 0
    deduplicated_states: int = 0
    pruned_states: int = 0


@dataclass(frozen=True)
class PackingStats:
    compatible_sets_generated: int = 0
    max_branch: int = 0
    set_enumeration_ms: float = 0.0


@dataclass(frozen=True)
class RolloutStats:
    expanded_nodes: int = 0
    evaluated_candidates: int = 0
    completion_calls: int = 0
    cache_hits: int = 0
    fallback_count: int = 0


@dataclass(frozen=True)
class MultiOracleResult:
    makespan: int
    actions: tuple[MultiResourceAction, ...]
    decision_count: int
    preemptions: int
    explored_states: int = 0
    trace: MultiResourceTrace | None = None
    status: Literal["feasible", "optimal"] = "feasible"
    termination_reason: str | None = None
    runtime_ms: float = 0.0
    lower_bound: int = 0
    generated_transitions: int = 0
    deduplicated_states: int = 0
    pruned_states: int = 0
    compatible_sets_generated: int = 0
    mean_branch: float = 0.0
    max_branch: int = 0
    set_enumeration_ms: float = 0.0
    peak_states: int = 0
    peak_memory_bytes: int | None = None
    expanded_nodes: int = 0
    evaluated_candidates: int = 0
    completion_calls: int = 0
    cache_hits: int = 0
    fallback_count: int = 0
    completed_search: bool = True
    fallback_reason: str | None = None
    planner_decisions: int = 0
    planner_triggered: int = 0
    planner_improvements: int = 0
    generated_candidates: int = 0
    fallback_reasons: tuple[tuple[str, int], ...] = ()
    selector: str | None = None
    max_completion_calls_per_decision: int = 0
    trigger_positives: int = 0
    completed_rollout_evaluations: int = 0
    budget_rejected_triggers: int = 0
    max_actual_depth: int = 0
    trigger_reason_counts: tuple[tuple[str, int], ...] = ()
    fallback_details: tuple[str, ...] = ()
    exact_stats: ExactStats | None = None
    packing_stats: PackingStats | None = None
    rollout_stats: RolloutStats | None = None


StateKey = tuple[object, ...]


class _BudgetExceeded(RuntimeError):
    pass


def normalized_state_key(state: MultiResourceState) -> StateKey:
    return tuple((item.status, item.remaining) for item in state.tasks)


def uncompressed_state_key(state: MultiResourceState) -> StateKey:
    return (state.time, state.tasks, state.active_allocations, state.resource_owners)


def _remaining(model: PreeMultiModel, state: MultiResourceState, index: int) -> int:
    runtime = state.tasks[index]
    if runtime.status == "completed":
        return 0
    return runtime.remaining or model.tasks[index].duration


def _tails(model: PreeMultiModel, state: MultiResourceState) -> dict[str, int]:
    values: dict[str, int] = {}
    for task_id in reversed(model.task_ids):
        index = model.index[task_id]
        values[task_id] = _remaining(model, state, index) + max(
            (values[child] for child in model.children[task_id]), default=0
        )
    return values


def remaining_lower_bound(model: PreeMultiModel, state: MultiResourceState) -> int:
    state, _ = model.normalize_decision_state(state)
    tails = _tails(model, state)
    loads: dict[str, int] = {}
    for task_id in model.task_ids:
        index = model.index[task_id]
        if model.tasks[index].kind != "comm":
            continue
        remaining = _remaining(model, state, index)
        for resource in model.resources[task_id]:
            loads[resource] = loads.get(resource, 0) + remaining
    return state.time + max(max(tails.values(), default=0), max(loads.values(), default=0))


def _greedy_completion(
    model: PreeMultiModel,
    state: MultiResourceState,
) -> tuple[MultiResourceState, tuple[MultiResourceAction, ...]]:
    actions: list[MultiResourceAction] = []
    while not model.finished(state):
        state, _ = model.normalize_decision_state(state)
        if model.finished(state):
            break
        tails = _tails(model, state)
        selected: list[str] = []
        used: set[str] = set()
        for task_id in sorted(model.eligible(state), key=lambda item: (-tails[item], item)):
            resources = model.resources[task_id]
            if used.isdisjoint(resources):
                selected.append(task_id)
                used.update(resources)
        action = MultiResourceAction(tuple(sorted(selected)))
        actions.append(action)
        state = model.step(state, action)
    return state, tuple(actions)


def _result(
    model: PreeMultiModel,
    actions: tuple[MultiResourceAction, ...],
    **values: object,
) -> MultiOracleResult:
    trace = model.run(actions)
    assert_preemptive_multi_trace(model.dag, model.resources, trace)
    return MultiOracleResult(
        trace.makespan,
        actions,
        len(actions),
        sum(
            1
            for task_id in model.task_ids
            if sum(span.task_id == task_id for span in trace.intervals if span.kind == "comm") > 1
        ),
        trace=trace,
        **values,
    )


def exact_oracle(
    dag: DAG,
    resources: dict[str, frozenset[str]],
    *,
    max_states: int = 300_000,
    time_limit_s: float | None = 5.0,
    normalized: bool = True,
) -> MultiOracleResult:
    if max_states < 1:
        raise ValueError("max_states must be positive")
    started = perf_counter()
    model = PreeMultiModel(dag, resources)
    initial, _ = model.normalize_decision_state(model.initial_state())
    baseline_state, baseline_actions = _greedy_completion(model, initial)
    key_fn = normalized_state_key if normalized else uncompressed_state_key
    memo: dict[StateKey, tuple[int, tuple[MultiResourceAction, ...]]] = {}
    explored = generated = duplicates = pruned = sets = max_branch = 0

    def check() -> None:
        if explored >= max_states:
            raise _BudgetExceeded("state_limit")
        if time_limit_s is not None and perf_counter() - started >= time_limit_s:
            raise _BudgetExceeded("time_limit")

    def search(state: MultiResourceState) -> tuple[int, tuple[MultiResourceAction, ...]]:
        nonlocal explored, generated, duplicates, pruned, sets, max_branch
        state, _ = model.normalize_decision_state(state)
        key = key_fn(state)
        if key in memo:
            duplicates += 1
            return memo[key]
        check()
        explored += 1
        if model.finished(state):
            memo[key] = (0, ())
            return memo[key]
        completed, suffix = _greedy_completion(model, state)
        best = completed.time - state.time
        best_actions = suffix
        actions = model.maximal_actions(state)
        sets += len(actions)
        max_branch = max(max_branch, len(actions))
        for action in actions:
            check()
            after = model.step(state, action)
            generated += 1
            immediate = after.time - state.time
            if immediate + remaining_lower_bound(model, after) > completed.time:
                pruned += 1
                continue
            residual, suffix_actions = search(after)
            candidate = immediate + residual
            candidate_actions = (action, *suffix_actions)
            if (candidate, tuple(item.communications for item in candidate_actions)) < (
                best, tuple(item.communications for item in best_actions)
            ):
                best, best_actions = candidate, candidate_actions
        memo[key] = (best, best_actions)
        return memo[key]

    try:
        _, actions = search(initial)
        status, reason = "optimal", "complete_enumeration"
    except _BudgetExceeded as error:
        actions = baseline_actions
        status, reason = "feasible", str(error)
    result = _result(
        model,
        tuple(actions),
        status=status,
        termination_reason=reason,
        runtime_ms=(perf_counter() - started) * 1000,
        lower_bound=remaining_lower_bound(model, model.initial_state()),
        explored_states=explored,
        generated_transitions=generated,
        deduplicated_states=duplicates,
        pruned_states=pruned,
        compatible_sets_generated=sets,
        mean_branch=sets / explored if explored else 0.0,
        max_branch=max_branch,
        peak_states=explored,
        exact_stats=ExactStats(explored, generated, duplicates, pruned),
    )
    if status == "feasible" and result.makespan != baseline_state.time:
        raise AssertionError("budget fallback must return deterministic baseline")
    return result


def exact_oracle_uncompressed(dag: DAG, resources: dict[str, frozenset[str]], **options: object) -> MultiOracleResult:
    return exact_oracle(dag, resources, normalized=False, **options)


def exact_completion_from_state_uncompressed(
    model: PreeMultiModel,
    state: MultiResourceState,
    *,
    max_states: int = 100_000,
    time_limit_s: float | None = 5.0,
) -> MultiOracleResult:
    """Return an exact suffix certificate from a public stable state."""
    started = perf_counter()
    initial, _ = model.normalize_decision_state(state)
    baseline, baseline_actions = _greedy_completion(model, initial)
    memo: dict[StateKey, tuple[int, tuple[MultiResourceAction, ...]]] = {}
    explored = generated = 0

    def search(current: MultiResourceState) -> tuple[int, tuple[MultiResourceAction, ...]]:
        nonlocal explored, generated
        current, _ = model.normalize_decision_state(current)
        key = uncompressed_state_key(current)
        if key in memo:
            return memo[key]
        if explored >= max_states:
            raise _BudgetExceeded("state_limit")
        if time_limit_s is not None and perf_counter() - started >= time_limit_s:
            raise _BudgetExceeded("time_limit")
        explored += 1
        if model.finished(current):
            memo[key] = (0, ())
            return memo[key]
        completed, suffix = _greedy_completion(model, current)
        best = completed.time - current.time
        best_actions = suffix
        for action in model.maximal_actions(current):
            after = model.step(current, action)
            generated += 1
            residual, residual_actions = search(after)
            candidate = after.time - current.time + residual
            candidate_actions = (action, *residual_actions)
            if (candidate, tuple(item.communications for item in candidate_actions)) < (
                best, tuple(item.communications for item in best_actions)
            ):
                best, best_actions = candidate, candidate_actions
        memo[key] = (best, best_actions)
        return memo[key]

    try:
        cost, actions = search(initial)
        status, reason = "optimal", "complete_enumeration"
        makespan = initial.time + cost
    except _BudgetExceeded as error:
        actions = baseline_actions
        status, reason = "feasible", str(error)
        makespan = baseline.time
    return MultiOracleResult(
        makespan,
        tuple(actions),
        len(actions),
        0,
        explored_states=explored,
        status=status,
        termination_reason=reason,
        runtime_ms=(perf_counter() - started) * 1000,
        generated_transitions=generated,
    )


__all__ = [
    "MultiOracleResult",
    "ExactStats",
    "PackingStats",
    "RolloutStats",
    "exact_oracle",
    "exact_oracle_uncompressed",
    "exact_completion_from_state_uncompressed",
    "normalized_state_key",
    "remaining_lower_bound",
    "uncompressed_state_key",
]
