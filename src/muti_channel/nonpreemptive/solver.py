"""R4: non-preemptive optional-idle scheduling on route resources.

Every started flow reserves all resources on its route until completion.  At a
task-completion event the scheduler may start a compatible subset of ready
flows, or start nothing and wait for the next active task completion.  The
module is isolated research infrastructure and does not change the production
executor.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from collections.abc import Hashable, Iterable
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path
from time import perf_counter
from typing import Literal

from core.execution.nonpreemptive import (
    NonPreeMultiModel,
    OracleMode,
    Resource,
    ResourceAction,
    ResourceInterval,
    ResourceRuntime,
    ResourceState,
    ResourceTransition,
)

@dataclass(frozen=True)
class ResourceSchedule:
    makespan: int
    actions: tuple[ResourceAction, ...]
    intervals: tuple[ResourceInterval, ...]
    runtime_ms: float
    explored_states: int = 0
    voluntary_waits: int = 0
    voluntary_wait_time: int = 0
    forced_waits: int = 0
    forced_wait_time: int = 0
    start_events: int = 0
    flows_started: int = 0
    candidate_actions: int = 0
    conflict_events: int = 0
    lower_bounds: dict[str, int] | None = None
    fallback: bool = False

def residual_resource_loads(
    model: NonPreeMultiModel, state: ResourceState
) -> dict[Resource, int]:
    loads: dict[Resource, int] = defaultdict(int)
    for index, task in enumerate(model.tasks):
        if task.kind != "comm":
            continue
        for resource in model.resources[index]:
            loads[resource] += model.remaining(state, index)
    return dict(loads)


def lower_bounds(model: NonPreeMultiModel, state: ResourceState) -> dict[str, int]:
    path, _tail = model.residual_features(state)
    loads = residual_resource_loads(model, state)
    result = {
        "critical_path": max(path, default=0),
        "max_resource_load": max(loads.values(), default=0),
    }
    result["combined"] = max(result.values())
    return result


StateKey = tuple[tuple[str, int], ...]


def _state_key(state: ResourceState) -> StateKey:
    return tuple((runtime.status, runtime.remaining) for runtime in state.tasks)


def _state_from_key(key: StateKey) -> ResourceState:
    values = []
    for status, remaining in key:
        if status == "pending":
            values.append(ResourceRuntime())
        elif status == "running":
            values.append(ResourceRuntime("running", remaining, 0, None))
        else:
            values.append(ResourceRuntime("completed", 0, 0, 0))
    return ResourceState(0, tuple(values))


def _replay(
    model: NonPreeMultiModel,
    actions: Iterable[ResourceAction],
    *,
    runtime_ms: float,
    explored_states: int = 0,
    candidate_actions: int = 0,
    lower: dict[str, int] | None = None,
    fallback: bool = False,
) -> ResourceSchedule:
    from .replay import replay_actions

    return replay_actions(
        model,
        actions,
        runtime_ms=runtime_ms,
        explored_states=explored_states,
        candidate_actions=candidate_actions,
        lower=lower,
        fallback=fallback,
    )


def _assert_route_reservations(
    model: NonPreeMultiModel,
    intervals: Iterable[ResourceInterval],
) -> None:
    from .replay import assert_route_reservations

    assert_route_reservations(model, intervals)


def exact_oracle(
    instance: DAG,
    *,
    mode: OracleMode = "optional_idle",
    max_states: int = 1_000_000,
    time_limit_s: float = 30.0,
) -> ResourceSchedule:
    started = perf_counter()
    model = NonPreeMultiModel(instance)
    initial = model.initial_state()
    choices: dict[StateKey, ResourceAction] = {}
    explored = 0

    @cache
    def solve(key: StateKey) -> int:
        nonlocal explored
        explored += 1
        if explored > max_states:
            raise RuntimeError("non-preemptive multi-resource oracle state limit")
        if perf_counter() - started > time_limit_s:
            raise TimeoutError("non-preemptive multi-resource oracle time limit")
        state = _state_from_key(key)
        if model.is_finished(state):
            return 0
        actions = model.legal_actions(state, mode)
        if not actions:
            raise RuntimeError("unfinished multi-resource state has no action")
        best = sys.maxsize
        best_action = actions[0]
        for action in actions:
            transition = model.step(state, action)
            delta = transition.after.time - transition.before.time
            value = delta + solve(_state_key(transition.after))
            tie = (action.kind == "wait", len(action.starts), action.starts)
            best_tie = (
                best_action.kind == "wait",
                len(best_action.starts),
                best_action.starts,
            )
            if (value, tie) < (best, best_tie):
                best = value
                best_action = action
        choices[key] = best_action
        return best

    optimum = solve(_state_key(initial))
    actions = []
    state = initial
    while not model.is_finished(state):
        action = choices[_state_key(state)]
        actions.append(action)
        state = model.step(state, action).after
    bounds = lower_bounds(model, initial)
    result = _replay(
        model,
        actions,
        runtime_ms=(perf_counter() - started) * 1000,
        explored_states=explored,
        candidate_actions=sum(
            len(model.legal_actions(_state_from_key(key), mode)) for key in choices
        ),
        lower=bounds,
    )
    if result.makespan != optimum or bounds["combined"] > optimum:
        raise AssertionError("multi-resource exact replay/lower-bound mismatch")
    return result


def _ranked_ready(
    model: NonPreeMultiModel,
    state: ResourceState,
    policy: str,
) -> list[str]:
    ready = list(model.ready_flows(state))
    _path, tail = model.residual_features(state)
    loads = residual_resource_loads(model, state)

    def bottleneck(task_id: str) -> int:
        index = model.index[task_id]
        return max((loads[item] for item in model.resources[index]), default=0)

    def key(task_id: str):
        index = model.index[task_id]
        duration = model.remaining(state, index)
        if policy == "dynamic_tail":
            return tail[index], -duration, task_id
        if policy == "resource_tail":
            return tail[index], bottleneck(task_id), -duration, task_id
        if policy == "bottleneck_first":
            return bottleneck(task_id), tail[index], -duration, task_id
        if policy == "spt":
            return -duration, tail[index], task_id
        if policy == "lpt":
            return duration, tail[index], task_id
        raise ValueError(f"unknown multi-resource policy: {policy}")

    return sorted(ready, key=key, reverse=True)


def greedy_action(
    model: NonPreeMultiModel,
    state: ResourceState,
    policy: str,
) -> ResourceAction:
    selected = []
    occupied = set(model.occupied_resources(state))
    for task_id in _ranked_ready(model, state, policy):
        resources = model.resources[model.index[task_id]]
        if occupied & resources:
            continue
        selected.append(task_id)
        occupied.update(resources)
    return ResourceAction.start(selected) if selected else ResourceAction.wait()


def _complete(
    model: NonPreeMultiModel,
    state: ResourceState,
    policy: str,
) -> tuple[int, tuple[ResourceAction, ...]]:
    start = state.time
    actions = []
    while not model.is_finished(state):
        action = greedy_action(model, state, policy)
        actions.append(action)
        state = model.step(state, action).after
    return state.time - start, tuple(actions)


def schedule_greedy(
    instance: DAG,
    policy: str = "dynamic_tail",
) -> ResourceSchedule:
    started = perf_counter()
    model = NonPreeMultiModel(instance)
    _elapsed, actions = _complete(model, model.initial_state(), policy)
    return _replay(model, actions, runtime_ms=(perf_counter() - started) * 1000)


def _rollout_candidates(
    model: NonPreeMultiModel,
    state: ResourceState,
    *,
    top_k: int,
    optional_actions: bool,
) -> tuple[ResourceAction, ...]:
    subsets = model.start_subsets(state, maximal_only=not optional_actions)
    _path, tail = model.residual_features(state)
    ranked = sorted(
        subsets,
        key=lambda selected: (
            sum(tail[model.index[item]] for item in selected),
            -sum(model.remaining(state, model.index[item]) for item in selected),
            selected,
        ),
        reverse=True,
    )[:top_k]
    result = [ResourceAction.start(items) for items in ranked]
    for policy in ("dynamic_tail", "resource_tail", "bottleneck_first", "spt"):
        action = greedy_action(model, state, policy)
        if action.kind == "start" and action not in result:
            result.append(action)
    if optional_actions and model._has_active_task(state):
        result.append(ResourceAction.wait())
    if not result and model._has_active_task(state):
        result.append(ResourceAction.wait())
    return tuple(dict.fromkeys(result))


def schedule_rollout(
    instance: DAG,
    *,
    top_k: int = 2,
    optional_actions: bool,
    time_limit_s: float = 2.0,
) -> ResourceSchedule:
    started = perf_counter()
    model = NonPreeMultiModel(instance)
    baseline = schedule_greedy(instance)
    state = model.initial_state()
    actions = []
    candidate_actions = 0
    fallback = False
    while not model.is_finished(state):
        base = greedy_action(model, state, "dynamic_tail")
        if perf_counter() - started > time_limit_s:
            action = base
            fallback = True
        else:
            candidates = _rollout_candidates(
                model,
                state,
                top_k=top_k,
                optional_actions=optional_actions,
            )
            if base not in candidates:
                candidates = (*candidates, base)
            candidate_actions += len(candidates)
            scored = []
            for action in candidates:
                transition = model.step(state, action)
                delta = transition.after.time - transition.before.time
                value = delta + _complete(model, transition.after, "dynamic_tail")[0]
                scored.append(
                    (
                        value,
                        action != base,
                        action.kind == "wait",
                        len(action.starts),
                        action.starts,
                        action,
                    )
                )
            action = min(scored, key=lambda item: item[:-1])[-1]
        actions.append(action)
        state = model.step(state, action).after
    result = _replay(
        model,
        actions,
        runtime_ms=(perf_counter() - started) * 1000,
        candidate_actions=candidate_actions,
        fallback=fallback,
    )
    if baseline.makespan < result.makespan:
        return replace(
            baseline,
            runtime_ms=(perf_counter() - started) * 1000,
            candidate_actions=candidate_actions,
            fallback=fallback,
        )
    return result
