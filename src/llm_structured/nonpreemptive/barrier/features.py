"""Residual barrier features. Exact transitions always go through the public simulator."""

from __future__ import annotations

from .contracts import ActionFeatures, BarrierBudget, BarrierConfig


def action_features(adapter, graph, state, action, config: BarrierConfig, budget: BarrierBudget, context=None) -> ActionFeatures:
    signature = adapter.signature(state, action)
    selected = signature.task_ids
    context = context or adapter.decision_context(state, config.mode)
    tails = context.tails
    tail = max((tails[item] for item in selected), default=0)
    duration = adapter.duration(state, action)
    last_missing = set(); downstream_barriers = set(); descendants = set(); visits = 0; truncated = False
    selected_set = set(selected)
    for task_id in selected:
        downstream_barriers.update(graph.nearest_barriers.get(task_id, ()))
        stack = list(graph.children.get(task_id, ()))
        while stack:
            item = stack.pop()
            if item in descendants: continue
            if not budget.reserve("descendant_visits", config.max_descendant_visits): truncated = True; break
            visits += 1; descendants.add(item); stack.extend(graph.children.get(item, ()))
        for barrier in graph.barriers:
            parents = graph.parents[barrier]
            unfinished = {p for p in parents if _status(adapter, state, p) != "completed"}
            if unfinished == {task_id}:
                last_missing.add(barrier)
    immediate = set()
    if budget.reserve("feature_transitions", config.max_feature_transitions):
        before = {_task_id(adapter, i) for i, rt in enumerate(state.tasks) if rt.status == "pending"}
        transition = context.transition_cache.get(signature)
        if transition is None:
            transition = adapter.step(state, action)
            context.transition_cache[signature] = transition
        after_state = transition.after
        after = {_task_id(adapter, i) for i, rt in enumerate(after_state.tasks) if rt.status == "pending"}
        immediate = before - after - selected_set
    else:
        truncated = True
    resource_union = set(); excluded = set()
    if adapter.resource_model == "single_channel":
        resource_union.add("channel:0")
        excluded.update(a.task_id for a in context.legal_actions if a.kind == "flow" and a.task_id not in selected_set)
    else:
        for task_id in selected: resource_union.update(map(str, adapter.model.resources[adapter.model.index[task_id]]))
        for task_id in adapter.model.ready_flows(state):
            if task_id not in selected_set and resource_union & set(map(str, adapter.model.resources[adapter.model.index[task_id]])):
                excluded.add(task_id)
    member_descendant_count = len(descendants)
    barrier_tail = max((tails.get(item, 0) for item in downstream_barriers), default=0)
    return ActionFeatures(signature, tail, duration, tuple(sorted(last_missing)), tuple(sorted(immediate)),
                          tuple(sorted(downstream_barriers)), barrier_tail, tuple(sorted(descendants)),
                          max(0, member_descendant_count - len(descendants)), tuple(sorted(resource_union)), tuple(sorted(excluded)),
                          {"tail": "state_exact", "duration": "state_exact", "direct_last_missing": "structural_exact",
                           "immediate_release": "transition_exact", "downstream_barrier_tail": "heuristic_estimate"}, truncated)


def _task_id(adapter, index): return adapter.model.tasks[index].task_id
def _status(adapter, state, task_id): return state.tasks[adapter.model.index[task_id]].status
def _reachable(children, root):
    result=set(); stack=list(children.get(root, ()))
    while stack:
        item=stack.pop()
        if item in result: continue
        result.add(item); stack.extend(children.get(item, ()))
    return result
