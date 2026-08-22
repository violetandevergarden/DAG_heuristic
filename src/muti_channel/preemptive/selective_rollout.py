"""Stage 4d selective rollout over Stage 4c legal maximal sets."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from time import perf_counter

from core.dag import BenchmarkDAG
from core.execution.multi_resource import (
    MultiResourceAction, MultiResourceState, PreemptiveMultiResourceModel,
)
from llm_structured.selective_rollout import (
    BudgetAccount, RolloutBudget, Trigger, TriggerDecision, TriggerFeatures,
    choice_only,
)
from muti_channel.preemptive.constructors import multi_seed
from muti_channel.preemptive.packing import DecisionBudget, PackingBudget
from muti_channel.preemptive.solver import (
    _result, greedy_fill_from_task_scores, score_tasks,
)

FEATURE_VERSION = "multi-resource-selective-v2"


def _signature(action: MultiResourceAction) -> str:
    return "+".join(action.communications)


def generate_candidates(
    model: PreemptiveMultiResourceModel,
    state: MultiResourceState,
    limit: int,
) -> tuple[MultiResourceAction, ...]:
    """Bounded Stage 4c multi-seed sets, always starting with LT packing."""

    if limit <= 0:
        return ()
    packing_budget = PackingBudget(
        k_score=max(1, len(model.eligible(state))),
        k_seed=max(1, limit * 2),
        b_pack=max(1, len(model.eligible(state)) * max(4, limit * 2)),
        b_eval=0,
        max_sets=max(0, limit - 1),
        time_limit_s=None,
    )
    ledger = DecisionBudget(packing_budget)
    packed = multi_seed(
        model, state, score_tasks(model, state, "longest_tail"),
        packing_budget, ledger,
    )
    ordered = (packed.baseline, *packed.candidates)
    return tuple(dict.fromkeys(ordered))[:limit]


def _features(
    model: PreemptiveMultiResourceModel,
    state: MultiResourceState,
    candidates: tuple[MultiResourceAction, ...],
) -> TriggerFeatures:
    baseline = _signature(candidates[0])
    challenger = _signature(candidates[1]) if len(candidates) > 1 else None
    return TriggerFeatures(
        feature_version=FEATURE_VERSION,
        eligible_count=len(model.eligible(state)),
        action_count=len(candidates),
        lt_action=baseline,
        challenger_action=challenger,
        lrpt_action=challenger or baseline,
        fifo_action=baseline,
        lt_tail=0,
        second_tail=None,
        tail_margin=None,
        normalized_tail_margin=None,
        heuristic_disagreement=challenger is not None,
        active_communication_remaining=0,
        eligible_comm_delta=0,
        baseline_compute_release=0,
        challenger_compute_release=0,
        compute_release_delta=0,
        baseline_last_missing_join=False,
        challenger_last_missing_join=False,
        last_missing_join_difference=False,
    )


def _terminal_completion(
    model: PreemptiveMultiResourceModel,
    state: MultiResourceState,
    account: BudgetAccount,
    decision_started: float,
) -> tuple[int | None, str | None]:
    reason = account.try_reserve_completion(decision_started)
    if reason is not None:
        return None, reason
    current = state
    while not model.finished(current):
        current, forced = model.normalize_decision_state(current)
        if forced:
            reason = account.try_expand(decision_started, len(forced))
            if reason is not None:
                return None, reason
        if model.finished(current):
            break
        reason = account.try_expand(decision_started)
        if reason is not None:
            return None, reason
        action = greedy_fill_from_task_scores(
            model, current, score_tasks(model, current, "longest_tail")
        )
        current = model.step(current, action)
    return current.time, None


def _tree_value(
    model: PreemptiveMultiResourceModel,
    state: MultiResourceState,
    depth: int,
    account: BudgetAccount,
    decision_started: float,
    width: int,
    depth_used: int,
) -> tuple[int | None, int, str | None]:
    current, forced = model.normalize_decision_state(state)
    if forced:
        reason = account.try_expand(decision_started, len(forced))
        if reason is not None:
            return None, depth_used, reason
    if model.finished(current):
        return current.time, depth_used, None
    if depth <= 0:
        value, reason = _terminal_completion(model, current, account, decision_started)
        return value, depth_used, reason
    candidates = generate_candidates(model, current, width)
    account.generated_candidates += len(candidates)
    best: int | None = None
    reached = depth_used
    for action in candidates:
        reason = account.try_expand(decision_started)
        if reason is not None:
            return None, reached, reason
        value, child_depth, reason = _tree_value(
            model, model.step(current, action), depth - 1, account,
            decision_started, width, depth_used + 1,
        )
        reached = max(reached, child_depth)
        if reason is not None or value is None:
            return None, reached, reason or "incomplete_evaluation"
        best = value if best is None else min(best, value)
    return best, reached, None


def schedule_selective_rollout(
    dag: BenchmarkDAG,
    resources: dict[str, frozenset[str]],
    *,
    budget: RolloutBudget | None = None,
    trigger: Trigger = choice_only,
):
    """Select among legal maximal sets; incomplete search returns LT packing."""

    budget = budget or RolloutBudget()
    if budget.search_depth == 0 or budget.max_candidates < 2:
        from muti_channel.preemptive.solver import schedule_pack
        return schedule_pack(dag, resources, "longest_tail")
    model = PreemptiveMultiResourceModel(dag, resources)
    state = model.initial_state()
    actions: list[MultiResourceAction] = []
    account = BudgetAccount(budget)
    started = account.started
    fallbacks: list[str] = []
    details: list[str] = []
    reasons: Counter[str] = Counter()
    improvements = decisions = 0
    while not model.finished(state):
        state, _forced = model.normalize_decision_state(state)
        if model.finished(state):
            break
        decisions += 1
        candidates = generate_candidates(model, state, budget.max_candidates)
        account.generated_candidates += len(candidates)
        baseline = candidates[0]
        selected = baseline
        if len(candidates) > 1:
            decision_started = perf_counter()
            decision: TriggerDecision = trigger(_features(model, state, candidates))
            reasons[decision.reason] += int(decision.triggered)
            if decision.triggered:
                reason = account.try_reserve_trigger(decision_started)
                if reason is None:
                    values: list[tuple[MultiResourceAction, int]] = []
                    calls_before = account.completion_calls
                    expansions_before = account.expansions
                    actual_depth = 0
                    for action in candidates:
                        reason = account.try_expand(decision_started)
                        if reason is not None:
                            break
                        value, reached, reason = _tree_value(
                            model, model.step(state, action), budget.search_depth - 1,
                            account, decision_started, budget.max_candidates, 1,
                        )
                        actual_depth = max(actual_depth, reached)
                        if reason is not None or value is None:
                            break
                        values.append((action, value))
                        account.evaluated_candidates += 1
                    if reason is None and len(values) == len(candidates):
                        baseline_value = dict(values)[baseline]
                        best_value = min(value for _, value in values)
                        if best_value < baseline_value:
                            selected = min(
                                (action for action, value in values if value == best_value),
                                key=lambda item: item.communications,
                            )
                            improvements += 1
                        account.completed_evaluations += 1
                        account.max_actual_depth = max(account.max_actual_depth, actual_depth)
                    else:
                        account.budget_rejected_triggers += 1
                        fallbacks.append(reason or "incomplete_evaluation")
                        details.append(f"decision={decisions}:{fallbacks[-1]}")
                    _ = calls_before, expansions_before
                else:
                    fallbacks.append(reason)
                    details.append(f"decision={decisions}:{reason}")
        actions.append(selected)
        state = model.step(state, selected)
    result = _result(model, actions, runtime_ms=(perf_counter() - started) * 1000)
    counts = Counter(fallbacks)
    return replace(
        result,
        expanded_nodes=account.expansions,
        evaluated_candidates=account.evaluated_candidates,
        completion_calls=account.completion_calls,
        generated_candidates=account.generated_candidates,
        fallback_count=len(fallbacks),
        fallback_reasons=tuple(sorted(counts.items())),
        planner_decisions=decisions,
        planner_triggered=account.trigger_positives,
        planner_improvements=improvements,
        trigger_positives=account.trigger_positives,
        completed_rollout_evaluations=account.completed_evaluations,
        budget_rejected_triggers=account.budget_rejected_triggers,
        max_actual_depth=account.max_actual_depth,
        trigger_reason_counts=tuple(sorted(reasons.items())),
        fallback_details=tuple(details),
        selector="stage4d_selective_rollout",
    )
