"""Budgeted depth-1 LT enhancement for the public single-channel model."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from time import perf_counter

from core.dag import BenchmarkDAG
from core.execution.preemptive import Action, PreemptiveDAGModel, ScheduleState
from llm_structured.selective_rollout import (
    BudgetAccount,
    ChoiceSummary,
    EvaluationOutcome,
    RolloutBudget,
    Trigger,
    TriggerDecision,
    TriggerFeatures,
    choice_only,
)
from single_channel.complex_chain.preemptive import solver

FEATURE_VERSION = "single-channel-selective-v1"


@dataclass
class TimingAudit:
    choice_gate_ms: float = 0.0
    cheap_feature_ms: float = 0.0
    expensive_feature_ms: float = 0.0
    candidate_generation_ms: float = 0.0
    completion_ms: float = 0.0


def summarize_choice(model: PreemptiveDAGModel, state: ScheduleState) -> ChoiceSummary:
    eligible = model.eligible_communications(state)
    signatures = tuple(eligible)
    if len(eligible) <= 1:
        kind = "no_choice"
    else:
        children = tuple(
            solver.normalized_state_key(model.step(state, Action.run(item)).after)
            for item in eligible
        )
        kind = "equivalent_choice" if len(set(children)) == 1 else "candidate_choice"
    return ChoiceSummary(kind, len(eligible), len(eligible), signatures)


def cheap_features(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    *,
    ready_set_delta: int = 0,
) -> TriggerFeatures:
    eligible = model.eligible_communications(state)
    if not eligible:
        raise ValueError("cheap features require an eligible communication")
    tails = solver.residual_tail(model, state, eligible)
    ranked_lt = sorted(
        eligible,
        key=lambda item: solver._priority_key(model, state, item, "longest_tail", tails),
    )
    ranked_lrpt = sorted(
        eligible, key=lambda item: solver._priority_key(model, state, item, "lrpt", tails)
    )
    lt = ranked_lt[0]
    challenger = next((item for item in ranked_lrpt if item != lt), None)
    if challenger is None:
        ranked_join = sorted(
            eligible,
            key=lambda item: solver._priority_key(model, state, item, "join_aware", tails),
        )
        challenger = next((item for item in ranked_join if item != lt), None)
    exclusive = {
        item: tails[item] - solver._own_remaining(model, state, item) for item in eligible
    }
    ordered_values = sorted(exclusive.values(), reverse=True)
    margin = ordered_values[0] - ordered_values[1] if len(ordered_values) > 1 else None
    normalizer = max(ordered_values[0], 1)
    active_remaining = 0
    if state.last_communication in eligible:
        active_remaining = solver._own_remaining(model, state, state.last_communication)
    return TriggerFeatures(
        FEATURE_VERSION,
        len(eligible),
        len(eligible),
        lt,
        challenger,
        exclusive[lt],
        ordered_values[1] if len(ordered_values) > 1 else None,
        margin,
        None if margin is None else margin / normalizer,
        bool(challenger and challenger != lt),
        active_remaining,
        ready_set_delta,
        any(solver.immediate_compute_delay(model, state, item) > 0 for item in eligible),
        any(solver.direct_last_blocker_gain(model, state, item, tails) > 0 for item in eligible),
    )


def _lt_completion_value(model: PreemptiveDAGModel, state: ScheduleState) -> tuple[int, int]:
    actions = solver._complete_actions(model, state, "longest_tail")
    return solver._apply_actions(model, state, actions).time, len(actions)


def evaluate_depth1(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    lt_action: str,
    challenger_action: str | None,
    account: BudgetAccount,
    *,
    decision_started: float,
) -> EvaluationOutcome:
    started = perf_counter()
    selected = lt_action
    if challenger_action is None or challenger_action == lt_action:
        return EvaluationOutcome(selected, lt_action, challenger_action, None, None, False,
                                 "no_distinct_challenger", 0, 0, 0.0)
    legal = model.legal_actions(state)
    if Action.run(challenger_action) not in legal:
        return EvaluationOutcome(selected, lt_action, challenger_action, None, None, False,
                                 "illegal_challenger", 0, 0, 0.0)
    if account.completion_calls + 2 > account.budget.max_completion_calls:
        account.note("completion_call_limit")
        return EvaluationOutcome(selected, lt_action, challenger_action, None, None, False,
                                 "completion_call_limit", 0, 0, 0.0)
    deadline = account.budget.per_decision_time_limit_s
    if deadline is not None and perf_counter() - decision_started >= deadline:
        account.note("per_decision_time_limit")
        return EvaluationOutcome(selected, lt_action, challenger_action, None, None, False,
                                 "per_decision_time_limit", 0, 0, 0.0)
    lt_after = model.step(state, Action.run(lt_action)).after
    challenger_after = model.step(state, Action.run(challenger_action)).after
    lt_value, lt_expansions = _lt_completion_value(model, lt_after)
    account.completion_calls += 1
    account.expansions += lt_expansions
    if account.expansions > account.budget.max_expansions:
        account.note("expansion_limit")
        return EvaluationOutcome(selected, lt_action, challenger_action, lt_value, None, False,
                                 "expansion_limit", 1, lt_expansions,
                                 (perf_counter() - started) * 1000)
    if deadline is not None and perf_counter() - decision_started >= deadline:
        account.note("per_decision_time_limit")
        return EvaluationOutcome(selected, lt_action, challenger_action, lt_value, None, False,
                                 "per_decision_time_limit", 1, lt_expansions,
                                 (perf_counter() - started) * 1000)
    challenger_value, challenger_expansions = _lt_completion_value(model, challenger_after)
    account.completion_calls += 1
    account.expansions += challenger_expansions
    improved = challenger_value < lt_value
    if improved:
        selected = challenger_action
    return EvaluationOutcome(
        selected, lt_action, challenger_action, lt_value, challenger_value, improved,
        None if improved else "challenger_not_strictly_better", 2,
        lt_expansions + challenger_expansions, (perf_counter() - started) * 1000,
    )


def evaluate_rollout(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    lt_action: str,
    challenger_action: str | None,
    account: BudgetAccount,
    *,
    decision_started: float,
) -> EvaluationOutcome:
    """Compare LT with a candidate prefix, optionally looking one node ahead.

    The second action is always selected from the simulator's eligible set and
    defaults to LT.  Thus depth-2 spends the same two completion calls as
    depth-1 while evaluating a longer candidate prefix.
    """
    depth = account.budget.rollout_depth
    if depth <= 1:
        return evaluate_depth1(model, state, lt_action, challenger_action, account,
                               decision_started=decision_started)
    if challenger_action is None or challenger_action == lt_action:
        return EvaluationOutcome(lt_action, lt_action, challenger_action, None, None, False,
                                 "no_distinct_challenger", 0, 0, 0.0)
    if Action.run(challenger_action) not in model.legal_actions(state):
        return EvaluationOutcome(lt_action, lt_action, challenger_action, None, None, False,
                                 "illegal_challenger", 0, 0, 0.0)
    if account.completion_calls + 2 > account.budget.max_completion_calls:
        account.note("completion_call_limit")
        return EvaluationOutcome(lt_action, lt_action, challenger_action, None, None, False,
                                 "completion_call_limit", 0, 0, 0.0)
    started = perf_counter()

    def prefix_value(first: str) -> tuple[int, int]:
        current = model.step(state, Action.run(first)).after
        expansions = 1
        for _ in range(depth - 1):
            eligible = model.eligible_communications(current)
            if not eligible:
                break
            second = solver._baseline_choice(model, current, "longest_tail")
            current = model.step(current, Action.run(second)).after
            expansions += 1
        value, tail_expansions = _lt_completion_value(model, current)
        return value, expansions + tail_expansions

    lt_value, lt_expansions = prefix_value(lt_action)
    account.completion_calls += 1
    account.expansions += lt_expansions
    if account.expansions > account.budget.max_expansions:
        account.note("expansion_limit")
        return EvaluationOutcome(lt_action, lt_action, challenger_action, lt_value, None, False,
                                 "expansion_limit", 1, lt_expansions,
                                 (perf_counter() - started) * 1000)
    deadline = account.budget.per_decision_time_limit_s
    if deadline is not None and perf_counter() - decision_started >= deadline:
        account.note("per_decision_time_limit")
        return EvaluationOutcome(lt_action, lt_action, challenger_action, lt_value, None, False,
                                 "per_decision_time_limit", 1, lt_expansions,
                                 (perf_counter() - started) * 1000)
    challenger_value, challenger_expansions = prefix_value(challenger_action)
    account.completion_calls += 1
    account.expansions += challenger_expansions
    improved = challenger_value < lt_value
    return EvaluationOutcome(
        challenger_action if improved else lt_action, lt_action, challenger_action,
        lt_value, challenger_value, improved,
        None if improved else "challenger_not_strictly_better", 2,
        lt_expansions + challenger_expansions, (perf_counter() - started) * 1000,
    )


def schedule_selective_rollout(
    dag: BenchmarkDAG,
    *,
    budget: RolloutBudget | None = None,
    trigger: Trigger = choice_only,
    use_cache: bool = True,
):
    solver.validate_complex_chain(dag)
    budget = budget or RolloutBudget()
    if budget.max_candidates < 2:
        return replace(solver.schedule_longest_tail(dag), fallback_count=1,
                       fallback_reasons=("candidate_limit",))
    model = PreemptiveDAGModel(dag)
    state = model.initial_state()
    actions: list[Action] = []
    account = BudgetAccount(budget)
    timing = TimingAudit()
    cache: dict[tuple[object, str], TriggerFeatures] = {}
    started = perf_counter()
    decisions = improvements = fallback_count = 0
    fallback_reasons: list[str] = []
    previous_eligible: set[str] = set()
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        if not eligible:
            action = Action.wait()
        else:
            decisions += 1
            gate_started = perf_counter()
            summary = summarize_choice(model, state)
            timing.choice_gate_ms += (perf_counter() - gate_started) * 1000
            lt = solver._baseline_choice(model, state, "longest_tail")
            selected = lt
            total_expired = budget.total_time_limit_s is not None and perf_counter() - started >= budget.total_time_limit_s
            if summary.kind == "candidate_choice" and not total_expired and account.triggers < budget.max_triggers:
                feature_started = perf_counter()
                key = (solver.normalized_state_key(state), FEATURE_VERSION)
                features = cache.get(key) if use_cache else None
                if features is None:
                    features = cheap_features(model, state, ready_set_delta=len(set(eligible) - previous_eligible))
                    if use_cache:
                        cache[key] = features
                timing.cheap_feature_ms += (perf_counter() - feature_started) * 1000
                decision = trigger(features)
                if decision.triggered and features.challenger_action is not None:
                    account.triggers += 1
                    outcome = evaluate_rollout(model, state, lt, features.challenger_action,
                                               account, decision_started=feature_started)
                    timing.completion_ms += outcome.runtime_ms
                    selected = outcome.selected_action
                    improvements += int(outcome.improved)
                    if outcome.fallback_reason:
                        fallback_count += 1
                        if outcome.fallback_reason not in fallback_reasons:
                            fallback_reasons.append(outcome.fallback_reason)
            elif summary.kind == "candidate_choice":
                reason = "total_time_limit" if total_expired else "trigger_limit"
                account.note(reason)  # type: ignore[arg-type]
                fallback_count += 1
                if reason not in fallback_reasons:
                    fallback_reasons.append(reason)
            action = Action.run(selected)
            previous_eligible = set(eligible)
        actions.append(action)
        state = model.step(state, action).after
    result = solver._result(model, actions)
    return replace(
        result,
        runtime_ms=(perf_counter() - started) * 1000,
        expanded_nodes=account.expansions,
        evaluated_candidates=account.completion_calls,
        fallback_count=fallback_count,
        fallback_reasons=tuple(fallback_reasons),
        planner_decisions=decisions,
        planner_triggered=account.triggers,
        planner_improvements=improvements,
        completion_calls=account.completion_calls,
        choice_gate_ms=timing.choice_gate_ms,
        cheap_feature_ms=timing.cheap_feature_ms,
        expensive_feature_ms=timing.expensive_feature_ms,
        candidate_generation_ms=timing.candidate_generation_ms,
        completion_ms=timing.completion_ms,
    )
