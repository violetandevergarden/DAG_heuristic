"""Residual vertex and whole-set union features."""

from __future__ import annotations

from muti_channel.nonpreemptive.solver import ResourceAction

from .contracts import DecisionBudget, SetFeatures


def set_features(model, state, action: ResourceAction, budget: DecisionBudget) -> SetFeatures:
    _paths, tails = model.residual_features(state)
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
    excluded = [x for x in model.startable_flows(state) if x not in selected and
                covered & model.resources[model.index[x]]]
    released = ()
    active_after = 0
    if action.kind == "start" or model.has_future_event(state):
        transition = model.step(state, action)
        before = set(model.ready_flows(state)); after = set(model.ready_flows(transition.after))
        released = tuple(sorted(after - before - selected))
        active_after = len(model.active_flows(transition.after))
    all_resources = {r for group in model.resources for r in group}
    return SetFeatures(
        frozenset(covered), len(reachable), released,
        max((tails[model.index[x]] for x in excluded), default=0),
        max((tails[model.index[x]] for x in selected), default=0),
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
