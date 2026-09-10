"""Exact search for fixed-resource non-preemptive DAG scheduling."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import cache
from time import perf_counter
from typing import Literal

from core.dag import DAG
from core.execution.nonpreemptive import (
    NonPreeMultiModel,
    OracleMode,
    ResourceAction,
    ResourceInterval,
    ResourceRuntime,
    ResourceState,
)
from core.trace.nonpree_multi import assert_nonpreemptive_multi_trace


@dataclass(frozen=True)
class MultiResourceOracleResult:
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
    status: Literal["feasible", "optimal"] = "optimal"
    termination_reason: str | None = "complete_enumeration"
    exact_stats: ExactStats | None = None


@dataclass(frozen=True)
class ExactStats:
    candidate_actions: int = 0
    conflict_events: int = 0
    lower_bounds: dict[str, int] | None = None


OracleStateKey = tuple[object, ...]


def _compressed_key(state: ResourceState) -> OracleStateKey:
    return tuple((item.status, item.remaining) for item in state.tasks)


def _uncompressed_key(state: ResourceState) -> OracleStateKey:
    return (
        state.time,
        tuple(
            (item.status, item.remaining, item.started_at, item.completed_at)
            for item in state.tasks
        ),
    )


def _state_from_key(key: OracleStateKey, *, compressed: bool) -> ResourceState:
    if compressed:
        time = 0
        values = key
    else:
        time = key[0]
        values = key[1]
    tasks = []
    for value in values:
        status, remaining = value[:2]
        if status == "pending":
            tasks.append(ResourceRuntime())
        elif status == "running":
            started_at = value[2] if not compressed else 0
            tasks.append(ResourceRuntime("running", remaining, started_at, None))
        else:
            completed_at = value[3] if not compressed else 0
            tasks.append(ResourceRuntime("completed", 0, value[2] if not compressed else 0, completed_at))
    return ResourceState(time, tuple(tasks))


def _replay(
    model: NonPreeMultiModel,
    actions: tuple[ResourceAction, ...],
    *,
    runtime_ms: float,
    explored: int,
    lower: dict[str, int],
    status: Literal["feasible", "optimal"],
    reason: str,
    candidate_actions: int,
    conflict_events: int,
    exact_stats: ExactStats | None = None,
) -> MultiResourceOracleResult:
    state = model.initial_state()
    intervals: list[ResourceInterval] = []
    voluntary_waits = voluntary_time = forced_waits = forced_time = 0
    for action in actions:
        ready = bool(model.startable_flows(state))
        transition = model.step(state, action)
        delta = transition.after.time - transition.before.time
        if action.kind == "wait":
            if ready:
                voluntary_waits += 1
                voluntary_time += delta
            else:
                forced_waits += 1
                forced_time += delta
        intervals.extend(transition.intervals)
        state = transition.after
    if not model.is_finished(state):
        raise AssertionError("exact action path did not finish")
    assert_nonpreemptive_multi_trace(
        model.dag,
        {
            task.task_id: frozenset(model.resources[index])
            for index, task in enumerate(model.tasks)
            if task.kind == "comm"
        },
        tuple(intervals),
        final_state=state,
    )
    return MultiResourceOracleResult(
        state.time,
        actions,
        tuple(intervals),
        runtime_ms,
        explored,
        voluntary_waits,
        voluntary_time,
        forced_waits,
        forced_time,
        sum(action.kind == "start" for action in actions),
        sum(len(action.starts) for action in actions),
        candidate_actions,
        conflict_events,
        lower,
        status=status,
        termination_reason=reason,
        exact_stats=exact_stats,
    )


def exact_oracle(
    dag: DAG,
    *,
    mode: OracleMode = "optional_idle",
    max_states: int = 1_000_000,
    time_limit_s: float = 30.0,
    normalized: bool = True,
) -> MultiResourceOracleResult:
    if mode not in ("optional_idle", "work_conserving"):
        raise ValueError(f"unknown oracle mode: {mode}")
    if max_states < 1:
        raise ValueError("max_states must be positive")
    started = perf_counter()
    model = NonPreeMultiModel(dag)
    initial = model.initial_state()
    choices: dict[OracleStateKey, ResourceAction] = {}
    explored = candidate_actions = conflict_events = 0
    key_fn = _compressed_key if normalized else _uncompressed_key

    @cache
    def solve(key: OracleStateKey) -> int:
        nonlocal explored, candidate_actions, conflict_events
        explored += 1
        if explored > max_states:
            raise RuntimeError("non-preemptive multi-resource oracle state limit")
        if perf_counter() - started > time_limit_s:
            raise TimeoutError("non-preemptive multi-resource oracle time limit")
        state = _state_from_key(key, compressed=normalized)
        if model.is_finished(state):
            return 0
        actions = model.legal_actions(state, mode)
        candidate_actions += len(actions)
        ready = model.startable_flows(state)
        if any(
            model.resources[model.index[left]] & model.resources[model.index[right]]
            for position, left in enumerate(ready)
            for right in ready[position + 1 :]
        ):
            conflict_events += 1
        if not actions:
            raise RuntimeError("unfinished multi-resource state has no action")
        best = sys.maxsize
        best_action = actions[0]
        for action in actions:
            transition = model.step(state, action)
            value = transition.after.time - state.time + solve(key_fn(transition.after))
            tie = (action.kind == "wait", len(action.starts), action.starts)
            best_tie = (best_action.kind == "wait", len(best_action.starts), best_action.starts)
            if (value, tie) < (best, best_tie):
                best, best_action = value, action
        choices[key] = best_action
        return best

    optimum = solve(key_fn(initial))
    state = initial
    actions: list[ResourceAction] = []
    while not model.is_finished(state):
        action = choices[key_fn(state)]
        actions.append(action)
        state = model.step(state, action).after
    path, _ = model.residual_features(initial)
    loads: dict[object, int] = {}
    for index, task in enumerate(model.tasks):
        if task.kind != "comm":
            continue
        for resource in model.resources[index]:
            loads[resource] = loads.get(resource, 0) + model.remaining(initial, index)
    lower = {
        "critical_path": max(path, default=0),
        "max_resource_load": max(loads.values(), default=0),
    }
    lower["combined"] = max(lower.values(), default=0)
    result = _replay(
        model,
        tuple(actions),
        runtime_ms=(perf_counter() - started) * 1000,
        explored=explored,
        lower=lower,
        status="optimal",
        reason="complete_enumeration",
        candidate_actions=candidate_actions,
        conflict_events=conflict_events,
        exact_stats=ExactStats(candidate_actions, conflict_events, lower),
    )
    if result.makespan != optimum:
        raise AssertionError("multi-resource exact replay mismatch")
    return result


def exact_completion_from_state(
    model: NonPreeMultiModel,
    state: ResourceState,
    *,
    mode: OracleMode = "optional_idle",
    max_states: int = 100_000,
    time_limit_s: float = 30.0,
):
    """Solve the residual fixed-resource problem from a decision state."""
    from core.oracle.nonpree_single import NonPreemptiveCompletionResult

    if max_states < 1:
        raise ValueError("max_states must be positive")
    if time_limit_s <= 0:
        raise ValueError("time_limit_s must be positive")
    started = perf_counter()
    explored = 0

    @cache
    def solve(key: OracleStateKey) -> int:
        nonlocal explored
        explored += 1
        if explored > max_states:
            raise RuntimeError("state_limit")
        if perf_counter() - started > time_limit_s:
            raise TimeoutError("time_limit")
        current = _state_from_key(key, compressed=True)
        if model.is_finished(current):
            return 0
        actions = model.legal_actions(current, mode)
        if not actions:
            raise RuntimeError("no_legal_action")
        best: int | None = None
        for action in actions:
            transition = model.step(current, action)
            value = transition.after.time - current.time + solve(_compressed_key(transition.after))
            best = value if best is None else min(best, value)
        assert best is not None
        return best

    try:
        initial_key = _compressed_key(state)
        optimum = solve(initial_key)
        best = []
        for action in model.legal_actions(state, mode):
            transition = model.step(state, action)
            if transition.after.time - state.time + solve(_compressed_key(transition.after)) == optimum:
                best.append(action)
        return NonPreemptiveCompletionResult(
            "optimal", optimum, tuple(best), explored, None
        )
    except (RuntimeError, TimeoutError) as error:
        return NonPreemptiveCompletionResult(
            "unknown", None, (), explored, str(error)
        )


def exact_oracle_uncompressed(
    dag: DAG,
    *,
    mode: OracleMode = "optional_idle",
    max_states: int = 1_000_000,
    time_limit_s: float = 30.0,
) -> MultiResourceOracleResult:
    """Audit entry point retaining absolute time and runtime timestamps."""
    return exact_oracle(
        dag,
        mode=mode,
        max_states=max_states,
        time_limit_s=time_limit_s,
        normalized=False,
    )


__all__ = [
    "MultiResourceOracleResult",
    "ExactStats",
    "exact_oracle",
    "exact_oracle_uncompressed",
]
