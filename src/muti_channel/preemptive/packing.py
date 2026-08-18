"""Contracts and diagnostics for bounded fixed-resource set construction."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Literal

from core.execution.multi_resource import (
    MultiResourceAction,
    MultiResourceState,
    PreemptiveMultiResourceModel,
)


FallbackReason = Literal[
    "pack_budget", "seed_budget", "set_budget", "time_limit", "no_alternative"
]


@dataclass(frozen=True)
class PackingBudget:
    k_score: int = 64
    k_seed: int = 4
    b_pack: int = 256
    b_eval: int = 2
    max_sets: int = 8
    time_limit_s: float | None = None

    def __post_init__(self) -> None:
        for name in ("k_score", "k_seed", "b_pack", "b_eval", "max_sets"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.time_limit_s is not None and self.time_limit_s < 0:
            raise ValueError("time_limit_s must be non-negative")


@dataclass(frozen=True)
class ConflictGraph:
    vertices: tuple[str, ...]
    conflict_edges: tuple[tuple[str, str], ...]
    footprints: tuple[tuple[str, tuple[str, ...]], ...]

    @property
    def density(self) -> float:
        possible = len(self.vertices) * (len(self.vertices) - 1) // 2
        return len(self.conflict_edges) / possible if possible else 0.0

    @property
    def maximum_degree(self) -> int:
        degree = {item: 0 for item in self.vertices}
        for left, right in self.conflict_edges:
            degree[left] += 1
            degree[right] += 1
        return max(degree.values(), default=0)


@dataclass(frozen=True)
class PackingStats:
    candidate_count: int = 0
    seed_count: int = 0
    exchange_count: int = 0
    operations: int = 0
    budget_exhausted: bool = False
    fallback_reason: FallbackReason | None = None
    runtime_ms: float = 0.0


@dataclass(frozen=True)
class PackingResult:
    selected: MultiResourceAction
    candidates: tuple[MultiResourceAction, ...]
    stats: PackingStats


def build_conflict_graph(
    model: PreemptiveMultiResourceModel, state: MultiResourceState
) -> ConflictGraph:
    vertices = tuple(sorted(model.eligible(state)))
    edges = tuple(
        (left, right)
        for index, left in enumerate(vertices)
        for right in vertices[index + 1 :]
        if model.resources[left] & model.resources[right]
    )
    footprints = tuple(
        (item, tuple(sorted(model.resources[item]))) for item in vertices
    )
    return ConflictGraph(vertices, edges, footprints)


def validate_maximal_action(
    model: PreemptiveMultiResourceModel,
    state: MultiResourceState,
    action: MultiResourceAction,
) -> None:
    selected = action.communications
    eligible = set(model.eligible(state))
    if not selected:
        raise ValueError("packing action must be non-empty")
    if tuple(sorted(selected)) != selected or len(set(selected)) != len(selected):
        raise ValueError("packing action must contain unique stable-sorted IDs")
    if not set(selected) <= eligible:
        raise ValueError("packing action contains an ineligible communication")
    if not model.compatible(selected):
        raise ValueError("packing action contains a resource conflict")
    used = set().union(*(model.resources[item] for item in selected))
    if any(
        item not in selected and not (used & model.resources[item])
        for item in eligible
    ):
        raise ValueError("packing action is not inclusion-maximal")


def complete_maximal(
    model: PreemptiveMultiResourceModel,
    state: MultiResourceState,
    ordered: tuple[str, ...],
    *,
    seed: tuple[str, ...] = (),
) -> MultiResourceAction:
    selected = list(seed)
    for item in ordered:
        if item not in selected and model.compatible((*selected, item)):
            selected.append(item)
    action = MultiResourceAction(tuple(sorted(selected)))
    validate_maximal_action(model, state, action)
    return action


def deadline_exceeded(started: float, budget: PackingBudget) -> bool:
    return (
        budget.time_limit_s is not None
        and perf_counter() - started >= budget.time_limit_s
    )
