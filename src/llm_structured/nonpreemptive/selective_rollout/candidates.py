"""Stable, deduplicated and bounded legal complete-action candidates."""

from __future__ import annotations

from .baseline import longest_tail_action


def generate(adapter, state, mode, max_candidates):
    legal = tuple(adapter.legal_actions(state, mode))
    base = longest_tail_action(adapter, state, mode)
    if max_candidates == 0:
        return (base,), len(legal), True
    tails = adapter.tail(state)
    if adapter.resource_model == "single_channel":
        starts = [a for a in legal if a.kind != "wait"]
        fifo = min(starts, key=lambda a: adapter.model.index[a.task_id]) if starts else None
        spt = min(starts, key=lambda a: (adapter.duration(state, a), a.task_id)) if starts else None
        lpt = max(starts, key=lambda a: (adapter.duration(state, a), a.task_id)) if starts else None
        ordered = [base, fifo, spt, lpt, *legal]
    else:
        starts = [a for a in legal if a.kind != "wait"]
        fifo = max(starts, key=lambda a: (-sum(adapter.model.index[x] for x in a.starts), len(a.starts), a.starts)) if starts else None
        spt = min(starts, key=lambda a: (sum(adapter.model.remaining(state, adapter.model.index[x]) for x in a.starts), a.starts)) if starts else None
        ordered = [base, fifo, spt, *legal]
    unique = []
    for action in ordered:
        if action is not None and action not in unique:
            unique.append(action)
    limited = unique[:max(1, max_candidates)]
    if base not in limited:
        limited[-1] = base
    return tuple(limited), len(unique), len(limited) < len(unique)

