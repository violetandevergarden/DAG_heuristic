"""Independent cheap first-action policies over the complete legal action space."""

from __future__ import annotations


def preferences(adapter, state, mode):
    legal = tuple(adapter.legal_actions(state, mode))
    starts = tuple(action for action in legal if action.kind != "wait")
    if not starts:
        return {name: legal[0] for name in ("lt", "fifo", "fixed", "spt", "lpt")}
    tails = adapter.tail(state)
    index = adapter.model.index
    if adapter.resource_model == "single_channel":
        mapping = {
            "fifo": min(starts, key=lambda a: (index[a.task_id], a.task_id)),
            "fixed": min(starts, key=lambda a: (index[a.task_id], a.task_id)),
            "spt": min(starts, key=lambda a: (adapter.duration(state, a), a.task_id)),
            "lpt": max(starts, key=lambda a: (adapter.duration(state, a), a.task_id)),
            "release_fit": min(starts, key=lambda a: (max(0, adapter.duration(state, a) - adapter.next_event_distance(state)), -tails[a.task_id], a.task_id)),
        }
    else:
        action_tail = lambda a: sum(tails[item] for item in a.starts)
        mapping = {
            "fifo": min(starts, key=lambda a: (tuple(index[item] for item in a.starts), a.starts)),
            "fixed": min(starts, key=lambda a: (tuple(index[item] for item in a.starts), a.starts)),
            "spt": min(starts, key=lambda a: (adapter.duration(state, a), a.starts)),
            "lpt": max(starts, key=lambda a: (adapter.duration(state, a), a.starts)),
            "hotspot": max(starts, key=lambda a: (adapter.resource_coverage(a), action_tail(a), len(a.starts), a.starts)),
        }
    from .baseline import longest_tail_action
    mapping["lt"] = longest_tail_action(adapter, state, mode)
    return mapping
