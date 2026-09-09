"""Bounded deterministic packing constructors and local exchanges."""

from __future__ import annotations

import random

from core.execution.nonpreemptive import (
    NonPreeMultiModel,
    ResourceAction,
    ResourceState,
)

from .contracts import DecisionBudget, PackingCandidate, PackingConfig
from .graph import build_conflict_graph


def _orders(model, state, random_seed: int):
    vertices = list(model.startable_flows(state))
    _path, tails = model.residual_features(state)
    duration = lambda item: model.remaining(state, model.index[item])
    tail = lambda item: tails[model.index[item]]
    loads = {resource: 0 for resources in model.resources for resource in resources}
    for index, task in enumerate(model.tasks):
        if task.kind == "comm" and state.tasks[index].status != "completed":
            for resource in model.resources[index]: loads[resource] += model.remaining(state, index)
    hotspot = lambda item: max((loads[x] for x in model.resources[model.index[item]]), default=0)
    degree = {item: 0 for item in vertices}
    graph = build_conflict_graph(model, state)
    for left, right in graph.conflict_edges: degree[left] += 1; degree[right] += 1
    rng = random.Random(random_seed); shuffled = vertices[:]; rng.shuffle(shuffled)
    return {
        "fixed": sorted(vertices, key=lambda x: model.index[x]),
        "fifo": sorted(vertices, key=lambda x: (x, model.index[x])),
        "lt": sorted(vertices, key=lambda x: (-tail(x), duration(x), x)),
        "short": sorted(vertices, key=lambda x: (duration(x), -tail(x), x)),
        "long": sorted(vertices, key=lambda x: (-duration(x), -tail(x), x)),
        "hotspot": sorted(vertices, key=lambda x: (-hotspot(x), -tail(x), x)),
        "degree": sorted(vertices, key=lambda x: (-degree[x], -tail(x), x)),
        "random": shuffled,
    }


def greedy_fill(model, state, order, budget: DecisionBudget, initial=()):
    selected = list(initial); used = set(model.occupied_resources(state))
    for task_id in selected: used.update(model.resources[model.index[task_id]])
    for task_id in order:
        if task_id in selected: continue
        if not budget.reserve("pack_operations"): break
        resources = model.resources[model.index[task_id]]
        if not used & resources: selected.append(task_id); used.update(resources)
    return ResourceAction.start(selected) if selected else ResourceAction.wait()


def baseline_action(model, state, policy="lt"):
    budget = DecisionBudget(PackingConfig().budget)
    return greedy_fill(model, state, _orders(model, state, 17)[policy], budget)


def construct_candidates(model: NonPreeMultiModel, state: ResourceState,
                         config: PackingConfig, budget: DecisionBudget) -> tuple[PackingCandidate, ...]:
    orders = _orders(model, state, config.random_seed)
    candidates: dict[tuple[str, ...], PackingCandidate] = {}
    baseline = greedy_fill(model, state, orders["lt"], budget)
    candidates[baseline.starts] = PackingCandidate(baseline, "lt")
    for name in ("fixed", "fifo", "short", "long", "hotspot", "degree", "random")[:config.budget.max_seeds]:
        action = greedy_fill(model, state, orders[name], budget)
        if action.kind == "start": candidates.setdefault(action.starts, PackingCandidate(action, name, action.starts[0]))
        if len(candidates) >= config.budget.max_candidates: break
    selected = baseline.starts
    excluded = [x for x in orders["lt"] if x not in selected]
    if config.include_exchanges:
        for incoming in excluded:
            if len(candidates) >= config.budget.max_candidates or not budget.reserve("exchanges"): break
            conflicts = [x for x in selected if model.resources[model.index[x]] & model.resources[model.index[incoming]]]
            if not conflicts: continue
            remaining = tuple(x for x in selected if x not in conflicts)
            action = greedy_fill(model, state, orders["lt"], budget, (*remaining, incoming))
            if action.kind == "start": candidates.setdefault(action.starts, PackingCandidate(action, "one_for_one", incoming))
    if config.include_exchanges and config.include_one_for_two:
        for outgoing in selected:
            pool = [x for x in excluded if model.resources[model.index[x]] & model.resources[model.index[outgoing]]]
            for pos, left in enumerate(pool):
                for right in pool[pos + 1:]:
                    if len(candidates) >= config.budget.max_candidates or not budget.reserve("exchanges"): break
                    if model.resources[model.index[left]] & model.resources[model.index[right]]: continue
                    initial = tuple(x for x in selected if x != outgoing) + (left, right)
                    action = greedy_fill(model, state, orders["lt"], budget, initial)
                    candidates.setdefault(action.starts, PackingCandidate(action, "one_for_two", outgoing))
                if len(candidates) >= config.budget.max_candidates: break
            if len(candidates) >= config.budget.max_candidates: break
    if config.mode == "optional_idle" and config.include_optional_challengers and model.has_future_event(state):
        candidates.setdefault((), PackingCandidate(ResourceAction.wait(), "wait"))
        if baseline.starts:
            prefix = ResourceAction.start(baseline.starts[:1])
            candidates.setdefault(prefix.starts, PackingCandidate(prefix, "lt_prefix"))
    return tuple(candidates.values())
