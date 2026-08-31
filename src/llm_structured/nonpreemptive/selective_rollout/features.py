"""Cheap residual features and explicitly accounted transition features."""

from __future__ import annotations


def compute(adapter, state, candidates, ledger, config):
    tails = adapter.tail(state)
    action_tails = []
    durations = []
    signatures = []
    crosses_event = False
    for action in candidates:
        signatures.append(adapter.signature(state, action))
        durations.append(adapter.duration(state, action))
        ids = (() if action.kind == "wait" else ((action.task_id,) if hasattr(action, "task_id") else action.starts))
        action_tails.append(sum(tails.get(x, 0) for x in ids))
        if ledger.reserve("feature_transitions", config.max_feature_transitions):
            transition = adapter.step(state, action)
            event_count = len(getattr(transition, "events", ())) + len(getattr(transition, "completed", ()))
            crosses_event |= event_count > 1
    ranked = sorted(action_tails, reverse=True)
    margin = ranked[0] - ranked[1] if len(ranked) > 1 else None
    normalized_margin = margin / max(1, ranked[0]) if margin is not None else None
    spread = (max(durations) - min(durations)) / max(1, max(durations)) if len(durations) > 1 else 0.0
    return {
        "choice_count": len(candidates),
        "lt_margin": margin,
        "lt_margin_ratio": normalized_margin,
        "duration_spread_ratio": spread,
        "heuristic_disagreement": len(set(signatures[:3])) > 1,
        "crosses_event": crosses_event,
        "wait_available": any(s.kind == "wait" for s in signatures),
        "resource_footprints": [len(s.task_ids) for s in signatures],
    }

