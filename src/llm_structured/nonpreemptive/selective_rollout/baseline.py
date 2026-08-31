"""Frozen residual Longest Tail completion policy (version 1)."""

from __future__ import annotations


def longest_tail_action(adapter, state, mode):
    legal = adapter.legal_actions(state, mode)
    if not legal:
        raise RuntimeError("unfinished state has no legal action")
    starts = [action for action in legal if action.kind != "wait"]
    if not starts:
        return legal[0]
    tails = adapter.tail(state)
    if adapter.resource_model == "single_channel":
        selected = max(starts, key=lambda a: (tails[a.task_id], a.task_id))
        if mode == "optional_idle" and adapter.model.active_computes(state):
            next_event = min(adapter.model.task_runtime(state, item).remaining for item in adapter.model.active_computes(state))
            selected_duration = adapter.model.tasks[adapter.model.index[selected.task_id]].duration
            for compute in adapter.model.active_computes(state):
                index = adapter.model.index[compute]
                if adapter.model.task_runtime(state, compute).remaining != next_event:
                    continue
                if any(tails[adapter.model.tasks[child].task_id] > tails[selected.task_id] for child, parents in enumerate(adapter.model.deps) if index in parents) and next_event < selected_duration:
                    return next(action for action in legal if action.kind == "wait")
        return selected
    selected = max(
        starts,
        key=lambda a: (sum(tails[x] for x in a.starts), len(a.starts), a.starts),
    )
    if mode == "optional_idle" and adapter.model.active_computes(state):
        next_event = min(state.tasks[adapter.model.index[item]].remaining for item in adapter.model.active_computes(state))
        if next_event < min(adapter.model.remaining(state, adapter.model.index[item]) for item in selected.starts):
            return next(action for action in legal if action.kind == "wait")
    return selected


def complete(adapter, state, mode):
    actions = []
    start = state.time
    while not adapter.is_finished(state):
        action = longest_tail_action(adapter, state, mode)
        actions.append(action)
        state = adapter.step(state, action).after
    return state.time - start, tuple(actions)
