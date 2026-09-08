"""R2 study for non-preemptive single-channel parallel chains.

Every action completes one whole communication or waits to the next compute
completion.  The compact chain state is cross-checked against the R0 DAG state
machine and the R1 exact oracle on small instances.

Use the public runner documented in the repository ``README.md``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Literal

def chains_from_dag(dag):
    """Build the compact chain input from a validated internal DAG."""

    from single_channel.parallel_chain.structure import parse_parallel_chain

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

from core.dag import DAGBuilder
from core.execution.nonpreemptive import (
    Action as DAGAction,
)
from core.execution.nonpreemptive import (
    NonPreeSingleModel,
)
from core.trace.nonpreemptive import assert_nonpreemptive_trace

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


def _public_projection(
    chains: tuple[ParallelChain, ...],
    model: NonPreeSingleModel,
    state,
    flow_ids: dict[tuple[int, int], str],
) -> ChainState:
    """Project a public simulator state for ranking only.

    This projection never advances time.  All state transitions in formal
    schedulers remain owned by ``NonPreeSingleModel``.
    """

    runtimes = {task.task_id: runtime for task, runtime in zip(model.tasks, state.tasks, strict=True)}
    values: list[tuple[int, int]] = []
    for chain_index, chain in enumerate(chains):
        completed = 0
        release = runtimes.get(f"c{chain_index}_release")
        cooldown = release.remaining if release is not None and release.status == "running" else 0
        for operation in range(len(chain.comm)):
            flow_id = flow_ids[chain_index, operation]
            if runtimes[flow_id].status == "completed":
                completed += 1
            compute_id = f"c{chain_index}_compute{operation}"
            compute = runtimes[compute_id]
            if compute.status == "running":
                cooldown = compute.remaining
        values.append((completed, cooldown))
    return tuple(values)


def _public_action(
    action: ChainAction,
    chains: tuple[ParallelChain, ...],
    model: NonPreeSingleModel,
    state,
    flow_ids: dict[tuple[int, int], str],
) -> DAGAction:
    if action.kind == "wait":
        return DAGAction.wait()
    if action.chain is None:
        raise ValueError(f"flow action has no chain: {action}")
    operation = _public_projection(chains, model, state, flow_ids)[action.chain][0]
    return DAGAction.flow(flow_ids[action.chain, operation])


def _chain_action_from_public(
    chains: tuple[ParallelChain, ...],
    model: NonPreeSingleModel,
    state,
    action: DAGAction,
    flow_ids: dict[tuple[int, int], str],
) -> ChainAction:
    if action.kind == "wait":
        return ChainAction.wait()
    if action.task_id is None:
        raise ValueError(f"flow action has no task: {action}")
    for (chain, operation), task_id in flow_ids.items():
        if task_id == action.task_id:
            return ChainAction.flow(chain)
    raise ValueError(f"unknown parallel-chain flow: {action.task_id}")


def _public_schedule(
    chains: tuple[ParallelChain, ...],
    choose,
    *,
    allow_wait: bool,
    fallback: bool = False,
) -> ChainSchedule:
    """Run a chain policy through the public non-preemptive simulator."""

    started = perf_counter()
    dag, flow_ids = to_benchmark_dag(chains)
    model = NonPreeSingleModel(dag)
    state = model.initial_state()
    actions: list[ChainAction] = []
    network_busy = voluntary_idle = forced_idle = 0
    compute_active_time = overlap_time = 0
    while not model.is_finished(state):
        projection = _public_projection(chains, model, state, flow_ids)
        ready = model.ready_flows(state)
        active = model.active_computes(state)
        selected = choose(projection, ready, bool(active), model, state, flow_ids)
        if selected.kind == "wait" and not allow_wait and ready:
            selected = ChainAction.flow(select_flow("dynamic_tail", chains, projection, ready_chains(chains, projection)))
        dag_action = _public_action(selected, chains, model, state, flow_ids)
        transition = model.step(state, dag_action)
        duration = transition.after.time - state.time
        if selected.kind == "wait":
            if ready:
                voluntary_idle += duration
            else:
                forced_idle += duration
        else:
            network_busy += duration
        compute_intervals = [
            interval for interval in transition.intervals if interval.kind == "compute"
        ]
        compute_active_time += sum(interval.end - interval.start for interval in compute_intervals)
        if selected.kind == "flow" and any(
            interval.start < transition.after.time and interval.end > transition.before.time
            for interval in compute_intervals
        ):
            overlap_time += duration
        actions.append(selected)
        state = transition.after
    dag_actions = []
    replay_state = model.initial_state()
    for action in actions:
        dag_action = _public_action(action, chains, model, replay_state, flow_ids)
        dag_actions.append(dag_action)
        replay_state = model.step(replay_state, dag_action).after
    trace = model.run(dag_actions)
    assert_nonpreemptive_trace(dag, trace, mode="optional_idle" if allow_wait else "work_conserving")
    return ChainSchedule(
        trace.makespan,
        tuple(actions),
        network_busy,
        voluntary_idle,
        forced_idle,
        compute_active_time,
        trace.makespan * len(chains),
        overlap_time,
        (perf_counter() - started) * 1000,
        fallback,
    )


def _public_completion_cost(
    chains: tuple[ParallelChain, ...],
    model: NonPreeSingleModel,
    state,
    action: ChainAction,
    flow_ids: dict[tuple[int, int], str],
    policy: str,
) -> int:
    """Complete a public state with a public-model priority policy."""

    dag_action = _public_action(action, chains, model, state, flow_ids)
    state = model.step(state, dag_action).after
    while not model.is_finished(state):
        projection = _public_projection(chains, model, state, flow_ids)
        ready = model.ready_flows(state)
        if ready:
            compact_ready = ready_chains(chains, projection)
            next_action = ChainAction.flow(select_flow(policy, chains, projection, compact_ready))
        elif model.active_computes(state):
            next_action = ChainAction.wait()
        else:
            raise RuntimeError("unfinished public state has no legal action")
        state = model.step(
            state, _public_action(next_action, chains, model, state, flow_ids)
        ).after
    return state.time


def schedule_priority(
    chains: tuple[ParallelChain, ...], policy: str = "dynamic_tail"
) -> ChainSchedule:
    return _public_schedule(
        chains,
        lambda state, _ready, _active, _model, _public_state, _flow_ids: priority_action(policy, chains, state),
        allow_wait=False,
    )


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

    def choose(
        state: ChainState,
        ready_ids: tuple[str, ...],
        active: bool,
        model: NonPreeSingleModel,
        public_state,
        flow_ids: dict[tuple[int, int], str],
    ) -> ChainAction:
        nonlocal fallback
        base_action = priority_action(base_policy, chains, state)
        if perf_counter() - started > time_limit_s:
            fallback = True
            return base_action
        ready = ready_chains(chains, state)
        ranked = sorted(ready, key=lambda item: (_flow_tail(chains, state, item), -item), reverse=True)[:top_k]
        candidates = [ChainAction.flow(index) for index in ranked]
        if base_action not in candidates:
            candidates.append(base_action)
        if allow_wait and active:
            candidates.append(ChainAction.wait())
        scored = [
            (
                _public_completion_cost(
                    chains, model, public_state, candidate, flow_ids, base_policy
                ),
                candidate.kind == "wait",
                candidate.chain if candidate.chain is not None else -1,
                candidate,
            )
            for candidate in dict.fromkeys(candidates)
        ]
        return min(scored, key=lambda item: item[:3])[3]

    result = _public_schedule(chains, choose, allow_wait=allow_wait, fallback=fallback)
    return replace(result, fallback=fallback)


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
    dag, flow_ids = to_benchmark_dag(chains)
    model = NonPreeSingleModel(dag)
    initial = model.initial_state()
    frontier = {(initial,): (0, ())}
    explored = 0
    fallback = False
    while frontier:
        successors = {}
        for (state,), (elapsed, path) in frontier.items():
            legal = model.legal_actions(state)
            if not allow_wait:
                legal = tuple(action for action in legal if action.kind != "wait")
            for dag_action in legal:
                transition = model.step(state, dag_action)
                successor = transition.after
                duration = successor.time - state.time
                new_elapsed = elapsed + duration
                explored += 1
                if explored > state_budget or perf_counter() - started > time_limit_s:
                    fallback = True
                    frontier = {}
                    break
                chain_action = _chain_action_from_public(
                    chains, model, state, dag_action, flow_ids
                )
                if model.is_finished(successor):
                    if new_elapsed < best_time:
                        best_time = new_elapsed
                        best_actions = (*path, chain_action)
                    continue
                projection = _public_projection(chains, model, successor, flow_ids)
                if new_elapsed + residual_bounds(chains, projection)["combined"] >= best_time:
                    continue
                key = (successor,)
                old = successors.get(key)
                if old is None or new_elapsed < old[0]:
                    successors[key] = (new_elapsed, (*path, chain_action))
            if not frontier:
                break
        if not successors:
            break
        ranked = sorted(
            successors.items(),
            key=lambda item: (
                item[1][0]
                + residual_bounds(
                    chains, _public_projection(chains, model, item[0][0], flow_ids)
                )["combined"],
                item[1][0],
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
        def choose(
            state: ChainState,
            _ready_ids,
            _active,
            _model,
            public_state,
            flow_ids,
        ) -> ChainAction:
            public_actions = list(_model.legal_actions(public_state))
            if not allow_wait and _ready_ids:
                public_actions = [
                    action for action in public_actions if action.kind != "wait"
                ]
            actions = [
                _chain_action_from_public(
                    chains, _model, public_state, action, flow_ids
                )
                for action in public_actions
            ]
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

        candidate = _public_schedule(chains, choose, allow_wait=allow_wait)
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
    dag_actions: list[DAGAction] = []
    state = model.initial_state()
    for action in schedule.actions:
        if action.kind == "wait":
            dag_action = DAGAction.wait()
        else:
            assert action.chain is not None
            runtimes = {
                task.task_id: runtime
                for task, runtime in zip(model.tasks, state.tasks, strict=True)
            }
            operation = sum(
                runtimes[flow_ids[action.chain, index]].status == "completed"
                for index in range(len(chains[action.chain].comm))
            )
            dag_action = DAGAction.flow(flow_ids[action.chain, operation])
        dag_actions.append(dag_action)
        state = model.step(state, dag_action).after
    trace = model.run(dag_actions)
    if trace.makespan != schedule.makespan or not model.is_finished(trace.final_state):
        raise AssertionError(
            f"compact/R0 replay mismatch: {schedule.makespan} vs {trace.makespan}"
        )
    assert_nonpreemptive_trace(dag, trace, mode="optional_idle")
