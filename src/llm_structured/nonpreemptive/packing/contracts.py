"""Stable contracts for bounded non-preemptive packing."""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass, field
from typing import Literal

from muti_channel.nonpreemptive.solver import ResourceAction

PackingMode = Literal["optional_idle", "work_conserving"]


@dataclass(frozen=True)
class PackingBudget:
    max_vertices_scored: int = 64
    max_seeds: int = 6
    max_pack_operations: int = 512
    max_candidates: int = 12
    max_exchanges: int = 24
    max_feature_nodes: int = 4096
    max_completion_calls: int = 4
    decision_time_limit_s: float = 0.05


@dataclass
class DecisionBudget:
    config: PackingBudget
    pack_operations: int = 0
    exchanges: int = 0
    feature_nodes: int = 0
    completion_calls: int = 0
    exhausted_reasons: set[str] = field(default_factory=set)

    def reserve(self, field_name: str, amount: int = 1) -> bool:
        limit = getattr(self.config, f"max_{field_name}")
        value = getattr(self, field_name)
        if value + amount > limit:
            self.exhausted_reasons.add(field_name)
            return False
        setattr(self, field_name, value + amount)
        return True


@dataclass(frozen=True)
class ConflictGraphSnapshot:
    vertices: tuple[str, ...]
    conflict_edges: tuple[tuple[str, str], ...]
    footprints: tuple[tuple[str, frozenset[Hashable]], ...]
    active: tuple[str, ...]
    occupied_resources: frozenset[Hashable]
    blocked_by_active: tuple[str, ...]
    density: float
    maximum_degree: int
    component_count: int
    truncated: bool = False


@dataclass(frozen=True)
class SetFeatures:
    covered_resources: frozenset[Hashable]
    reachable_union_size: int
    immediate_release_union: tuple[str, ...]
    excluded_critical_tail: int
    max_selected_tail: int
    max_duration: int
    duration_spread: int
    active_after_count: int
    is_maximal: bool
    left_idle_resources: frozenset[Hashable]


@dataclass(frozen=True)
class PackingCandidate:
    action: ResourceAction
    source: str
    seed: str | None = None
    features: SetFeatures | None = None

    @property
    def signature(self) -> tuple[str, ...]:
        return self.action.starts


@dataclass(frozen=True)
class PackingConfig:
    mode: PackingMode = "work_conserving"
    constructor: str = "multi_seed_exchange"
    selector: str = "set_union"
    random_seed: int = 17
    include_exchanges: bool = True
    include_one_for_two: bool = True
    include_optional_challengers: bool = True
    budget: PackingBudget = PackingBudget()
    version: str = "stage4c-nonpreemptive-v1"


@dataclass(frozen=True)
class PackingDecision:
    baseline: ResourceAction
    selected: ResourceAction
    candidates: tuple[PackingCandidate, ...]
    fallback: bool
    fallback_reasons: tuple[str, ...]
    completion_calls: int


@dataclass(frozen=True)
class PackingScheduleResult:
    makespan: int
    actions: tuple[ResourceAction, ...]
    intervals: tuple
    runtime_ms: float
    decisions: int
    candidate_count: int
    completion_calls: int
    fallback_count: int
    fallback_reasons: tuple[tuple[str, int], ...]
    voluntary_waits: int
    voluntary_wait_time: int
    forced_waits: int
    forced_wait_time: int
