"""Frozen configuration for bounded local critical-frontier search."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AdoptionMode = Literal["diagnostic", "risk_controlled"]


@dataclass(frozen=True)
class LocalFrontierConfig:
    name: str = "local_frontier_diagnostic"
    version: str = "stage4h-v1"
    max_candidates: int = 2
    decision_depth: int = 4
    max_local_nodes: int = 64
    max_expansions: int = 96
    per_decision_time_limit_s: float = 0.005
    total_time_limit_s: float = 2.0
    max_graph_tasks: int = 1000
    adoption_mode: AdoptionMode = "diagnostic"
    min_proxy_gain: int = 1
    max_normalized_tail_margin: float = 1.0

    def __post_init__(self) -> None:
        integer_fields = (
            "max_candidates", "decision_depth", "max_local_nodes",
            "max_expansions", "max_graph_tasks", "min_proxy_gain",
        )
        if any(getattr(self, item) < 0 for item in integer_fields):
            raise ValueError("local-frontier integer budgets must be non-negative")
        if self.max_candidates not in {0, 2}:
            raise ValueError("stage4h-v1 supports disabled or width-2 search")
        if self.per_decision_time_limit_s < 0 or self.total_time_limit_s < 0:
            raise ValueError("time budgets must be non-negative")
        if not 0 <= self.max_normalized_tail_margin <= 1:
            raise ValueError("tail margin must be in [0, 1]")


def diagnostic_config() -> LocalFrontierConfig:
    return LocalFrontierConfig()


def tiny_config(*, adoption_mode: AdoptionMode = "diagnostic") -> LocalFrontierConfig:
    return LocalFrontierConfig(
        name=f"local_frontier_tiny_{adoption_mode}", decision_depth=2,
        max_local_nodes=32, max_expansions=32,
        per_decision_time_limit_s=0.002, total_time_limit_s=0.5,
        adoption_mode=adoption_mode,
    )


def medium_config(*, adoption_mode: AdoptionMode = "diagnostic") -> LocalFrontierConfig:
    return LocalFrontierConfig(
        name=f"local_frontier_medium_{adoption_mode}", decision_depth=8,
        max_local_nodes=128, max_expansions=256,
        per_decision_time_limit_s=0.02, total_time_limit_s=10.0,
        adoption_mode=adoption_mode,
    )
