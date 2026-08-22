"""Frozen configuration contract for Stage 4g policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ResourceMode = Literal["single", "fixed_multi"]
PackingMode = Literal["lt_greedy", "bounded_candidate"]
RolloutMode = Literal["off", "truncated_experimental"]
BarrierMode = Literal["off", "diagnostics_only"]


@dataclass(frozen=True)
class IntegratedConfig:
    name: str
    config_version: str = "stage4g-integrated-v0"
    resource_mode: ResourceMode = "single"
    packing_mode: PackingMode = "lt_greedy"
    rollout_mode: RolloutMode = "off"
    barrier_mode: BarrierMode = "diagnostics_only"
    k_seed: int = 4
    b_pack: int = 256
    max_sets: int = 8
    max_candidates: int = 2
    search_depth: int = 1
    max_expansions: int = 0
    evaluation_steps: int = 0
    per_decision_time_limit_s: float = 0.0
    total_time_limit_s: float = 0.0
    large_graph_safe_threshold: int = 1000
    tie_break_version: str = "task-id-v1"
    detailed_audit: bool = True

    def __post_init__(self) -> None:
        for field_name in (
            "k_seed",
            "b_pack",
            "max_sets",
            "max_candidates",
            "search_depth",
            "max_expansions",
            "evaluation_steps",
            "large_graph_safe_threshold",
        ):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must be non-negative")
        if self.per_decision_time_limit_s < 0 or self.total_time_limit_s < 0:
            raise ValueError("time budgets must be non-negative")
        if self.resource_mode == "single" and self.packing_mode != "lt_greedy":
            raise ValueError("single-channel mode cannot enable packing")
        if self.rollout_mode == "truncated_experimental":
            if not self.max_candidates or not self.search_depth or not self.evaluation_steps:
                raise ValueError("truncated rollout requires positive candidate/depth/step budgets")
        elif self.max_expansions or self.evaluation_steps:
            raise ValueError("disabled rollout must not reserve search work")
        if self.barrier_mode not in {"off", "diagnostics_only"}:
            raise ValueError("barrier may only be disabled or diagnostic")


def integrated_v0(resource_mode: ResourceMode) -> IntegratedConfig:
    return IntegratedConfig(name="integrated_v0", resource_mode=resource_mode)


def integrated_safe_large(resource_mode: ResourceMode) -> IntegratedConfig:
    return IntegratedConfig(
        name="integrated_safe_large",
        resource_mode=resource_mode,
        barrier_mode="off",
        detailed_audit=False,
    )


def integrated_p_exp() -> IntegratedConfig:
    return IntegratedConfig(
        name="integrated_p_exp",
        config_version="stage4g-integrated-p-exp-v1",
        resource_mode="fixed_multi",
        packing_mode="bounded_candidate",
    )


def integrated_r_exp(resource_mode: ResourceMode = "single") -> IntegratedConfig:
    return IntegratedConfig(
        name="integrated_r_exp",
        config_version="stage4g-integrated-r-exp-v1",
        resource_mode=resource_mode,
        rollout_mode="truncated_experimental",
        max_expansions=64,
        evaluation_steps=2,
        per_decision_time_limit_s=0.02,
        total_time_limit_s=2.0,
    )
