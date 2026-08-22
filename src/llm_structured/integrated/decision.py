"""Auditable records for integrated decisions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ComponentCost:
    feature_ms: float = 0.0
    packing_ms: float = 0.0
    search_ms: float = 0.0
    simulator_ms: float = 0.0


@dataclass(frozen=True)
class IntegratedDecision:
    time: int
    state_fingerprint: str
    eligible_ids: tuple[str, ...]
    baseline_action: tuple[str, ...]
    baseline_scores: tuple[tuple[str, tuple[object, ...]], ...]
    candidate_actions: tuple[tuple[str, ...], ...]
    constructor: str
    barrier_diagnostics_collected: bool
    search_complete: bool
    candidate_values: tuple[tuple[tuple[str, ...], float, float], ...]
    final_action: tuple[str, ...]
    changed_by: str | None
    fallback_reason: str | None
    completion_calls: int
    expansions: int
    cost: ComponentCost
