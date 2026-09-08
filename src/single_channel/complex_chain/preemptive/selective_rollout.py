"""Stage 4d selective rollout for the public single-channel simulator.

The implementation separates the LT baseline, bounded candidate generation,
triggering, and evaluation.  Search depth is a real branching decision depth;
every branch uses :class:`PreeSingleModel` for state transitions.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from time import perf_counter

from core.dag import DAG
from core.execution.preemptive import Action, PreeSingleModel, ScheduleState
from llm_structured.selective_rollout import (
    BudgetAccount, CandidateSummary, ChoiceSummary, EvaluationOutcome,
    RolloutBudget, Trigger, TriggerFeatures, choice_only,
)
from single_channel.complex_chain.preemptive import solver

FEATURE_VERSION = "single-channel-selective-v2"


@dataclass
class TimingAudit:
    choice_gate_ms: float = 0.0
    cheap_feature_ms: float = 0.0
    candidate_generation_ms: float = 0.0
    completion_ms: float = 0.0


def feature_cache_key(
    state: ScheduleState, previous_eligible: set[str] | frozenset[str] | tuple[str, ...]
) -> tuple[object, str, tuple[str, ...]]:
    """Include the history input used by ``eligible_comm_delta``."""

    return (
        solver.normalized_state_key(state), FEATURE_VERSION,
        tuple(sorted(previous_eligible)),
    )


def summarize_choice(model: PreeSingleModel, state: ScheduleState) -> ChoiceSummary:
    eligible = model.eligible_communications(state)
    if len(eligible) <= 1:
        kind = "no_choice"
    else:
        children = tuple(
            solver.normalized_state_key(model.step(state, Action.run(item)).after)
            for item in eligible
        )
        kind = "equivalent_choice" if len(set(children)) == 1 else "candidate_choice"
    return ChoiceSummary(kind, len(eligible), len(eligible), tuple(eligible))


def _ranked(model: PreeSingleModel, state: ScheduleState, mode: str) -> tuple[str, ...]:
    eligible = model.eligible_communications(state)
    tails = solver.residual_tail(model, state, eligible)
    return tuple(sorted(
        eligible,
        key=lambda item: solver._priority_key(model, state, item, mode, tails),
    ))


def generate_candidates(
    model: PreeSingleModel,
    state: ScheduleState,
    limit: int,
) -> CandidateSummary:
    """Return a stable, de-duplicated list that always starts with LT."""

    eligible = model.eligible_communications(state)
    if not eligible:
        raise ValueError("candidate generation requires eligible communication")
    lt_order = _ranked(model, state, "longest_tail")
    lrpt_order = _ranked(model, state, "lrpt")
    join_order = _ranked(model, state, "join_aware")
    fifo_order = tuple(eligible)
    source_rows = (
        ("longest_tail", lt_order), ("lrpt", lrpt_order),
        ("fifo", fifo_order), ("join_aware", join_order),
    )
    ordered: list[str] = []
    sources: dict[str, list[str]] = {}
    for source, ranking in source_rows:
        if not ranking:
            continue
        first = ranking[0]
        sources.setdefault(first, []).append(source)
        if first not in ordered:
            ordered.append(first)
    for item in lt_order:
        sources.setdefault(item, []).append("lt_rank_fill")
        if item not in ordered:
            ordered.append(item)
    retained = tuple(ordered[:limit]) if limit > 0 else ()
    return CandidateSummary(
        baseline=lt_order[0],
        candidates=retained,
        sources=tuple((item, tuple(sources[item])) for item in retained),
        available_action_count=len(eligible),
        retained_count=len(retained),
        truncated=len(retained) < len(ordered),
        truncation_reason="candidate_limit" if len(retained) < len(ordered) else None,
    )


def cheap_features(
    model: PreeSingleModel,
    state: ScheduleState,
    *,
    candidates: CandidateSummary | None = None,
    eligible_comm_delta: int = 0,
) -> TriggerFeatures:
    eligible = model.eligible_communications(state)
    if not eligible:
        raise ValueError("cheap features require an eligible communication")
    candidates = candidates or generate_candidates(model, state, len(eligible))
    lt = candidates.baseline
    challenger = next((item for item in candidates.candidates if item != lt), None)
    tails = solver.residual_tail(model, state, eligible)
    exclusive = {
        item: tails[item] - solver._own_remaining(model, state, item)
        for item in eligible
    }
    ordered_values = sorted(exclusive.values(), reverse=True)
    margin = ordered_values[0] - ordered_values[1] if len(ordered_values) > 1 else None
    normalizer = max(ordered_values[0], 1)
    active_remaining = (
        solver._own_remaining(model, state, state.last_communication)
        if state.last_communication in eligible else 0
    )
    lrpt = _ranked(model, state, "lrpt")[0]
    fifo = eligible[0]
    baseline_release = solver.immediate_compute_delay(model, state, lt)
    challenger_release = (
        solver.immediate_compute_delay(model, state, challenger)
        if challenger is not None else 0
    )
    baseline_join = solver.direct_last_blocker_gain(model, state, lt, tails) > 0
    challenger_join = (
        solver.direct_last_blocker_gain(model, state, challenger, tails) > 0
        if challenger is not None else False
    )
    return TriggerFeatures(
        feature_version=FEATURE_VERSION,
        eligible_count=len(eligible),
        action_count=len(eligible),
        lt_action=lt,
        challenger_action=challenger,
        lrpt_action=lrpt,
        fifo_action=fifo,
        lt_tail=exclusive[lt],
        second_tail=ordered_values[1] if len(ordered_values) > 1 else None,
        tail_margin=margin,
        normalized_tail_margin=None if margin is None else margin / normalizer,
        heuristic_disagreement=lrpt != lt,
        active_communication_remaining=active_remaining,
        eligible_comm_delta=eligible_comm_delta,
        baseline_compute_release=baseline_release,
        challenger_compute_release=challenger_release,
        compute_release_delta=challenger_release - baseline_release,
        baseline_last_missing_join=baseline_join,
        challenger_last_missing_join=challenger_join,
        last_missing_join_difference=baseline_join != challenger_join,
    )


def _forced_idle(
    model: PreeSingleModel,
    state: ScheduleState,
    account: BudgetAccount,
    decision_started: float,
) -> tuple[ScheduleState, str | None]:
    current = state
    while not model.is_finished(current) and not model.eligible_communications(current):
        reason = account.try_expand(decision_started)
        if reason is not None:
            return current, reason
        current = model.step(current, Action.wait()).after
    return current, None


def _terminal_lt_completion(
    model: PreeSingleModel,
    state: ScheduleState,
    account: BudgetAccount,
    decision_started: float,
) -> tuple[int | None, str | None]:
    reason = account.try_reserve_completion(decision_started)
    if reason is not None:
        return None, reason
    current = state
    while not model.is_finished(current):
        reason = account.try_expand(decision_started)
        if reason is not None:
            return None, reason
        eligible = model.eligible_communications(current)
        action = (
            Action.run(solver._baseline_choice(model, current, "longest_tail"))
            if eligible else Action.wait()
        )
        current = model.step(current, action).after
    return current.time, None


def _tree_value(
    model: PreeSingleModel,
    state: ScheduleState,
    remaining_depth: int,
    account: BudgetAccount,
    decision_started: float,
    width: int,
    depth_used: int,
) -> tuple[int | None, int, str | None]:
    current, reason = _forced_idle(model, state, account, decision_started)
    if reason is not None:
        return None, depth_used, reason
    if model.is_finished(current):
        return current.time, depth_used, None
    if remaining_depth <= 0:
        value, reason = _terminal_lt_completion(model, current, account, decision_started)
        return value, depth_used, reason
    summary = generate_candidates(model, current, width)
    account.generated_candidates += summary.retained_count
    best: int | None = None
    reached = depth_used
    for item in summary.candidates:
        reason = account.try_expand(decision_started)
        if reason is not None:
            return None, reached, reason
        after = model.step(current, Action.run(item)).after
        value, child_depth, reason = _tree_value(
            model, after, remaining_depth - 1, account, decision_started,
            width, depth_used + 1,
        )
        reached = max(reached, child_depth)
        if reason is not None or value is None:
            return None, reached, reason or "incomplete_evaluation"
        best = value if best is None else min(best, value)
    return best, reached, None


def evaluate_rollout(
    model: PreeSingleModel,
    state: ScheduleState,
    candidates: CandidateSummary,
    account: BudgetAccount,
    *,
    decision_started: float,
) -> EvaluationOutcome:
    """Evaluate a bounded width/depth tree; incomplete trees always use LT."""

    started = perf_counter()
    calls_before = account.completion_calls
    expansions_before = account.expansions
    evaluated_before = account.evaluated_candidates
    baseline = candidates.baseline
    if account.budget.search_depth == 0:
        return EvaluationOutcome(
            baseline, baseline, (), False, True, "search_depth_zero", 0, 0, 0, 0, 0.0,
        )
    if len(candidates.candidates) < 2:
        return EvaluationOutcome(
            baseline, baseline, (), False, True, "no_distinct_challenger",
            0, 0, 0, 0, 0.0,
        )
    values: list[tuple[str, int]] = []
    actual_depth = 0
    for item in candidates.candidates:
        reason = account.try_expand(decision_started)
        if reason is not None:
            return EvaluationOutcome(
                baseline, baseline, tuple(values), False, False, reason,
                account.completion_calls - calls_before,
                account.expansions - expansions_before,
                account.evaluated_candidates - evaluated_before,
                actual_depth, (perf_counter() - started) * 1000,
            )
        after = model.step(state, Action.run(item)).after
        value, reached, reason = _tree_value(
            model, after, account.budget.search_depth - 1, account,
            decision_started, account.budget.max_candidates, 1,
        )
        actual_depth = max(actual_depth, reached)
        if reason is not None or value is None:
            return EvaluationOutcome(
                baseline, baseline, tuple(values), False, False,
                reason or "incomplete_evaluation",
                account.completion_calls - calls_before,
                account.expansions - expansions_before,
                account.evaluated_candidates - evaluated_before,
                actual_depth, (perf_counter() - started) * 1000,
            )
        account.evaluated_candidates += 1
        values.append((item, value))
    baseline_value = dict(values)[baseline]
    best_value = min(value for _, value in values)
    selected = baseline
    if best_value < baseline_value:
        selected = min(item for item, value in values if value == best_value)
    improved = selected != baseline
    account.completed_evaluations += 1
    account.max_actual_depth = max(account.max_actual_depth, actual_depth)
    return EvaluationOutcome(
        selected, baseline, tuple(values), improved, True,
        None if improved else "candidate_not_strictly_better",
        account.completion_calls - calls_before,
        account.expansions - expansions_before,
        account.evaluated_candidates - evaluated_before,
        actual_depth, (perf_counter() - started) * 1000,
    )


def schedule_selective_rollout(
    dag: DAG,
    *,
    budget: RolloutBudget | None = None,
    trigger: Trigger = choice_only,
    use_cache: bool = True,
):
    solver.validate_complex_chain(dag)
    budget = budget or RolloutBudget()
    if budget.search_depth == 0 or budget.max_candidates < 2:
        return solver.schedule_longest_tail(dag)
    model = PreeSingleModel(dag)
    state = model.initial_state()
    actions: list[Action] = []
    account = BudgetAccount(budget)
    timing = TimingAudit()
    cache: dict[tuple[object, str, tuple[str, ...]], TriggerFeatures] = {}
    started = account.started
    decisions = improvements = fallback_count = cache_hits = 0
    fallback_reasons: list[str] = []
    fallback_details: list[str] = []
    trigger_reasons: Counter[str] = Counter()
    previous_eligible: set[str] = set()
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        if not eligible:
            action = Action.wait()  # public model's forced-idle compatibility action
        else:
            decisions += 1
            gate_started = perf_counter()
            summary = summarize_choice(model, state)
            timing.choice_gate_ms += (perf_counter() - gate_started) * 1000
            baseline = solver._baseline_choice(model, state, "longest_tail")
            selected = baseline
            if summary.kind == "candidate_choice":
                candidate_started = perf_counter()
                candidates = generate_candidates(model, state, budget.max_candidates)
                account.generated_candidates += candidates.retained_count
                timing.candidate_generation_ms += (perf_counter() - candidate_started) * 1000
                feature_started = perf_counter()
                key = feature_cache_key(state, previous_eligible)
                features = cache.get(key) if use_cache else None
                if features is None:
                    features = cheap_features(
                        model, state, candidates=candidates,
                        eligible_comm_delta=len(set(eligible) - previous_eligible),
                    )
                    if use_cache:
                        cache[key] = features
                else:
                    cache_hits += 1
                timing.cheap_feature_ms += (perf_counter() - feature_started) * 1000
                decision = trigger(features)
                trigger_reasons[decision.reason] += int(decision.triggered)
                if decision.triggered:
                    reason = account.try_reserve_trigger(feature_started)
                    if reason is not None:
                        fallback_count += 1
                        fallback_reasons.append(reason)
                        fallback_details.append(f"decision={decisions}:{reason}")
                    else:
                        outcome = evaluate_rollout(
                            model, state, candidates, account,
                            decision_started=feature_started,
                        )
                        timing.completion_ms += outcome.runtime_ms
                        selected = outcome.selected_action
                        improvements += int(outcome.improved)
                        if not outcome.complete:
                            account.budget_rejected_triggers += 1
                        if outcome.fallback_reason and outcome.fallback_reason != "candidate_not_strictly_better":
                            fallback_count += 1
                            fallback_reasons.append(outcome.fallback_reason)
                            fallback_details.append(
                                f"decision={decisions}:{outcome.fallback_reason}"
                            )
            action = Action.run(selected)
            previous_eligible = set(eligible)
        actions.append(action)
        state = model.step(state, action).after
    result = solver._result(model, actions)
    return result.with_stats(
        runtime_ms=(perf_counter() - started) * 1000,
        expanded_nodes=account.expansions,
        evaluated_candidates=account.evaluated_candidates,
        fallback_count=fallback_count,
        fallback_reasons=tuple(dict.fromkeys(fallback_reasons)),
        planner_decisions=decisions,
        planner_triggered=account.trigger_positives,
        planner_improvements=improvements,
        completion_calls=account.completion_calls,
        choice_gate_ms=timing.choice_gate_ms,
        cheap_feature_ms=timing.cheap_feature_ms,
        candidate_generation_ms=timing.candidate_generation_ms,
        completion_ms=timing.completion_ms,
        trigger_positives=account.trigger_positives,
        completed_rollout_evaluations=account.completed_evaluations,
        budget_rejected_triggers=account.budget_rejected_triggers,
        generated_candidates=account.generated_candidates,
        max_actual_depth=account.max_actual_depth,
        cache_hits=cache_hits,
        trigger_reason_counts=tuple(sorted(trigger_reasons.items())),
        fallback_details=tuple(fallback_details),
    )
