"""Policy-neutral contracts for Stage 4d budgeted selective rollout.

This module owns no simulator state transition. Scenario-specific planners
use these records to keep baseline construction, candidate generation,
triggering, and rollout evaluation separate and auditable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Literal, Protocol


BudgetReason = Literal[
    "candidate_limit", "trigger_limit", "completion_call_limit",
    "expansion_limit", "per_decision_time_limit", "total_time_limit",
]
ChoiceKind = Literal[
    "no_choice", "equivalent_choice", "candidate_choice", "enumeration_capped"
]


@dataclass(frozen=True)
class RolloutBudget:
    """Hard counters and cooperative time limits.

    ``search_depth`` counts branching communication-decision layers. Depth
    zero disables rollout, depth one compares first actions followed by the
    terminal policy, and depth two branches once more before terminal
    completion. Terminal completion is not included in the depth count.
    """

    max_candidates: int = 2
    max_triggers: int = 8
    max_completion_calls: int = 16
    max_expansions: int = 100_000
    search_depth: int = 1
    per_decision_time_limit_s: float | None = 0.25
    total_time_limit_s: float | None = 2.0

    def __post_init__(self) -> None:
        for name in (
            "max_candidates", "max_triggers", "max_completion_calls",
            "max_expansions", "search_depth",
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
class CandidateSummary:
    baseline: str
    candidates: tuple[str, ...]
    sources: tuple[tuple[str, tuple[str, ...]], ...]
    available_action_count: int
    retained_count: int
    truncated: bool
    truncation_reason: str | None


@dataclass(frozen=True)
class TriggerFeatures:
    feature_version: str
    eligible_count: int
    action_count: int
    lt_action: str
    challenger_action: str | None
    lrpt_action: str
    fifo_action: str
    lt_tail: int
    second_tail: int | None
    tail_margin: int | None
    normalized_tail_margin: float | None
    heuristic_disagreement: bool
    active_communication_remaining: int
    eligible_comm_delta: int
    baseline_compute_release: int
    challenger_compute_release: int
    compute_release_delta: int
    baseline_last_missing_join: bool
    challenger_last_missing_join: bool
    last_missing_join_difference: bool

    @property
    def immediate_compute_release(self) -> bool:
        return self.compute_release_delta != 0

    @property
    def last_missing_join(self) -> bool:
        return self.last_missing_join_difference


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
    baseline_action: str
    candidate_values: tuple[tuple[str, int], ...]
    improved: bool
    complete: bool
    fallback_reason: str | None
    completion_calls: int
    expanded_states: int
    evaluated_candidates: int
    actual_depth: int
    runtime_ms: float


@dataclass
class BudgetAccount:
    """Shared atomic ledger for every branch of one complete schedule."""

    budget: RolloutBudget
    started: float = field(default_factory=perf_counter)
    trigger_positives: int = 0
    completed_evaluations: int = 0
    budget_rejected_triggers: int = 0
    completion_calls: int = 0
    expansions: int = 0
    generated_candidates: int = 0
    evaluated_candidates: int = 0
    max_actual_depth: int = 0
    exhausted_reasons: list[BudgetReason] = field(default_factory=list)

    def note(self, reason: BudgetReason) -> BudgetReason:
        if reason not in self.exhausted_reasons:
            self.exhausted_reasons.append(reason)
        return reason

    def time_reason(self, decision_started: float) -> BudgetReason | None:
        now = perf_counter()
        total = self.budget.total_time_limit_s
        if total is not None and now - self.started >= total:
            return self.note("total_time_limit")
        per_decision = self.budget.per_decision_time_limit_s
        if per_decision is not None and now - decision_started >= per_decision:
            return self.note("per_decision_time_limit")
        return None

    def try_reserve_trigger(self, decision_started: float) -> BudgetReason | None:
        reason = self.time_reason(decision_started)
        if reason is not None:
            self.budget_rejected_triggers += 1
            return reason
        if self.trigger_positives >= self.budget.max_triggers:
            self.budget_rejected_triggers += 1
            return self.note("trigger_limit")
        self.trigger_positives += 1
        return None

    def try_reserve_completion(self, decision_started: float) -> BudgetReason | None:
        reason = self.time_reason(decision_started)
        if reason is not None:
            return reason
        if self.completion_calls >= self.budget.max_completion_calls:
            return self.note("completion_call_limit")
        self.completion_calls += 1
        return None

    def try_expand(self, decision_started: float, count: int = 1) -> BudgetReason | None:
        if count < 0:
            raise ValueError("expansion count must be non-negative")
        reason = self.time_reason(decision_started)
        if reason is not None:
            return reason
        if self.expansions + count > self.budget.max_expansions:
            return self.note("expansion_limit")
        self.expansions += count
        return None


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
            features.compute_release_delta != 0 and margin.triggered,
            "unlock_and_small_margin", margin.confidence_or_score,
        )

    return decide


def last_missing_and_small_margin(max_normalized_margin: float) -> Trigger:
    margin_trigger = small_lt_margin(max_normalized_margin)

    def decide(features: TriggerFeatures) -> TriggerDecision:
        margin = margin_trigger(features)
        return TriggerDecision(
            features.last_missing_join_difference and margin.triggered,
            "last_missing_and_small_margin", margin.confidence_or_score,
        )

    return decide


