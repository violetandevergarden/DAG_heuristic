"""Frozen shared baseline policies, including the declared WAIT rule."""

from __future__ import annotations

from .contracts import Mode, PolicyName


def _rank(adapter, state, actions, policy: PolicyName, first_seen=None, tails=None):
    tails = adapter.tail(state) if tails is None else tails
    first_seen = first_seen or {}

    def key(action):
        ids = (action.task_id,) if adapter.resource_model == "single_channel" else action.starts
        if policy == "fifo":
            oldest = min(
                first_seen.get(item, (state.time, adapter.model.index[item])) for item in ids
            )
            return (-oldest[0], -oldest[1], ids)
        if policy == "fixed_order":
            return tuple(-adapter.model.index[item] for item in ids)
        durations = [
            adapter.model.remaining(state, adapter.model.index[item])
            if adapter.resource_model != "single_channel"
            else adapter.model.tasks[adapter.model.index[item]].duration
            for item in ids
        ]
        if policy == "spt":
            return (-sum(durations), ids)
        if policy == "lpt":
            return (sum(durations), ids)
        return (sum(tails[item] for item in ids), len(ids), ids)

    return max(actions, key=key)


def should_wait(adapter, state, selected, tails, active=None, next_event=None) -> bool:
    active = adapter.model.active_computes(state) if active is None else active
    if not active:
        return False
    next_event = (
        next_event
        if next_event is not None
        else (
            min(adapter.model.task_runtime(state, item).remaining for item in active)
            if adapter.resource_model == "single_channel"
            else min(state.tasks[adapter.model.index[item]].remaining for item in active)
        )
    )
    if adapter.resource_model != "single_channel":
        return next_event < min(
            adapter.model.remaining(state, adapter.model.index[item]) for item in selected.starts
        )
    duration = adapter.model.tasks[adapter.model.index[selected.task_id]].duration
    for compute in active:
        index = adapter.model.index[compute]
        if adapter.model.task_runtime(state, compute).remaining == next_event and any(
            tails[adapter.model.tasks[child].task_id] > tails[selected.task_id]
            for child, parents in enumerate(adapter.model.deps)
            if index in parents
        ):
            return next_event < duration
    return False


def baseline_action(
    adapter,
    state,
    mode: Mode,
    policy: PolicyName = "longest_tail",
    first_seen=None,
    context=None,
):
    context = context or adapter.decision_context(state, mode)
    legal = context.legal_actions
    if not legal:
        raise RuntimeError("unfinished state has no legal action")
    starts = [action for action in legal if action.kind != "wait"]
    if not starts:
        return legal[0]
    selected = _rank(adapter, state, starts, policy, first_seen, context.tails)
    if mode == "optional_idle" and should_wait(
        adapter,
        state,
        selected,
        context.tails,
        context.active_computes,
        context.next_event_distance,
    ):
        return next(action for action in legal if action.kind == "wait")
    return selected


def longest_tail_action(adapter, state, mode, context=None):
    return baseline_action(adapter, state, mode, "longest_tail", context=context)
