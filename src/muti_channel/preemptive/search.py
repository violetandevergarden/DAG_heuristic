"""Budgeted generic search for fixed-resource preemptive scheduling."""

from __future__ import annotations

from dataclasses import replace
from time import perf_counter
from typing import Literal

from core.dag import DAG
from core.execution.preemptive import MultiResourceAction, PreeMultiModel
from core.oracle.pree_multi import RolloutStats
from core.oracle.pree_multi import normalized_state_key
from .packing import DecisionBudget, PackingBudget
from .packing_constructors import (
    choose_by_depth1_longest_tail,
    enumerate_bounded,
    greedy,
    multi_seed,
    one_exchange,
)
from .solver import (
    CompletionCache,
    MultiResult,
    complete_pack,
    greedy_fill_from_task_scores,
    remaining_lower_bound,
    result_from_actions,
    score_sets,
    score_tasks,
    select_best_scored_set,
)


class _BudgetExceeded(RuntimeError):
    pass


def schedule_bounded_packing(
    dag: DAG,
    resources: dict[str, frozenset[str]],
    *,
    constructor: str = "multi_seed",
    score_mode: str = "longest_tail",
    rollout: bool = False,
    selector: Literal["baseline", "set_score", "depth1_completion"] | None = None,
    budget=None,
) -> MultiResult:
    started = perf_counter()
    budget = budget or PackingBudget()
    if selector is None:
        selector = "depth1_completion" if rollout else "baseline"
    if rollout and selector != "depth1_completion":
        raise ValueError("rollout is only compatible with depth1_completion")
    builders = {
        "greedy": greedy,
        "multi_seed": lambda model, state, scores, ledger: multi_seed(model, state, scores, budget, ledger),
        "one_exchange": lambda model, state, scores, ledger: one_exchange(model, state, scores, budget, ledger),
        "enumeration": lambda model, state, scores, ledger: enumerate_bounded(model, state, scores, budget, ledger),
    }
    if constructor not in builders:
        raise ValueError(f"unknown packing constructor: {constructor}")
    model = PreeMultiModel(dag, resources)
    state = model.initial_state()
    actions: list[MultiResourceAction] = []
    evaluated = generated = fallbacks = calls = improvements = triggered = max_calls = 0
    fallback_reasons: dict[str, int] = {}
    while not model.finished(state):
        state, _ = model.normalize_decision_state(state)
        if model.finished(state):
            break
        ledger = DecisionBudget(budget)
        packed = builders[constructor](model, state, score_tasks(model, state, score_mode), ledger)
        action = packed.baseline
        generated += packed.stats.generated_candidates
        if selector == "set_score" and packed.candidates:
            choices = (packed.baseline, *packed.candidates)
            action = select_best_scored_set(score_sets(model, state, choices, "union_downstream"))
            evaluated += len(choices)
            triggered += 1
        elif selector == "depth1_completion" and packed.candidates:
            action, used = choose_by_depth1_longest_tail(model, state, packed, ledger)
            calls += used
            evaluated += used
            triggered += 1
        else:
            reason = "selector_baseline" if selector == "baseline" else "no_alternative"
            fallback_reasons[reason] = fallback_reasons.get(reason, 0) + 1
        packed = replace(packed, selected=action, selector=selector, fallback_reason=ledger.fallback_reason or packed.fallback_reason)
        if packed.fallback_reason:
            fallbacks += 1
            fallback_reasons[packed.fallback_reason] = fallback_reasons.get(packed.fallback_reason, 0) + 1
        improvements += action != packed.baseline
        max_calls = max(max_calls, ledger.completion_calls)
        actions.append(action)
        state = model.step(state, action)
    result = result_from_actions(
        model, actions, runtime_ms=(perf_counter() - started) * 1000,
        lower_bound=remaining_lower_bound(model, model.initial_state()),
    )
    return replace(result, evaluated_candidates=evaluated, completion_calls=calls,
                   fallback_count=fallbacks, planner_decisions=len(actions),
                   planner_triggered=triggered, planner_improvements=improvements,
                   generated_candidates=generated, fallback_reasons=tuple(sorted(fallback_reasons.items())),
                   selector=selector, max_completion_calls_per_decision=max_calls)


def rollout_sets(
    dag: DAG,
    resources: dict[str, frozenset[str]],
    *,
    top_k: int = 2,
    depth: int = 2,
    node_budget: int = 10_000,
    set_budget: int = 50_000,
    time_limit_s: float | None = 1.0,
) -> MultiResult:
    if top_k < 1 or depth < 1 or node_budget < 1 or set_budget < 1:
        raise ValueError("rollout budgets, top_k, depth and budgets must be positive")
    started = perf_counter()
    model = PreeMultiModel(dag, resources)
    state = model.initial_state()
    actions: list[MultiResourceAction] = []
    memo: dict[tuple[int, tuple[tuple[str, int], ...]], int] = {}
    expanded = evaluated = completion_calls = cache_hits = generated = 0
    fallback_count = 0
    fallback_reason: str | None = None
    completion_cache = CompletionCache()

    def check_budget() -> None:
        if expanded >= node_budget:
            raise _BudgetExceeded("expanded_node_budget")
        if generated >= set_budget:
            raise _BudgetExceeded("compatible_set_budget")
        if time_limit_s is not None and perf_counter() - started >= time_limit_s:
            raise _BudgetExceeded("wall_clock_budget")

    def candidates(current):
        nonlocal generated
        check_budget()
        all_actions = model.maximal_actions(current)
        generated += len(all_actions)
        baseline = greedy_fill_from_task_scores(model, current, score_tasks(model, current, "longest_tail"))
        scores = score_sets(model, current, all_actions, "union_downstream")
        ranked = sorted(all_actions, key=scores.__getitem__)
        selected = list(ranked[:top_k])
        if baseline not in selected:
            selected.append(baseline)
        return tuple(sorted(set(selected), key=lambda item: item.communications))

    def evaluate(current, remaining_depth: int) -> int:
        nonlocal expanded, evaluated, completion_calls, cache_hits
        current, _ = model.normalize_decision_state(current)
        if model.finished(current):
            return current.time
        key = (remaining_depth, normalized_state_key(current))
        if key in memo:
            cache_hits += 1
            return current.time + memo[key]
        check_budget()
        expanded += 1
        if remaining_depth == 0:
            completion_calls += 1
            completed, _ = complete_pack(model, current, cache=completion_cache)
            value = completed.time
        else:
            branch = candidates(current)
            evaluated += len(branch)
            value = min(evaluate(model.step(current, action), remaining_depth - 1) for action in branch)
        memo[key] = value - current.time
        return value

    while not model.finished(state):
        state, _ = model.normalize_decision_state(state)
        if model.finished(state):
            break
        baseline = greedy_fill_from_task_scores(model, state, score_tasks(model, state, "longest_tail"))
        try:
            scored = [(evaluate(model.step(state, action), depth - 1), action.communications, action) for action in candidates(state)]
            action = min(scored)[2]
        except _BudgetExceeded as error:
            action = baseline
            fallback_count += 1
            fallback_reason = str(error)
        actions.append(action)
        state = model.step(state, action)
    return result_from_actions(
        model, actions, runtime_ms=(perf_counter() - started) * 1000,
        lower_bound=remaining_lower_bound(model, model.initial_state()),
        compatible_sets_generated=generated, expanded_nodes=expanded,
        evaluated_candidates=evaluated, completion_calls=completion_calls,
        cache_hits=cache_hits, fallback_count=fallback_count,
        completed_search=fallback_count == 0, fallback_reason=fallback_reason,
        rollout_stats=RolloutStats(expanded, evaluated, completion_calls,
                                   cache_hits + completion_cache.hits, fallback_count),
    )


__all__ = ["rollout_sets", "schedule_bounded_packing"]
