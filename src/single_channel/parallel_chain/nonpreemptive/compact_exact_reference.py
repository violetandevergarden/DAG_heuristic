"""Isolated compact-state exact reference for non-preemptive parallel chains.

This module deliberately owns the only compact state transition left in the
parallel-chain package.  Production schedulers use ``NonPreeSingleModel``;
the compact transition is retained only because it is substantially cheaper
for small exact-reference instances and is cross-checked state by state.
"""

from __future__ import annotations

from collections import defaultdict
from functools import cache
from time import perf_counter

from .solver import (
    ChainAction,
    ChainSearchResult,
    ChainState,
    ParallelChain,
    active_computes,
    initial_state,
    is_finished,
    ready_chains,
    residual_bounds,
    schedule_rollout,
)


def legal_actions(
    chains: tuple[ParallelChain, ...],
    state: ChainState,
    *,
    optional_idle: bool,
) -> tuple[ChainAction, ...]:
    flows = tuple(ChainAction.flow(index) for index in ready_chains(chains, state))
    can_wait = bool(active_computes(state))
    if optional_idle:
        return (*flows, ChainAction.wait()) if can_wait else flows
    if flows:
        return flows
    return (ChainAction.wait(),) if can_wait else ()


def advance(
    chains: tuple[ParallelChain, ...],
    state: ChainState,
    action: ChainAction,
) -> tuple[ChainState, int]:
    if action.kind == "wait":
        active = active_computes(state)
        if not active:
            raise ValueError("WAIT requires an active compute")
        duration = min(state[index][1] for index in active)
        return tuple(
            (operation, max(0, cooldown - duration))
            for operation, cooldown in state
        ), duration

    if action.chain is None or action.chain not in ready_chains(chains, state):
        raise ValueError(f"flow action is not ready: {action}")
    selected = action.chain
    operation = state[selected][0]
    duration = chains[selected].comm[operation]
    values = [
        (item_operation, max(0, cooldown - duration))
        for item_operation, cooldown in state
    ]
    values[selected] = (operation + 1, chains[selected].compute[operation])
    return tuple(values), duration


def _canonicalizer(chains: tuple[ParallelChain, ...]):
    groups: dict[ParallelChain, list[int]] = defaultdict(list)
    for index, chain in enumerate(chains):
        groups[chain].append(index)
    repeated = tuple(tuple(items) for items in groups.values() if len(items) > 1)

    def canonical(state: ChainState) -> ChainState:
        values = list(state)
        for indices in repeated:
            ordered = sorted(values[index] for index in indices)
            for index, value in zip(indices, ordered, strict=True):
                values[index] = value
        return tuple(values)

    return canonical


def exact_dp(
    chains: tuple[ParallelChain, ...],
    *,
    optional_idle: bool,
    max_states: int = 2_000_000,
    time_limit_s: float = 30.0,
    symmetry: bool = True,
) -> ChainSearchResult:
    started = perf_counter()
    canonical = _canonicalizer(chains) if symmetry else (lambda state: state)
    explored = 0

    @cache
    def solve(raw_state: ChainState) -> int:
        nonlocal explored
        state = canonical(raw_state)
        explored += 1
        if explored > max_states:
            raise RuntimeError(f"chain exact DP exceeded max_states={max_states}")
        if perf_counter() - started > time_limit_s:
            raise TimeoutError(f"chain exact DP exceeded time_limit_s={time_limit_s}")
        if is_finished(chains, state):
            return 0
        actions = legal_actions(chains, state, optional_idle=optional_idle)
        if not actions:
            raise RuntimeError("unfinished chain state has no legal action")
        return min(
            duration + solve(canonical(successor))
            for action in actions
            for successor, duration in (advance(chains, state, action),)
        )

    optimum = solve(canonical(initial_state(chains)))
    return ChainSearchResult(optimum, (), explored, (perf_counter() - started) * 1000)


def _feasible_within(
    chains: tuple[ParallelChain, ...],
    horizon: int,
    *,
    optional_idle: bool,
    max_states: int,
) -> tuple[bool, int]:
    canonical = _canonicalizer(chains)
    explored = 0

    @cache
    def feasible(raw_state: ChainState, budget: int) -> bool:
        nonlocal explored
        state = canonical(raw_state)
        explored += 1
        if explored > max_states:
            raise RuntimeError("chain binary feasibility DP exceeded state budget")
        if is_finished(chains, state):
            return True
        if budget < residual_bounds(chains, state)["combined"]:
            return False
        for action in legal_actions(chains, state, optional_idle=optional_idle):
            successor, duration = advance(chains, state, action)
            if duration <= budget and feasible(canonical(successor), budget - duration):
                return True
        return False

    return feasible(canonical(initial_state(chains)), horizon), explored


def binary_search_exact(
    chains: tuple[ParallelChain, ...],
    *,
    optional_idle: bool,
    max_states: int = 2_000_000,
) -> ChainSearchResult:
    started = perf_counter()
    lower = residual_bounds(chains, initial_state(chains))["combined"]
    upper = schedule_rollout(chains, top_k=2, allow_wait=optional_idle).makespan
    explored = 0
    while lower < upper:
        middle = (lower + upper) // 2
        feasible, states = _feasible_within(
            chains, middle, optional_idle=optional_idle, max_states=max_states
        )
        explored += states
        if feasible:
            upper = middle
        else:
            lower = middle + 1
    return ChainSearchResult(lower, (), explored, (perf_counter() - started) * 1000)


__all__ = ["advance", "binary_search_exact", "exact_dp", "legal_actions"]
