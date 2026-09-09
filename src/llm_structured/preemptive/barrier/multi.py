"""Stage 4 barrier policies for fixed-resource preemptive DAGs."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from core.dag import DAG
from core.execution.preemptive import MultiResourceAction, PreeMultiModel
from core.oracle.pree_multi import MultiOracleResult
from muti_channel.preemptive.solver import (
    CompletionCache,
    complete_pack,
    result_from_actions,
    greedy_fill_from_task_scores,
    score_tasks,
    schedule_pack,
)
from .features import action_features, build_context, has_barrier_signal, priority_key


@dataclass(frozen=True)
class OfflineBarrierUpperBound:
    online: bool
    full_schedule_runs: int
    baseline: MultiOracleResult
    candidate: MultiOracleResult
    selected_policy: str
    runtime_ms: float


def _barrier_set_score(context, action: MultiResourceAction) -> tuple[object, ...]:
    features = action_features(context, action.communications)
    return (
        -features.newly_ready_compute_work,
        -features.completed_direct_join_count,
        -features.union_downstream_tail,
        features.communication_ids,
    )


def schedule_barrier_set_policy(
    dag: DAG,
    resources: dict[str, frozenset[str]],
) -> MultiOracleResult:
    started = perf_counter()
    model = PreeMultiModel(dag, resources)
    state = model.initial_state()
    actions: list[MultiResourceAction] = []
    generated = 0
    while not model.finished(state):
        state, _ = model.normalize_decision_state(state)
        if model.finished(state):
            break
        candidates = model.maximal_actions(state)
        generated += len(candidates)
        context = build_context(model, state)
        selected = min(candidates, key=lambda action: _barrier_set_score(context, action))
        actions.append(selected)
        state = model.step(state, selected)
    return result_from_actions(
        model,
        actions,
        runtime_ms=(perf_counter() - started) * 1000,
        compatible_sets_generated=generated,
        selector="barrier_set_policy",
    )


def schedule_selective_barrier_rollout(
    dag: DAG,
    resources: dict[str, frozenset[str]],
    *,
    max_triggers: int = 8,
    time_limit_s: float | None = 2.0,
) -> MultiOracleResult:
    if max_triggers < 0 or (time_limit_s is not None and time_limit_s < 0):
        raise ValueError("invalid rollout budget")
    started = perf_counter()
    model = PreeMultiModel(dag, resources)
    state = model.initial_state()
    actions: list[MultiResourceAction] = []
    triggered = improvements = completion_calls = fallback_count = 0
    fallback_reason: str | None = None
    cache = CompletionCache()
    while not model.finished(state):
        state, _ = model.normalize_decision_state(state)
        if model.finished(state):
            break
        baseline = greedy_fill_from_task_scores(model, state, score_tasks(model, state, "longest_tail"))
        context = build_context(model, state, roots=model.eligible(state))
        candidate = greedy_fill_from_task_scores(
            model,
            state,
            {item: priority_key(context, item, "barrier_only") for item in model.eligible(state)},
        )
        has_signal = any(has_barrier_signal(context, item) for item in candidate.communications)
        budget_ok = triggered < max_triggers and (time_limit_s is None or perf_counter() - started < time_limit_s)
        selected = baseline
        if candidate != baseline and has_signal and budget_ok:
            triggered += 1
            baseline_end, _ = complete_pack(model, model.step(state, baseline), cache=cache)
            candidate_end, _ = complete_pack(model, model.step(state, candidate), cache=cache)
            completion_calls += 2
            if candidate_end.time < baseline_end.time:
                selected = candidate
                improvements += 1
        elif candidate != baseline and has_signal:
            fallback_count += 1
            fallback_reason = "selective_trigger_limit" if triggered >= max_triggers else "selective_time_limit"
        actions.append(selected)
        state = model.step(state, selected)
    return result_from_actions(
        model,
        actions,
        runtime_ms=(perf_counter() - started) * 1000,
        completion_calls=completion_calls,
        evaluated_candidates=completion_calls,
        fallback_count=fallback_count,
        completed_search=fallback_count == 0,
        fallback_reason=fallback_reason,
        planner_decisions=len(actions),
        planner_triggered=triggered,
        planner_improvements=improvements,
    )


def offline_best_of_lt_and_barrier(
    dag: DAG,
    resources: dict[str, frozenset[str]],
) -> OfflineBarrierUpperBound:
    started = perf_counter()
    baseline = schedule_pack(dag, resources, "longest_tail")
    candidate = schedule_barrier_set_policy(dag, resources)
    return OfflineBarrierUpperBound(
        online=False,
        full_schedule_runs=2,
        baseline=baseline,
        candidate=candidate,
        selected_policy="barrier_candidate" if candidate.makespan < baseline.makespan else "longest_tail",
        runtime_ms=(perf_counter() - started) * 1000,
    )


__all__ = [
    "OfflineBarrierUpperBound",
    "offline_best_of_lt_and_barrier",
    "schedule_barrier_set_policy",
    "schedule_selective_barrier_rollout",
]
