"""Residual vertex and whole-set union features."""

from __future__ import annotations

from core.execution.nonpreemptive import ResourceAction

from .contracts import DecisionBudget, PackingDecisionContext, SetFeatures, build_decision_context


def set_features(model, state, action: ResourceAction, budget: DecisionBudget, context: PackingDecisionContext | None = None) -> SetFeatures:
    context = context or build_decision_context(model, state)
    tails = context.tails
    selected = set(action.starts)
    covered = set(); reachable = set(); durations = []
    stack = [model.index[x] for x in selected]
    while stack and budget.reserve("feature_nodes"):
        index = stack.pop()
        if index in reachable: continue
        reachable.add(index); stack.extend(model.children[index])
    for task_id in selected:
        index = model.index[task_id]
        covered.update(model.resources[index]); durations.append(model.remaining(state, index))
    excluded = [x for x in context.startable if x not in selected and
                covered & model.resources[model.index[x]]]
    released = ()
    active_after = 0
    if action.kind == "start" or model.has_future_event(state):
        key = action.starts
        transition = context.transition_cache.get(key)
        if transition is None:
            transition = model.step(state, action)
            context.transition_cache[key] = transition
            context.cache_misses += 1
        else:
            context.cache_hits += 1
        before = set(model.ready_flows(state)); after = set(model.ready_flows(transition.after))
        released = tuple(sorted(after - before - selected))
        active_after = len(model.active_flows(transition.after))
    all_resources = context.all_resources
    return SetFeatures(
        frozenset(covered), len(reachable), released,
        max((tails[x] for x in excluded), default=0),
        max((tails[x] for x in selected), default=0),
        max(durations, default=0), max(durations, default=0)-min(durations, default=0),
        active_after, bool(selected) and model.is_maximal_start(state, selected),
        frozenset(all_resources - model.occupied_resources(state) - covered),
    )


def union_score(features: SetFeatures) -> tuple:
    return (
        -features.max_selected_tail,
        features.excluded_critical_tail,
        features.max_duration,
        -len(features.immediate_release_union),
        -features.reachable_union_size,
        len(features.left_idle_resources),
    )
