"""R2 study for non-preemptive single-channel parallel chains.

Every action completes one whole communication or waits to the next compute
completion.  The compact chain state is cross-checked against the R0 DAG state
machine and the R1 exact oracle on small instances.

Use the public runner documented in the repository ``README.md``.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from itertools import product
import json
from pathlib import Path
import random
from statistics import mean
import sys
from time import perf_counter
from typing import Literal


ROOT = Path(__file__).resolve().parents[2]


def chains_from_dag(dag):
    """Build the compact chain input from a validated internal DAG."""

    from single_channel.parallel_chain.model import parse_parallel_chain

    instance = parse_parallel_chain(dag)
    tasks = dag.task_map()
    chains: list[ParallelChain] = []
    for task_ids in instance.chains:
        sequence = [tasks[task_id] for task_id in task_ids]
        position = 0
        initial_delay = 0
        if sequence[0].kind == "compute":
            initial_delay = sequence[0].duration
            position = 1
        comm: list[int] = []
        compute: list[int] = []
        while position < len(sequence):
            if sequence[position].kind != "comm":
                raise ValueError(f"expected communication at {sequence[position].task_id}")
            comm.append(sequence[position].duration)
            position += 1
            if position >= len(sequence) or sequence[position].kind != "compute":
                raise ValueError("each parallel-chain communication must have a compute tail")
            compute.append(sequence[position].duration)
            position += 1
        if not comm:
            raise ValueError("parallel-chain component has no communication")
        chains.append(ParallelChain(tuple(comm), tuple(compute), initial_delay))
    return tuple(chains)

from core.dag import DAGBuilder  # noqa: E402
from core.execution.nonpreemptive import (  # noqa: E402
    Action as DAGAction,
    NonPreeSingleModel,
)
from core.trace.nonpreemptive import assert_nonpreemptive_trace  # noqa: E402


ChainState = tuple[tuple[int, int], ...]  # (next communication, compute cooldown)
ActionKind = Literal["flow", "wait"]


@dataclass(frozen=True)
class ParallelChain:
    comm: tuple[int, ...]
    compute: tuple[int, ...]
    initial_delay: int = 0

    def __post_init__(self) -> None:
        if not self.comm or len(self.comm) != len(self.compute):
            raise ValueError("comm and compute must have the same positive length")
        if any(value <= 0 for value in self.comm):
            raise ValueError("communication durations must be positive")
        if self.initial_delay < 0 or any(value < 0 for value in self.compute):
            raise ValueError("compute durations must be non-negative")

@dataclass(frozen=True)
class ChainAction:
    kind: ActionKind
    chain: int | None = None

    @classmethod
    def flow(cls, chain: int) -> ChainAction:
        return cls("flow", chain)

    @classmethod
    def wait(cls) -> ChainAction:
        return cls("wait")


@dataclass(frozen=True)
class ChainSchedule:
    makespan: int
    actions: tuple[ChainAction, ...]
    network_busy: int
    voluntary_idle: int
    forced_idle: int
    compute_active_time: int
    compute_capacity_time: int
    overlap_time: int
    runtime_ms: float
    fallback: bool = False

    @property
    def network_idle(self) -> int:
        return self.voluntary_idle + self.forced_idle

    @property
    def preemptions(self) -> int:
        return 0


@dataclass(frozen=True)
class ChainSearchResult:
    makespan: int
    actions: tuple[ChainAction, ...]
    explored_states: int
    runtime_ms: float
    fallback: bool = False


def initial_state(chains: tuple[ParallelChain, ...]) -> ChainState:
    return tuple((0, chain.initial_delay) for chain in chains)


def is_finished(chains: tuple[ParallelChain, ...], state: ChainState) -> bool:
    return all(
        operation == len(chain.comm) and cooldown == 0
        for chain, (operation, cooldown) in zip(chains, state, strict=True)
    )


def ready_chains(chains: tuple[ParallelChain, ...], state: ChainState) -> list[int]:
    return [
        index
        for index, (chain, (operation, cooldown)) in enumerate(
            zip(chains, state, strict=True)
        )
        if operation < len(chain.comm) and cooldown == 0
    ]


def active_computes(state: ChainState) -> list[int]:
    return [index for index, (_operation, cooldown) in enumerate(state) if cooldown > 0]


def legal_actions(
    chains: tuple[ParallelChain, ...],
    state: ChainState,
    *,
    optional_idle: bool,
) -> tuple[ChainAction, ...]:
    ready = ready_chains(chains, state)
    flows = tuple(ChainAction.flow(index) for index in ready)
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


def residual_bounds(
    chains: tuple[ParallelChain, ...], state: ChainState
) -> dict[str, int]:
    communication = 0
    compute = 0
    chain_path = 0
    for chain, (operation, cooldown) in zip(chains, state, strict=True):
        remaining_comm = sum(chain.comm[operation:])
        remaining_compute = cooldown + sum(chain.compute[operation:])
        communication += remaining_comm
        compute = max(compute, remaining_compute)
        chain_path = max(chain_path, remaining_comm + remaining_compute)
    return {
        "P": communication,
        "Q": compute,
        "L": chain_path,
        "combined": max(communication, compute, chain_path),
    }


def _flow_tail(
    chains: tuple[ParallelChain, ...], state: ChainState, index: int
) -> int:
    operation = state[index][0]
    chain = chains[index]
    return sum(chain.compute[operation:]) + sum(chain.comm[operation + 1 :])


def _flow_duration(
    chains: tuple[ParallelChain, ...], state: ChainState, index: int
) -> int:
    return chains[index].comm[state[index][0]]


BASE_POLICIES = (
    "fifo",
    "spt",
    "lpt",
    "longest_delay",
    "dynamic_tail",
    "lrpt",
    "earliest_slack",
    "tictac",
)


def select_flow(
    policy: str,
    chains: tuple[ParallelChain, ...],
    state: ChainState,
    ready: list[int],
) -> int:
    if policy == "fifo":
        return min(ready)
    if policy == "spt":
        return min(ready, key=lambda item: (_flow_duration(chains, state, item), item))
    if policy == "lpt":
        return max(ready, key=lambda item: (_flow_duration(chains, state, item), -item))
    if policy == "longest_delay":
        return max(
            ready,
            key=lambda item: (
                chains[item].compute[state[item][0]],
                -item,
            ),
        )
    if policy == "dynamic_tail":
        return max(ready, key=lambda item: (_flow_tail(chains, state, item), -item))
    if policy in {"lrpt", "earliest_slack"}:
        return max(
            ready,
            key=lambda item: (
                _flow_duration(chains, state, item)
                + _flow_tail(chains, state, item),
                -item,
            ),
        )
    if policy == "tictac":
        winner = ready[0]
        for candidate in ready[1:]:
            pa = _flow_duration(chains, state, winner)
            pb = _flow_duration(chains, state, candidate)
            qa = _flow_tail(chains, state, winner)
            qb = _flow_tail(chains, state, candidate)
            ab = max(pa + qa, pa + pb + qb)
            ba = max(pb + qb, pb + pa + qa)
            if (ba, candidate) < (ab, winner):
                winner = candidate
        return winner
    raise ValueError(f"unknown non-preemptive chain policy: {policy}")


def priority_action(
    policy: str,
    chains: tuple[ParallelChain, ...],
    state: ChainState,
) -> ChainAction:
    ready = ready_chains(chains, state)
    if ready:
        return ChainAction.flow(select_flow(policy, chains, state, ready))
    if active_computes(state):
        return ChainAction.wait()
    raise RuntimeError("unfinished chain state has no legal action")


def _simulate_actions(
    chains: tuple[ParallelChain, ...],
    choose,
    *,
    start_state: ChainState | None = None,
    collect_metrics: bool = True,
) -> ChainSchedule:
    started = perf_counter()
    state = initial_state(chains) if start_state is None else start_state
    actions: list[ChainAction] = []
    elapsed = 0
    network_busy = 0
    voluntary_idle = 0
    forced_idle = 0
    compute_active_time = 0
    overlap_time = 0
    while not is_finished(chains, state):
        action = choose(state)
        if action not in legal_actions(chains, state, optional_idle=True):
            raise ValueError(f"scheduler returned illegal action: {action}")
        cooldowns = [cooldown for _operation, cooldown in state]
        had_ready = bool(ready_chains(chains, state))
        successor, duration = advance(chains, state, action)
        compute_active_time += sum(min(cooldown, duration) for cooldown in cooldowns)
        if action.kind == "flow":
            network_busy += duration
            overlap_time += min(max(cooldowns, default=0), duration)
        elif had_ready:
            voluntary_idle += duration
        else:
            forced_idle += duration
        actions.append(action)
        elapsed += duration
        state = successor
    return ChainSchedule(
        elapsed,
        tuple(actions),
        network_busy,
        voluntary_idle,
        forced_idle,
        compute_active_time,
        elapsed * len(chains),
        overlap_time,
        (perf_counter() - started) * 1000 if collect_metrics else 0.0,
    )


def schedule_priority(
    chains: tuple[ParallelChain, ...], policy: str = "dynamic_tail"
) -> ChainSchedule:
    return _simulate_actions(
        chains, lambda state: priority_action(policy, chains, state)
    )


def _completion_cost(
    chains: tuple[ParallelChain, ...], state: ChainState, policy: str
) -> int:
    return _simulate_actions(
        chains,
        lambda item: priority_action(policy, chains, item),
        start_state=state,
        collect_metrics=False,
    ).makespan


def schedule_rollout(
    chains: tuple[ParallelChain, ...],
    *,
    top_k: int = 2,
    allow_wait: bool,
    base_policy: str = "dynamic_tail",
    time_limit_s: float = 2.0,
) -> ChainSchedule:
    started = perf_counter()
    fallback = False

    def choose(state: ChainState) -> ChainAction:
        nonlocal fallback
        base_action = priority_action(base_policy, chains, state)
        if perf_counter() - started > time_limit_s:
            fallback = True
            return base_action
        ready = ready_chains(chains, state)
        ranked = sorted(
            ready,
            key=lambda item: (_flow_tail(chains, state, item), -item),
            reverse=True,
        )[:top_k]
        candidates = [ChainAction.flow(index) for index in ranked]
        if base_action not in candidates:
            candidates.append(base_action)
        if allow_wait and active_computes(state):
            candidates.append(ChainAction.wait())
        scored = []
        for action in dict.fromkeys(candidates):
            successor, duration = advance(chains, state, action)
            score = duration + _completion_cost(chains, successor, base_policy)
            scored.append((score, action != base_action, action.kind == "wait", action))
        return min(scored, key=lambda item: item[:3])[3]

    result = _simulate_actions(chains, choose)
    return replace(result, fallback=fallback)


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

    @lru_cache(maxsize=None)
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
    return ChainSearchResult(
        optimum, (), explored, (perf_counter() - started) * 1000
    )


def _feasible_within(
    chains: tuple[ParallelChain, ...],
    horizon: int,
    *,
    optional_idle: bool,
    max_states: int,
) -> tuple[bool, int]:
    canonical = _canonicalizer(chains)
    explored = 0

    @lru_cache(maxsize=None)
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
            chains,
            middle,
            optional_idle=optional_idle,
            max_states=max_states,
        )
        explored += states
        if feasible:
            upper = middle
        else:
            lower = middle + 1
    return ChainSearchResult(
        lower, (), explored, (perf_counter() - started) * 1000
    )


def beam_search(
    chains: tuple[ParallelChain, ...],
    *,
    width: int,
    allow_wait: bool,
    state_budget: int = 100_000,
    time_limit_s: float = 2.0,
) -> ChainSearchResult:
    started = perf_counter()
    incumbent = schedule_priority(chains)
    best_time = incumbent.makespan
    best_actions = incumbent.actions
    frontier: dict[ChainState, tuple[int, tuple[ChainAction, ...]]] = {
        initial_state(chains): (0, ())
    }
    explored = 0
    fallback = False
    while frontier:
        successors: dict[ChainState, tuple[int, tuple[ChainAction, ...]]] = {}
        for state, (elapsed, path) in frontier.items():
            for action in legal_actions(chains, state, optional_idle=allow_wait):
                successor, duration = advance(chains, state, action)
                new_elapsed = elapsed + duration
                explored += 1
                if explored > state_budget or perf_counter() - started > time_limit_s:
                    fallback = True
                    frontier = {}
                    break
                if is_finished(chains, successor):
                    if new_elapsed < best_time:
                        best_time = new_elapsed
                        best_actions = (*path, action)
                    continue
                if new_elapsed + residual_bounds(chains, successor)["combined"] >= best_time:
                    continue
                old = successors.get(successor)
                if old is None or new_elapsed < old[0]:
                    successors[successor] = (new_elapsed, (*path, action))
            if not frontier:
                break
        if not successors:
            break
        ranked = sorted(
            successors.items(),
            key=lambda item: (
                item[1][0] + residual_bounds(chains, item[0])["combined"],
                item[1][0] + _completion_cost(chains, item[0], "dynamic_tail"),
            ),
        )[:width]
        frontier = dict(ranked)
    return ChainSearchResult(
        best_time,
        best_actions,
        explored,
        (perf_counter() - started) * 1000,
        fallback,
    )


def monte_carlo_best(
    chains: tuple[ParallelChain, ...],
    *,
    samples: int,
    seed: int,
    allow_wait: bool,
    wait_probability: float = 0.15,
) -> ChainSearchResult:
    started = perf_counter()
    rng = random.Random(seed)
    incumbent = schedule_priority(chains)
    best_time = incumbent.makespan
    best_actions = incumbent.actions
    for _ in range(samples):
        def choose(state: ChainState) -> ChainAction:
            actions = list(legal_actions(chains, state, optional_idle=allow_wait))
            waits = [action for action in actions if action.kind == "wait"]
            flows = [action for action in actions if action.kind == "flow"]
            if waits and flows and rng.random() < wait_probability:
                return waits[0]
            if flows:
                if rng.random() < 0.7:
                    flows.sort(
                        key=lambda action: _flow_tail(
                            chains, state, int(action.chain)
                        ),
                        reverse=True,
                    )
                    return rng.choice(flows[: min(2, len(flows))])
                return rng.choice(flows)
            return waits[0]

        candidate = _simulate_actions(chains, choose)
        if candidate.makespan < best_time:
            best_time = candidate.makespan
            best_actions = candidate.actions
    return ChainSearchResult(
        best_time,
        best_actions,
        samples,
        (perf_counter() - started) * 1000,
    )


def to_benchmark_dag(chains: tuple[ParallelChain, ...]):
    builder = DAGBuilder("nonpreemptive_parallel_chains", context=(("category", "r2_chain"), ("description", "Compact-chain replay DAG.")))
    flow_ids: dict[tuple[int, int], str] = {}
    for chain_index, chain in enumerate(chains):
        previous = None
        if chain.initial_delay:
            previous = builder.add(
                f"c{chain_index}_release", "compute", chain.initial_delay
            )
        for operation, (comm, compute) in enumerate(
            zip(chain.comm, chain.compute, strict=True)
        ):
            flow_id = builder.add(
                f"c{chain_index}_flow{operation}",
                "comm",
                comm,
                () if previous is None else (previous,),
            )
            flow_ids[chain_index, operation] = flow_id
            previous = builder.add(
                f"c{chain_index}_compute{operation}",
                "compute",
                compute,
                (flow_id,),
            )
    return builder.finish(), flow_ids


def verify_schedule(
    chains: tuple[ParallelChain, ...], schedule: ChainSchedule | ChainSearchResult
) -> None:
    dag, flow_ids = to_benchmark_dag(chains)
    model = NonPreeSingleModel(dag)
    compact_state = initial_state(chains)
    dag_actions: list[DAGAction] = []
    for action in schedule.actions:
        if action.kind == "wait":
            dag_actions.append(DAGAction.wait())
        else:
            assert action.chain is not None
            operation = compact_state[action.chain][0]
            dag_actions.append(DAGAction.flow(flow_ids[action.chain, operation]))
        compact_state, _duration = advance(chains, compact_state, action)
    trace = model.run(dag_actions)
    if trace.makespan != schedule.makespan or not model.is_finished(trace.final_state):
        raise AssertionError(
            f"compact/R0 replay mismatch: {schedule.makespan} vs {trace.makespan}"
        )
    assert_nonpreemptive_trace(dag, trace, mode="optional_idle")
