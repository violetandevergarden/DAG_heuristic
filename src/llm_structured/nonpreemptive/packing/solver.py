"""Online packing policy; all transitions remain owned by the public simulator."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from time import perf_counter

from core.execution.nonpreemptive import NonPreeMultiModel
from muti_channel.nonpreemptive.solver import complete
from muti_channel.nonpreemptive.replay import replay_actions

from .constructors import baseline_action, construct_candidates
from .contracts import DecisionBudget, PackingConfig, PackingDecision, PackingScheduleResult, build_decision_context
from .features import set_features, union_score


def choose_action(model, state, config: PackingConfig) -> PackingDecision:
    started = perf_counter(); budget = DecisionBudget(config.budget)
    context = build_decision_context(model, state)
    baseline = baseline_action(model, state, context=context)
    candidates = list(construct_candidates(model, state, config, budget, context))
    valid = []
    for candidate in candidates:
        try: model.validate_action(state, candidate.action, config.mode)
        except ValueError: continue
        valid.append(replace(candidate, features=set_features(model, state, candidate.action, budget, context)))
    selected = baseline
    if config.selector == "set_union" and valid:
        selected = min(valid, key=lambda x: (union_score(x.features), x.action != baseline, x.signature)).action
    elif config.selector == "completion" and valid:
        scored = []
        for candidate in valid:
            if perf_counter() - started > config.budget.decision_time_limit_s or not budget.reserve("completion_calls"):
                break
            transition = model.step(state, candidate.action)
            value = transition.after.time - state.time + complete(model, transition.after, "dynamic_tail")[0]
            scored.append((value, candidate.action != baseline, candidate.signature, candidate.action))
        if scored and len(scored) == len(valid): selected = min(scored, key=lambda x: x[:-1])[-1]
        elif scored: budget.exhausted_reasons.add("incomplete_completion_evaluation")
    fallback = bool(budget.exhausted_reasons)
    if "incomplete_completion_evaluation" in budget.exhausted_reasons: selected = baseline
    model.validate_action(state, selected, config.mode)
    return PackingDecision(baseline, selected, tuple(valid), fallback,
                           tuple(sorted(budget.exhausted_reasons)), budget.completion_calls,
                           context.cache_hits, context.cache_misses, context.cache_rejections)


def schedule_packing(instance, config: PackingConfig | None = None) -> PackingScheduleResult:
    config = config or PackingConfig()
    started = perf_counter(); model = NonPreeMultiModel(instance)
    state = model.initial_state(); actions = []; decisions = []; reasons = Counter()
    while not model.is_finished(state):
        decision = choose_action(model, state, config)
        decisions.append(decision); reasons.update(decision.fallback_reasons)
        actions.append(decision.selected); state = model.step(state, decision.selected).after
    elapsed = (perf_counter() - started) * 1000
    replay = replay_actions(model, actions, runtime_ms=elapsed)
    return PackingScheduleResult(
        replay.makespan, replay.actions, replay.intervals, elapsed, len(decisions),
        sum(len(x.candidates) for x in decisions), sum(x.completion_calls for x in decisions),
        sum(x.fallback for x in decisions), tuple(sorted(reasons.items())),
        replay.voluntary_waits, replay.voluntary_wait_time,
        replay.forced_waits, replay.forced_wait_time,
    )

