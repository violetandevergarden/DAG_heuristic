"""Transparent trigger policies used by Stage 4d."""

from __future__ import annotations

import random
from .contracts import TriggerDecision


def decide(kind, features, config, decision_index, rng: random.Random):
    if kind == "none": return TriggerDecision(False, ("disabled",))
    if features["choice_count"] < 2: return TriggerDecision(False, ("no_choice",))
    if kind == "full": return TriggerDecision(True, ("choice_exists",), 1.0)
    if kind == "random":
        hit = rng.random() < config.random_probability
        return TriggerDecision(hit, ("random_match",) if hit else ("random_skip",), config.random_probability)
    if kind == "periodic":
        hit = decision_index % config.periodic_interval == 0
        return TriggerDecision(hit, ("periodic_match",) if hit else ("periodic_skip",), 1.0 / config.periodic_interval)
    reasons = []
    margin = features["lt_margin_ratio"]
    if margin is not None and margin <= config.small_margin_ratio: reasons.append("small_lt_margin")
    if features["heuristic_disagreement"]: reasons.append("heuristic_disagreement")
    if features["crosses_event"]: reasons.append("crosses_event")
    if features["duration_spread_ratio"] >= config.duration_spread_ratio: reasons.append("duration_spread")
    if features["wait_available"] and margin is not None and margin <= config.small_margin_ratio: reasons.append("wait_competition")
    return TriggerDecision(bool(reasons), tuple(reasons), float(len(reasons)))

