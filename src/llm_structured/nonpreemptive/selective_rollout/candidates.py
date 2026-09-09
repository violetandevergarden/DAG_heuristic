"""Stable, deduplicated and bounded legal complete-action candidates."""

from __future__ import annotations

from llm_structured.nonpreemptive.baseline.solver import baseline_action

from ..baseline.solver import longest_tail_action


def generate(adapter, state, mode, max_candidates, candidate_mode="full_cross_job", context=None):
    context = context or adapter.decision_context(state, mode)
    legal = context.legal_actions
    base = longest_tail_action(adapter, state, mode, context)
    if max_candidates == 0:
        return (base,), len(legal), True
    # The revised Stage 4d experiment excludes fixed-resource graphs, but the
    # generic API retains its prior legal-set candidates for compatibility.
    if adapter.resource_model != "single_channel":
        starts = [a for a in legal if a.kind != "wait"]
        fifo = (
            max(
                starts,
                key=lambda a: (
                    -sum(adapter.model.index[x] for x in a.starts),
                    len(a.starts),
                    a.starts,
                ),
            )
            if starts
            else None
        )
        spt = (
            min(
                starts,
                key=lambda a: (
                    sum(adapter.model.remaining(state, adapter.model.index[x]) for x in a.starts),
                    a.starts,
                ),
            )
            if starts
            else None
        )
        ordered = [base, fifo, spt, *legal]
    else:
        starts = [a for a in legal if a.kind != "wait"]
        if base.kind == "wait" or len(starts) < 2:
            return (base,), len(legal), len(legal) > 1
        tails = context.tails
        ranked = sorted(starts, key=lambda a: (-tails[a.task_id], a.task_id))
        base_job = adapter.job_index.job_of(base.task_id)
        second = next((action for action in ranked if action != base), None)
        proposed = [base, second]
        if candidate_mode == "full_cross_job":
            for policy in ("shortest_remaining_job", "fifo", "job_aware_longest_tail"):
                action = baseline_action(adapter, state, mode, policy, context=context)
                if action.kind != "wait" and adapter.job_index.job_of(action.task_id) != base_job:
                    proposed.append(action)
        ordered = proposed
    unique = []
    for action in ordered:
        if action is not None and action not in unique:
            unique.append(action)
    limited = (
        unique[: min(3, max(1, max_candidates))]
        if adapter.resource_model == "single_channel"
        else unique[: max(1, max_candidates)]
    )
    if base not in limited:
        limited[-1] = base
    return tuple(limited), len(unique), len(limited) < len(unique)
