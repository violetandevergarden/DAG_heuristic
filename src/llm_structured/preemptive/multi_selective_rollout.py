"""Stage 4d selective rollout entry point for multi-resource DAGs."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from core.dag import DAG
from core.execution.preemptive import MultiResourceAction, MultiResourceState, PreeMultiModel
from muti_channel.preemptive.packing_constructors import multi_seed
from muti_channel.preemptive.packing import DecisionBudget, PackingBudget
from muti_channel.preemptive.solver import schedule_pack, score_tasks
from .multi_barrier import schedule_selective_barrier_rollout


class RolloutBudget(Protocol):
    max_candidates: int
    max_triggers: int
    max_completion_calls: int
    search_depth: int
    total_time_limit_s: float | None


def generate_candidates(model: PreeMultiModel, state: MultiResourceState, limit: int) -> tuple[MultiResourceAction, ...]:
    if limit <= 0:
        return ()
    budget = PackingBudget(
        k_score=max(1, len(model.eligible(state))),
        k_seed=max(1, limit * 2),
        b_pack=max(1, len(model.eligible(state)) * max(4, limit * 2)),
        b_eval=0,
        max_sets=max(0, limit - 1),
        time_limit_s=None,
    )
    result = multi_seed(model, state, score_tasks(model, state, "longest_tail"), budget, DecisionBudget(budget))
    return tuple(dict.fromkeys((result.baseline, *result.candidates)))[:limit]


def schedule_selective_rollout(dag: DAG, resources: dict[str, frozenset[str]], *, budget: RolloutBudget):
    baseline = schedule_pack(dag, resources, "longest_tail")
    if budget.search_depth == 0 or budget.max_candidates < 2:
        return baseline
    result = schedule_selective_barrier_rollout(
        dag,
        resources,
        max_triggers=budget.max_triggers,
        time_limit_s=budget.total_time_limit_s,
    )
    if result.completion_calls > budget.max_completion_calls:
        return replace(
            baseline,
            fallback_count=1,
            fallback_reason="completion_call_limit",
            completed_search=False,
            selector="stage4d_family_fallback",
        )
    return result


__all__ = ["generate_candidates", "schedule_selective_rollout"]
