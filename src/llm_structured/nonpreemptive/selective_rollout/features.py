"""Version 2 cheap and one-transition features for effective selective rollout."""

from __future__ import annotations

from .cheap_policies import preferences


def compute(adapter, state, candidates, ledger, config):
    tails = adapter.tail(state)
    policy_actions = preferences(adapter, state, config.mode)
    policy_signatures = {name: adapter.signature(state, action) for name, action in policy_actions.items()}
    baseline = policy_actions["lt"]
    baseline_signature = policy_signatures["lt"]
    starts = tuple(action for action in adapter.legal_actions(state, config.mode) if action.kind != "wait")
    start_tails = []
    for action in starts:
        ids = (action.task_id,) if hasattr(action, "task_id") else action.starts
        start_tails.append(max((tails[item] for item in ids), default=0))
    ranked = sorted(start_tails, reverse=True)
    margin = ranked[0] - ranked[1] if len(ranked) > 1 else None
    normalized_margin = margin / max(1, ranked[0]) if margin is not None else None
    durations = [adapter.duration(state, action) for action in starts]
    duration_spread = ((max(durations) - min(durations)) / max(1, max(durations)) if len(durations) > 1 else 0.0)
    before_ready = adapter.ready_flow_ids(state)
    transitions = {}
    release_metrics = {}
    for action in candidates:
        signature = adapter.signature(state, action)
        if not ledger.reserve("feature_transitions", config.max_feature_transitions):
            continue
        transition = adapter.step(state, action)
        transitions[signature] = transition
        released = adapter.ready_flow_ids(transition.after) - before_ready
        competing = tuple(item for item in released if _task_resources(adapter, item) & adapter.resources(action))
        after_tails = adapter.tail(transition.after)
        release_tail = max((after_tails.get(item, 0) for item in competing), default=0)
        current_ids = (() if action.kind == "wait" else ((action.task_id,) if hasattr(action, "task_id") else action.starts))
        current_tail = max((tails.get(item, 0) for item in current_ids), default=0)
        release_metrics[signature] = {"released": tuple(sorted(released)), "competing": tuple(sorted(competing)), "release_tail": release_tail, "current_tail": current_tail, "advance": transition.after.time - state.time}
    base_metric = release_metrics.get(baseline_signature, {})
    gain_values = [value.get("release_tail", 0) for value in release_metrics.values()]
    gain_spread = max(gain_values, default=0) - min(gain_values, default=0)
    candidate_duration = adapter.duration(state, baseline)
    next_event = adapter.next_event_distance(state)
    release_advantage = base_metric.get("release_tail", 0) - base_metric.get("current_tail", 0)
    wait_available = any(action.kind == "wait" for action in adapter.legal_actions(state, config.mode))
    resource_sets = [adapter.resources(action) for action in candidates if action.kind != "wait"]
    resource_spread = any(left != right for left in resource_sets for right in resource_sets)
    return {
        "choice_count": len(candidates), "lt_margin": margin, "lt_margin_ratio": normalized_margin,
        "duration_spread_ratio": duration_spread, "policy_actions": policy_signatures,
        "true_policy_disagreement": any(sig != baseline_signature for sig in policy_signatures.values()),
        "critical_release_crossed": bool(next_event < candidate_duration and base_metric.get("competing") and base_metric.get("release_tail", 0) >= base_metric.get("current_tail", 0)),
        "release_gain_spread": gain_spread > 0, "release_gain_spread_value": gain_spread,
        "wait_opportunity": bool(config.mode == "optional_idle" and wait_available and next_event < candidate_duration and base_metric.get("competing") and release_advantage / max(1, base_metric.get("current_tail", 0)) >= config.release_tail_advantage_ratio and next_event / max(1, candidate_duration) <= config.wait_ratio),
        "resource_conflict_spread": resource_spread, "wait_available": wait_available,
        "next_event_distance": next_event, "selected_action_blocking_duration": candidate_duration,
        "release_metrics": release_metrics, "precomputed_transitions": transitions,
        "heuristic_disagreement": len({adapter.signature(state, x) for x in candidates[:3]}) > 1,
        "crosses_event": any(value["advance"] > 0 for value in release_metrics.values()),
    }


def _task_resources(adapter, task_id):
    if adapter.resource_model == "single_channel": return frozenset({"channel:0"})
    return frozenset(adapter.model.resources[adapter.model.index[task_id]])
