"""Versioned contracts for Stage 4d selective rollout."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from llm_structured.nonpreemptive.baseline.contracts import ActionSignature, Mode

TriggerKind = Literal[
    "none", "full", "selective", "strict", "loose", "disagreement", "legacy", "random", "periodic"
]


@dataclass(frozen=True)
class RolloutConfig:
    mode: Mode = "optional_idle"
    trigger: TriggerKind = "selective"
    search_depth: int = 1
    max_candidates_per_decision: int = 2
    candidate_mode: Literal["lt_top_two", "full_cross_job"] = "full_cross_job"
    max_triggered_decisions: int = 64
    max_completion_calls: int = 256
    max_expanded_decision_states: int = 1024
    max_feature_transitions: int = 256
    max_cache_entries: int = 2048
    per_decision_soft_time_s: float = 1.0
    per_instance_soft_time_s: float = 15.0
    random_seed: int = 0
    random_probability: float = 0.25
    periodic_interval: int = 4
    small_margin_ratio: float = 0.15
    min_duration_ratio: float | None = None
    duration_spread_ratio: float = 0.5
    release_tail_advantage_ratio: float = 0.15
    wait_ratio: float = 0.5
    feature_version: str = "np-stage4d-features-v2"
    candidate_version: str = "np-stage4d-candidates-v2"
    completion_version: str = "residual-lt-v1"

    def __post_init__(self) -> None:
        if self.search_depth < 0 or self.max_candidates_per_decision < 0:
            raise ValueError("depth and candidate width must be non-negative")
        for name in (
            "max_triggered_decisions",
            "max_completion_calls",
            "max_expanded_decision_states",
            "max_feature_transitions",
            "max_cache_entries",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.periodic_interval < 1:
            raise ValueError("periodic_interval must be positive")
        if not 0 <= self.random_probability <= 1:
            raise ValueError("random_probability must be in [0, 1]")
        if self.min_duration_ratio is not None and self.min_duration_ratio < 1:
            raise ValueError("min_duration_ratio must be at least one")


@dataclass
class BudgetLedger:
    triggered_decisions: int = 0
    completion_calls: int = 0
    expanded_decision_states: int = 0
    feature_transitions: int = 0
    evaluated_candidates: int = 0
    cache_hits: int = 0
    cache_writes: int = 0
    budget_rejections: int = 0

    def reserve(self, field_name: str, limit: int, amount: int = 1) -> bool:
        current = getattr(self, field_name)
        if current + amount > limit:
            self.budget_rejections += 1
            return False
        setattr(self, field_name, current + amount)
        return True


@dataclass(frozen=True)
class TriggerDecision:
    triggered: bool
    reasons: tuple[str, ...]
    score: float = 0.0
    budget_rejected: bool = False


@dataclass
class DecisionRecord:
    index: int
    time: int
    baseline: ActionSignature
    legal_action_count: int
    generated: tuple[ActionSignature, ...]
    evaluated: tuple[ActionSignature, ...] = ()
    values: dict[str, int] = field(default_factory=dict)
    trigger: TriggerDecision = field(default_factory=lambda: TriggerDecision(False, ()))
    selected: ActionSignature | None = None
    fallback_reason: str | None = None
    actual_depth: int = 0
    features: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RolloutResult:
    status: str
    makespan: int | None
    mode: Mode
    config: dict
    actions: tuple[ActionSignature, ...]
    decisions: tuple[dict, ...]
    metrics: dict
    trace_hash: str | None
    trace_valid: bool
    termination_reason: str | None = None

    @staticmethod
    def config_dict(config: RolloutConfig) -> dict:
        return asdict(config)
