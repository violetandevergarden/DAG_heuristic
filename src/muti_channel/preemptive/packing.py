"""Contracts, bounded construction and accounting for fixed-resource packing."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Iterator, Literal

from core.execution.multi_resource import MultiResourceAction, MultiResourceState, PreemptiveMultiResourceModel

FallbackReason = Literal["pack_budget", "seed_budget", "set_budget", "eval_budget", "time_limit", "no_alternative", "selector_baseline"]


@dataclass(frozen=True)
class PackingBudget:
    """Hard per-decision limits. ``max_sets`` excludes the LT baseline."""
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


@dataclass
class DecisionBudget:
    """Shared ledger used by construction, scoring and completion evaluation."""
    budget: PackingBudget
    started: float = field(default_factory=perf_counter)
    operations: int = 0
    generated_candidates: int = 0
    retained_candidates: int = 0
    completion_calls: int = 0
    fallback_reason: FallbackReason | None = None

    def expired(self) -> bool:
        return self.budget.time_limit_s is not None and perf_counter() - self.started >= self.budget.time_limit_s

    def consume_operation(self, count: int = 1) -> bool:
        if self.expired():
            self.fallback_reason = "time_limit"
            return False
        if self.operations + count > self.budget.b_pack:
            self.fallback_reason = "pack_budget"
            return False
        self.operations += count
        return True

    def retain_candidate(self) -> bool:
        if self.expired():
            self.fallback_reason = "time_limit"
            return False
        if self.retained_candidates >= self.budget.max_sets:
            self.fallback_reason = "set_budget"
            return False
        self.generated_candidates += 1
        self.retained_candidates += 1
        return True

    def reserve_completion(self) -> bool:
        if self.expired():
            self.fallback_reason = "time_limit"
            return False
        if self.completion_calls >= self.budget.b_eval:
            self.fallback_reason = "eval_budget"
            return False
        self.completion_calls += 1
        return True


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
    generated_candidates: int = 0
    seed_count: int = 0
    exchange_count: int = 0
    operations: int = 0
    completion_calls: int = 0
    budget_exhausted: bool = False
    fallback_reason: FallbackReason | None = None
    runtime_ms: float = 0.0


@dataclass(frozen=True)
class PackingResult:
    """Construction output and a selector-resolved action."""
    baseline: MultiResourceAction
    candidates: tuple[MultiResourceAction, ...]
    selected: MultiResourceAction
    constructor: str
    selector: str
    config_version: str
    truncated: bool
    fallback_reason: FallbackReason | None
    stats: PackingStats


def build_conflict_graph(model: PreemptiveMultiResourceModel, state: MultiResourceState) -> ConflictGraph:
    vertices = tuple(sorted(model.eligible(state)))
    edges = tuple((left, right) for index, left in enumerate(vertices) for right in vertices[index + 1 :] if model.resources[left] & model.resources[right])
    footprints = tuple((item, tuple(sorted(model.resources[item]))) for item in vertices)
    return ConflictGraph(vertices, edges, footprints)


def validate_maximal_action(model: PreemptiveMultiResourceModel, state: MultiResourceState, action: MultiResourceAction) -> None:
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
    if any(item not in selected and not (used & model.resources[item]) for item in eligible):
        raise ValueError("packing action is not inclusion-maximal")


def complete_maximal(model: PreemptiveMultiResourceModel, state: MultiResourceState, ordered: tuple[str, ...], *, seed: tuple[str, ...] = ()) -> MultiResourceAction:
    selected = list(seed)
    for item in ordered:
        if item not in selected and model.compatible((*selected, item)):
            selected.append(item)
    action = MultiResourceAction(tuple(sorted(selected)))
    validate_maximal_action(model, state, action)
    return action


def iter_maximal_actions(model: PreemptiveMultiResourceModel, state: MultiResourceState, ledger: DecisionBudget) -> Iterator[MultiResourceAction]:
    """Stream maximal actions, consuming construction budget at each tree node."""
    vertices = tuple(sorted(model.eligible(state)))
    seen: set[MultiResourceAction] = set()

    def visit(index: int, selected: tuple[str, ...]) -> Iterator[MultiResourceAction]:
        if not ledger.consume_operation():
            return
        if index == len(vertices):
            if not selected:
                return
            action = MultiResourceAction(tuple(sorted(selected)))
            try:
                validate_maximal_action(model, state, action)
            except ValueError:
                return
            if action not in seen:
                seen.add(action)
                yield action
            return
        item = vertices[index]
        if model.compatible((*selected, item)):
            yield from visit(index + 1, (*selected, item))
        yield from visit(index + 1, selected)

    yield from visit(0, ())


def deadline_exceeded(started: float, budget: PackingBudget) -> bool:
    return budget.time_limit_s is not None and perf_counter() - started >= budget.time_limit_s
