"""Shared, policy-neutral contracts for budgeted selective rollout.

The types in this module do not advance a simulator and deliberately contain
no benchmark metadata.  Scenario-specific planners populate them exclusively
from the public residual state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol


BudgetReason = Literal[
    "candidate_limit",
    "trigger_limit",
    "completion_call_limit",
    "expansion_limit",
    "per_decision_time_limit",
    "total_time_limit",
]
ChoiceKind = Literal[
    "no_choice", "equivalent_choice", "candidate_choice", "enumeration_capped"
]


@dataclass(frozen=True)
class RolloutBudget:
    max_candidates: int = 2
    max_triggers: int = 8
    max_completion_calls: int = 16
    max_expansions: int = 100_000
    rollout_depth: int = 1
    per_decision_time_limit_s: float | None = 0.25
    total_time_limit_s: float | None = 2.0

    def __post_init__(self) -> None:
        for name in (
            "max_candidates", "max_triggers", "max_completion_calls", "max_expansions", "rollout_depth"
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        for name in ("per_decision_time_limit_s", "total_time_limit_s"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative or None")


@dataclass(frozen=True)
class ChoiceSummary:
    kind: ChoiceKind
    eligible_count: int
    action_count: int
    action_signatures: tuple[str, ...]


@dataclass(frozen=True)
class TriggerFeatures:
    feature_version: str
    eligible_count: int
    action_count: int
    lt_action: str
    challenger_action: str | None
    lt_tail: int
    second_tail: int | None
    tail_margin: int | None
    normalized_tail_margin: float | None
    heuristic_disagreement: bool
    active_communication_remaining: int
    ready_set_delta: int
    immediate_compute_release: bool
    last_missing_join: bool


@dataclass(frozen=True)
class TriggerDecision:
    triggered: bool
    reason: str
    confidence_or_score: float | None = None


class Trigger(Protocol):
    def __call__(self, features: TriggerFeatures) -> TriggerDecision: ...


@dataclass(frozen=True)
class EvaluationOutcome:
    selected_action: str
    lt_action: str
    challenger_action: str | None
    lt_value: int | None
    challenger_value: int | None
    improved: bool
    fallback_reason: str | None
    completion_calls: int
    expanded_states: int
    runtime_ms: float


@dataclass
class BudgetAccount:
    """Mutable accounting only; it never owns or advances simulator state."""

    budget: RolloutBudget
    triggers: int = 0
    completion_calls: int = 0
    expansions: int = 0
    exhausted_reasons: list[BudgetReason] = field(default_factory=list)

    def note(self, reason: BudgetReason) -> BudgetReason:
        if reason not in self.exhausted_reasons:
            self.exhausted_reasons.append(reason)
        return reason


def choice_only(features: TriggerFeatures) -> TriggerDecision:
    return TriggerDecision(features.action_count > 1, "choice_state")


def small_lt_margin(max_normalized_margin: float) -> Trigger:
    if max_normalized_margin < 0:
        raise ValueError("margin threshold must be non-negative")

    def decide(features: TriggerFeatures) -> TriggerDecision:
        margin = features.normalized_tail_margin
        triggered = margin is not None and margin <= max_normalized_margin
        return TriggerDecision(triggered, "small_lt_margin", margin)

    return decide


def heuristic_disagreement(features: TriggerFeatures) -> TriggerDecision:
    return TriggerDecision(features.heuristic_disagreement, "heuristic_disagreement")


def unlock_and_small_margin(max_normalized_margin: float) -> Trigger:
    margin_trigger = small_lt_margin(max_normalized_margin)

    def decide(features: TriggerFeatures) -> TriggerDecision:
        margin = margin_trigger(features)
        return TriggerDecision(
            features.immediate_compute_release and margin.triggered,
            "unlock_and_small_margin",
            margin.confidence_or_score,
        )

    return decide


def last_missing_and_small_margin(max_normalized_margin: float) -> Trigger:
    margin_trigger = small_lt_margin(max_normalized_margin)

    def decide(features: TriggerFeatures) -> TriggerDecision:
        margin = margin_trigger(features)
        return TriggerDecision(
            features.last_missing_join and margin.triggered,
            "last_missing_and_small_margin",
            margin.confidence_or_score,
        )

    return decide
