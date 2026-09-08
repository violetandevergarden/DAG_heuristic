"""Stage 1 policies and compact Exact for preemptive parallel chains.

All time advancement is delegated to :class:`PreeSingleModel`.  This module
only validates the family contract, chooses legal communications, and searches
states produced by that public transition system.
"""

from __future__ import annotations

import random
from functools import cache
from time import perf_counter

from core.dag import DAG
from core.execution.preemptive import (
    Action,
    PreemptiveScheduleResult,
    PreeSingleModel,
    ScheduleState,
    result_from_trace,
)
from core.trace.preemptive import assert_preemptive_trace
from single_channel.parallel_chain.structure import (
    ParallelChainInstance,
    parse_parallel_chain,
)


def schedule_longest_tail(dag: DAG) -> PreemptiveScheduleResult:
    """Choose the largest residual tail after the candidate communication."""

    return schedule_priority(dag, "longest_tail")


def schedule_priority(
    dag: DAG,
    priority: str = "longest_tail",
) -> PreemptiveScheduleResult:
    """Run a deterministic Stage 1 work-conserving priority.

    ``fifo`` uses the first event time at which a communication becomes
    eligible and retains that arrival time after suspension. ``longest_delay``
    is the immediately following compute segment. ``longest_tail`` excludes
    the candidate's remaining communication work; ``lrpt`` includes it.
    Every tie is resolved by task ID.
    """

    instance = parse_parallel_chain(dag)
    model = PreeSingleModel(dag)
    state = model.initial_state()
    arrivals: dict[str, int] = {}
    actions: list[Action] = []
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        for task_id in eligible:
            arrivals.setdefault(task_id, state.time)
        if not eligible:
            action = Action.wait()
        else:
            tails = residual_tail(model, state) if _uses_tail(priority) else None
            action = Action.run(
                min(
                    eligible,
                    key=lambda task_id: _priority_key(
                        instance,
                        model,
                        state,
                        task_id,
                        priority,
                        arrivals,
                        tails,
                    ),
                )
            )
        actions.append(action)
        state = model.step(state, action).after
    return _validated_result(model, tuple(actions))


def schedule_rollout(
    dag: DAG,
    *,
    top_k: int = 2,
    candidate_mode: str = "longest_tail",
    depth: int = 1,
) -> PreemptiveScheduleResult:
    """Finite-depth event rollout with a residual Longest-tail completion.

    ``candidate_mode`` is explicit: ``longest_tail`` excludes the current
    communication, while ``lrpt`` includes its remaining work.  The baseline
    Longest-tail action is always included in the shortlist. ``depth`` counts
    communication choices, not forced-idle transitions; depth one reproduces
    the original one-event rollout.
    """

    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if depth <= 0:
        raise ValueError("depth must be positive")
    instance = parse_parallel_chain(dag)
    model = PreeSingleModel(dag)
    state = model.initial_state()
    actions: list[Action] = []
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        if not eligible:
            action = Action.wait()
        else:
            tails = residual_tail(model, state)
            ranked = _rank_candidates(
                instance,
                model,
                state,
                eligible,
                top_k,
                candidate_mode,
                tails,
            )
            memo: dict[tuple[int, tuple], int] = {}
            candidates: list[tuple[int, str, Action]] = []
            for task_id in ranked:
                first = Action.run(task_id)
                after = model.step(state, first).after
                finish = after.time + _rollout_remaining_cost(
                    instance,
                    model,
                    after,
                    depth - 1,
                    top_k,
                    candidate_mode,
                    memo,
                )
                candidates.append((finish, task_id, first))
            action = min(candidates)[2]
        actions.append(action)
        state = model.step(state, action).after
    return _validated_result(model, tuple(actions))


def beam_search(dag: DAG, *, width: int = 8) -> PreemptiveScheduleResult:
    """Deterministic event-state beam with a Longest-tail incumbent.

    For an identical ordered frontier key, future residual cost is identical.
    Keeping only the representative with the earliest absolute time is thus a
    time-dominance rule, not merely an implementation-level duplicate filter.
    Equal-time representatives use the action signature for deterministic
    replay.
    """

    if width <= 0:
        raise ValueError("width must be positive")
    instance = parse_parallel_chain(dag)
    model = PreeSingleModel(dag)
    initial = model.initial_state()
    frontier: list[tuple[ScheduleState, tuple[Action, ...]]] = [(initial, ())]
    incumbent = schedule_longest_tail(dag)
    best_actions: tuple[Action, ...] | None = None
    while frontier:
        children: dict[tuple, tuple[ScheduleState, tuple[Action, ...]]] = {}
        for state, prefix in frontier:
            if model.is_finished(state):
                best_actions = prefix
                break
            for action in model.legal_actions(state):
                after = model.step(state, action).after
                key = _compact_key(instance, model, after)
                candidate = (after, (*prefix, action))
                old = children.get(key)
                if old is None or (
                    after.time,
                    _action_signature(candidate[1]),
                ) < (
                    old[0].time,
                    _action_signature(old[1]),
                ):
                    children[key] = candidate
        if best_actions is not None:
            break
        scored = []
        for state, prefix in children.values():
            suffix = _complete_actions(instance, model, state)
            predicted = _apply_actions(model, state, suffix).time
            scored.append(
                (
                    predicted,
                    state.time,
                    len(prefix),
                    _action_signature(prefix),
                    prefix,
                    state,
                )
            )
        scored.sort(key=lambda item: item[:4])
        frontier = [(item[5], item[4]) for item in scored[:width]]
    if best_actions is None:
        return incumbent
    candidate = _validated_result(model, best_actions)
    return min((incumbent, candidate), key=lambda item: (item.makespan, item.dispatches))


def exact_oracle(
    dag: DAG,
    *,
    max_states: int = 500_000,
    time_limit_s: float | None = None,
    symmetry_reduction: bool = True,
) -> PreemptiveScheduleResult:
    """Exact memoized search keyed by lossless per-chain frontiers.

    For a strict path, all completed tasks form a prefix and exactly one task
    is the unfinished frontier.  Its position and remaining work completely
    determine that chain's future.  Absolute time, start timestamps, and
    whether an eligible communication has previously run do not affect future
    evolution under zero-cost resume, so they are safely omitted.  When
    ``symmetry_reduction`` is enabled, chains with identical kind/duration
    sequences are additionally represented as a multiset of frontier states.
    The proof and assumptions are recorded in the Stage 1 compact-state proof.
    """

    if max_states <= 0:
        raise ValueError("max_states must be positive")
    instance = parse_parallel_chain(dag)
    model = PreeSingleModel(dag)
    initial = model.initial_state()
    started = perf_counter()
    states = 0
    duplicates = 0
    pruned = 0
    representative: dict[tuple, ScheduleState] = {}
    symmetry_groups = _chain_type_groups(instance, model) if symmetry_reduction else None

    @cache
    def search(state_key: tuple) -> int:
        nonlocal states, duplicates, pruned
        states += 1
        if states > max_states:
            raise RuntimeError(f"parallel-chain exact oracle exceeded {max_states} states")
        if time_limit_s is not None and perf_counter() - started > time_limit_s:
            raise TimeoutError("parallel-chain exact oracle exceeded time limit")
        state = representative[state_key]
        if model.is_finished(state):
            return 0

        incumbent_actions = _complete_actions(instance, model, state)
        best_cost = _apply_actions(model, state, incumbent_actions).time - state.time
        candidates = []
        for action in model.legal_actions(state):
            transition = model.step(state, action)
            elapsed = transition.after.time - state.time
            bound = elapsed + _remaining_lower_bound(instance, model, transition.after)
            candidates.append((bound, action.task_id or "", action, transition.after, elapsed))
        for bound, _task_id, action, after, elapsed in sorted(candidates):
            if bound > best_cost:
                pruned += 1
                continue
            child_key = _compact_key(instance, model, after, symmetry_groups)
            if child_key in representative:
                duplicates += 1
            else:
                representative[child_key] = after
            best_cost = min(best_cost, elapsed + search(child_key))
        return best_cost

    initial_key = _compact_key(instance, model, initial, symmetry_groups)
    representative[initial_key] = initial
    root_lower_bound = _remaining_lower_bound(instance, model, initial)
    search(initial_key)

    actions: list[Action] = []
    state = initial
    while not model.is_finished(state):
        state_key = _compact_key(instance, model, state, symmetry_groups)
        optimum = search(state_key)
        selected: tuple[Action, ScheduleState] | None = None
        for action in sorted(
            model.legal_actions(state), key=lambda item: (item.kind, item.task_id or "")
        ):
            transition = model.step(state, action)
            elapsed = transition.after.time - state.time
            if elapsed + _remaining_lower_bound(instance, model, transition.after) > optimum:
                continue
            child_key = _compact_key(instance, model, transition.after, symmetry_groups)
            representative.setdefault(child_key, transition.after)
            if elapsed + search(child_key) == optimum:
                selected = action, transition.after
                break
        if selected is None:
            raise AssertionError("compact Exact could not reconstruct an optimal action")
        action, state = selected
        actions.append(action)

    result = _validated_result(model, tuple(actions))
    return result.with_stats(
        explored_states=states,
        deduplicated_states=duplicates,
        pruned_states=pruned,
        lower_bound=root_lower_bound,
        runtime_ms=(perf_counter() - started) * 1000,
        status="optimal",
    )


def monte_carlo(
    dag: DAG,
    *,
    samples: int = 64,
    seed: int = 0,
) -> PreemptiveScheduleResult:
    """Historical reproducible baseline; intentionally absent from registry."""

    parse_parallel_chain(dag)
    model = PreeSingleModel(dag)
    rng = random.Random(seed)
    candidates = [schedule_longest_tail(dag)]
    for _ in range(samples):
        state = model.initial_state()
        actions: list[Action] = []
        while not model.is_finished(state):
            eligible = model.eligible_communications(state)
            action = Action.run(rng.choice(eligible)) if eligible else Action.wait()
            actions.append(action)
            state = model.step(state, action).after
        candidates.append(_validated_result(model, tuple(actions)))
    return min(candidates, key=lambda item: (item.makespan, item.dispatches))


def residual_tail(model: PreeSingleModel, state: ScheduleState) -> dict[str, int]:
    """Return the residual longest path including each task's own remainder."""

    order = model.dag.topological_order()
    tasks = model.task_map
    children: dict[str, list[str]] = {task_id: [] for task_id in order}
    for task in tasks.values():
        for dependency in task.deps:
            children[dependency].append(task.task_id)
    tail: dict[str, int] = {}
    for task_id in reversed(order):
        runtime = model.task_runtime(state, task_id)
        if runtime.status == "completed":
            own = 0
        elif runtime.status in {"running", "suspended"}:
            own = runtime.remaining
        else:
            own = tasks[task_id].duration
        tail[task_id] = own + max((tail[child] for child in children[task_id]), default=0)
    return tail


def _priority_key(
    instance: ParallelChainInstance,
    model: PreeSingleModel,
    state: ScheduleState,
    task_id: str,
    priority: str,
    arrivals: dict[str, int],
    tails: dict[str, int] | None,
) -> tuple[int, str]:
    runtime = model.task_runtime(state, task_id)
    remaining = runtime.remaining or model.task_map[task_id].duration
    if priority == "fifo":
        return arrivals[task_id], task_id
    if priority == "spt":
        return remaining, task_id
    if priority == "lpt":
        return -remaining, task_id
    if priority == "longest_delay":
        score = _immediate_compute_delay(instance, model, state, task_id)
    elif priority == "longest_tail":
        if tails is None:
            raise AssertionError("longest_tail requires a residual-tail snapshot")
        score = tails[task_id] - remaining
    elif priority == "lrpt":
        if tails is None:
            raise AssertionError("lrpt requires a residual-tail snapshot")
        score = tails[task_id]
    else:
        raise ValueError(f"unknown Stage 1 priority: {priority}")
    return -score, task_id


def _immediate_compute_delay(
    instance: ParallelChainInstance,
    model: PreeSingleModel,
    state: ScheduleState,
    task_id: str,
) -> int:
    chain_index, position = instance.task_to_chain_position[task_id]
    chain = instance.chains[chain_index]
    if position + 1 == len(chain):
        return 0
    child = chain[position + 1]
    task = model.task_map[child]
    if task.kind != "compute":
        raise AssertionError("validated parallel chain stopped alternating")
    runtime = model.task_runtime(state, child)
    return runtime.remaining if runtime.status == "running" else task.duration


def _rank_candidates(
    instance: ParallelChainInstance,
    model: PreeSingleModel,
    state: ScheduleState,
    eligible: tuple[str, ...],
    top_k: int,
    mode: str,
    tails: dict[str, int],
) -> list[str]:
    if mode not in {"longest_tail", "lrpt"}:
        raise ValueError("candidate_mode must be 'longest_tail' or 'lrpt'")
    arrivals = {task_id: state.time for task_id in eligible}
    ranked = sorted(
        eligible,
        key=lambda task_id: _priority_key(instance, model, state, task_id, mode, arrivals, tails),
    )
    baseline = min(
        eligible,
        key=lambda task_id: _priority_key(
            instance,
            model,
            state,
            task_id,
            "longest_tail",
            arrivals,
            tails,
        ),
    )
    selected = ranked[:top_k]
    if baseline not in selected:
        selected[-1] = baseline
        selected.sort(
            key=lambda task_id: _priority_key(
                instance, model, state, task_id, mode, arrivals, tails
            )
        )
    return selected


def _rollout_remaining_cost(
    instance: ParallelChainInstance,
    model: PreeSingleModel,
    state: ScheduleState,
    depth: int,
    top_k: int,
    candidate_mode: str,
    memo: dict[tuple[int, tuple], int],
) -> int:
    if model.is_finished(state):
        return 0
    key = (depth, _compact_key(instance, model, state))
    cached = memo.get(key)
    if cached is not None:
        return cached
    if depth == 0:
        suffix = _complete_actions(instance, model, state)
        cost = _apply_actions(model, state, suffix).time - state.time
        memo[key] = cost
        return cost
    eligible = model.eligible_communications(state)
    if not eligible:
        transition = model.step(state, Action.wait())
        elapsed = transition.after.time - state.time
        cost = elapsed + _rollout_remaining_cost(
            instance,
            model,
            transition.after,
            depth,
            top_k,
            candidate_mode,
            memo,
        )
        memo[key] = cost
        return cost
    tails = residual_tail(model, state)
    ranked = _rank_candidates(
        instance,
        model,
        state,
        eligible,
        top_k,
        candidate_mode,
        tails,
    )
    best: tuple[int, str] | None = None
    for task_id in ranked:
        transition = model.step(state, Action.run(task_id))
        elapsed = transition.after.time - state.time
        cost = elapsed + _rollout_remaining_cost(
            instance,
            model,
            transition.after,
            depth - 1,
            top_k,
            candidate_mode,
            memo,
        )
        candidate = cost, task_id
        if best is None or candidate < best:
            best = candidate
    if best is None:
        raise AssertionError("eligible rollout state produced no candidate")
    memo[key] = best[0]
    return best[0]


def _complete_actions(
    instance: ParallelChainInstance,
    model: PreeSingleModel,
    state: ScheduleState,
) -> tuple[Action, ...]:
    actions: list[Action] = []
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        if eligible:
            arrivals = {task_id: state.time for task_id in eligible}
            tails = residual_tail(model, state)
            task_id = min(
                eligible,
                key=lambda item: _priority_key(
                    instance,
                    model,
                    state,
                    item,
                    "longest_tail",
                    arrivals,
                    tails,
                ),
            )
            action = Action.run(task_id)
        else:
            action = Action.wait()
        actions.append(action)
        state = model.step(state, action).after
    return tuple(actions)


def _uses_tail(priority: str) -> bool:
    return priority in {"longest_tail", "lrpt"}


def _chain_type_groups(
    instance: ParallelChainInstance,
    model: PreeSingleModel,
) -> tuple[tuple[int, ...], ...]:
    """Group chains whose complete kind/duration sequences are isomorphic."""

    tasks = model.task_map
    by_type: dict[tuple[tuple[str, int], ...], list[int]] = {}
    for chain_index, chain in enumerate(instance.chains):
        signature = tuple((tasks[task_id].kind, tasks[task_id].duration) for task_id in chain)
        by_type.setdefault(signature, []).append(chain_index)
    return tuple(tuple(by_type[signature]) for signature in sorted(by_type))


def _compact_key(
    instance: ParallelChainInstance,
    model: PreeSingleModel,
    state: ScheduleState,
    symmetry_groups: tuple[tuple[int, ...], ...] | None = None,
) -> tuple:
    key: list[tuple[int, int]] = []
    tasks = model.task_map
    for chain in instance.chains:
        for position, task_id in enumerate(chain):
            runtime = model.task_runtime(state, task_id)
            if runtime.status == "completed":
                continue
            remaining = runtime.remaining or tasks[task_id].duration
            key.append((position, remaining))
            break
        else:
            key.append((len(chain), 0))
    if symmetry_groups is None:
        return tuple(key)
    return tuple(
        tuple(sorted(key[chain_index] for chain_index in group)) for group in symmetry_groups
    )


def _remaining_lower_bound(
    instance: ParallelChainInstance,
    model: PreeSingleModel,
    state: ScheduleState,
) -> int:
    tasks = model.task_map
    communication = 0
    longest_path = 0
    longest_compute = 0
    for chain in instance.chains:
        path = 0
        compute = 0
        for task_id in chain:
            runtime = model.task_runtime(state, task_id)
            if runtime.status == "completed":
                continue
            remaining = runtime.remaining or tasks[task_id].duration
            path += remaining
            if tasks[task_id].kind == "comm":
                communication += remaining
            else:
                compute += remaining
        longest_path = max(longest_path, path)
        longest_compute = max(longest_compute, compute)
    return max(communication, longest_compute, longest_path)


def _apply_actions(
    model: PreeSingleModel,
    state: ScheduleState,
    actions: tuple[Action, ...],
) -> ScheduleState:
    for action in actions:
        state = model.step(state, action).after
    return state


def _validated_result(
    model: PreeSingleModel,
    actions: tuple[Action, ...],
) -> PreemptiveScheduleResult:
    trace = model.run(actions)
    assert_preemptive_trace(model, trace)
    return result_from_trace(trace)


def _action_signature(actions: tuple[Action, ...]) -> tuple[tuple[str, str], ...]:
    return tuple((action.kind, action.task_id or "") for action in actions)
