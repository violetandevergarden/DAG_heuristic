"""Versioned contracts for non-preemptive barrier-aware scheduling."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from llm_structured.nonpreemptive.selective_rollout.contracts import ActionSignature, Mode

QuantityMode = Literal["state_exact", "transition_exact", "structural_exact", "heuristic_estimate", "not_available"]
Method = Literal["lt", "barrier_only", "last_missing_tie", "margin", "counterfactual"]


@dataclass(frozen=True)
class BarrierConfig:
    mode: Mode = "optional_idle"
    method: Method = "lt"
    tail_margin_ratio: float = 0.10
    max_tracked_barriers: int = 256
    max_descendant_visits: int = 100_000
    max_feature_transitions: int = 2_000
    max_completion_calls: int = 256
    per_instance_soft_time_s: float = 15.0
    graph_version: str = "np-stage4e-barrier-graph-v1"
    feature_version: str = "np-stage4e-barrier-features-v1"
    completion_version: str = "residual-lt-v1"

    def __post_init__(self) -> None:
        if not 0 <= self.tail_margin_ratio <= 1:
            raise ValueError("tail_margin_ratio must be in [0, 1]")
        for name in ("max_tracked_barriers", "max_descendant_visits", "max_feature_transitions", "max_completion_calls"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")


@dataclass
class BarrierBudget:
    feature_transitions: int = 0
    completion_calls: int = 0
    descendant_visits: int = 0
    budget_rejections: int = 0

    def reserve(self, name: str, limit: int, amount: int = 1) -> bool:
        if getattr(self, name) + amount > limit:
            self.budget_rejections += 1
            return False
        setattr(self, name, getattr(self, name) + amount)
        return True


@dataclass(frozen=True)
class ActionFeatures:
    signature: ActionSignature
    tail: int
    duration: int
    direct_last_missing: tuple[str, ...]
    immediate_release: tuple[str, ...]
    downstream_barriers: tuple[str, ...]
    downstream_barrier_tail: int
    descendants: tuple[str, ...]
    shared_downstream_removed: int
    resource_union: tuple[str, ...]
    excluded_ready: tuple[str, ...]
    quantity_modes: dict[str, QuantityMode]
    truncated: bool = False

    @property
    def barrier_key(self) -> tuple:
        return (len(self.direct_last_missing), len(self.immediate_release), self.downstream_barrier_tail, -self.duration)


@dataclass(frozen=True)
class BarrierDecision:
    index: int
    time: int
    baseline: ActionSignature
    challenger: ActionSignature | None
    selected: ActionSignature
    reason: str
    tail_loss_ratio: float | None
    baseline_features: ActionFeatures
    challenger_features: ActionFeatures | None
    counterfactual_values: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class BarrierResult:
    status: str
    makespan: int | None
    mode: Mode
    method: Method
    config: dict
    actions: tuple[ActionSignature, ...]
    decisions: tuple[dict, ...]
    metrics: dict
    trace_valid: bool
    termination_reason: str | None = None

    @staticmethod
    def config_dict(config: BarrierConfig) -> dict:
        return asdict(config)
