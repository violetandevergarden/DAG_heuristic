"""Transparent trigger policies used by Stage 4d."""

from __future__ import annotations

import random

from .contracts import TriggerDecision


def decide(kind, features, config, decision_index, rng: random.Random):
    if kind == "none":
        return TriggerDecision(False, ("disabled",))
    if features["choice_count"] < 2:
        return TriggerDecision(False, ("no_choice",))
    if kind == "full":
        return TriggerDecision(True, ("choice_exists",), 1.0)
    if kind == "random":
        hit = rng.random() < config.random_probability
        return TriggerDecision(
            hit, ("random_match",) if hit else ("random_skip",), config.random_probability
        )
    if kind == "periodic":
        hit = decision_index % config.periodic_interval == 0
        return TriggerDecision(
            hit, ("periodic_match",) if hit else ("periodic_skip",), 1.0 / config.periodic_interval
        )
    if kind == "disagreement":
        hit = features["true_policy_disagreement"]
        return TriggerDecision(
            hit, ("true_policy_disagreement",) if hit else ("policy_agreement",), float(hit)
        )
    if kind == "legacy":
        hit = features["heuristic_disagreement"] or features["crosses_event"]
        return TriggerDecision(
            hit, ("legacy_failed_trigger_v1",) if hit else ("legacy_skip",), float(hit)
        )
    if kind == "loose":
        margin = features["lt_margin_ratio"]
        small = margin is not None and margin <= config.small_margin_ratio
        hit = features["true_policy_disagreement"] or small
        return TriggerDecision(
            hit, ("small_margin_or_policy_disagreement",) if hit else ("loose_skip",), float(hit)
        )
    reasons = []
    margin = features["lt_margin_ratio"]
    duration_ok = (
        config.min_duration_ratio is None
        or features.get("top_duration_ratio", 1.0) >= config.min_duration_ratio
    )
    if margin is not None and margin <= config.small_margin_ratio and duration_ok:
        reasons.append("small_lt_margin")
    if kind == "selective":
        if features["true_policy_disagreement"]:
            reasons.append("true_policy_disagreement")
        return TriggerDecision(bool(reasons), tuple(reasons), float(len(reasons)))
    structural = []
    if (
        margin is not None
        and margin <= config.small_margin_ratio
        and features["critical_release_crossed"]
    ):
        structural.append("small_margin_and_critical_release")
    for name in ("release_gain_spread", "wait_opportunity", "resource_conflict_spread"):
        if features[name]:
            structural.append(name)
    hit = features["true_policy_disagreement"] and bool(structural)
    return TriggerDecision(
        hit,
        tuple((["true_policy_disagreement"] + structural) if hit else ("strict_gate_failed",)),
        float(hit),
    )
