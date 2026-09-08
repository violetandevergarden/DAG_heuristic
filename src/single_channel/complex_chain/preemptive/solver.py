"""Stage 2 algorithms for single-channel communication-preemptive DAGs.

Every policy and search routine delegates event progression to
``PreeSingleModel.step``.  This module only ranks legal communications or
searches the resulting public event states.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Literal

from core.dag import DAG
from core.execution.preemptive import (
    Action,
    PreemptiveScheduleResult,
    PreeSingleModel,
    ScheduleState,
    result_from_trace,
)
from core.trace.preemptive import assert_preemptive_trace

PriorityName = str
StateKey = tuple[object, ...]


@dataclass
class _SearchStats:
    explored: int = 0
    generated: int = 0
    duplicates: int = 0
    incumbent_prunes: int = 0
    lower_bound_prunes: int = 0
    peak_states: int = 0
    expanded_nodes: int = 0
    evaluated_candidates: int = 0
    fallback_count: int = 0


class _BudgetExceeded(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def schedule_longest_tail(dag: DAG) -> PreemptiveScheduleResult:
    """Schedule the largest exclusive residual downstream tail first."""

    return schedule_priority(dag, "longest_tail")


def schedule_priority(
    dag: DAG,
    priority: PriorityName = "longest_tail",
) -> PreemptiveScheduleResult:
    """Run a deterministic work-conserving Stage 2 priority policy.

    FIFO is history-aware: the first event time at which a communication is
    eligible is retained across later pauses.  All other policies are
    memoryless functions of the current residual state.  Ties use task ID.
    """

    validate_complex_chain(dag)
    model = PreeSingleModel(dag)
    state = model.initial_state()
    actions: list[Action] = []
    first_eligible: dict[str, int] = {}
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        for task_id in eligible:
            first_eligible.setdefault(task_id, state.time)
        if not eligible:
            action = Action.wait()
        else:
            tail = residual_tail(model, state, eligible)
            if priority == "fifo":
                selected = min(eligible, key=lambda item: (first_eligible[item], item))
            elif priority == "fixed_order":
                selected = min(eligible)
            else:
                selected = min(
                    eligible,
                    key=lambda item: _priority_key(model, state, item, priority, tail),
                )
            action = Action.run(selected)
        actions.append(action)
        state = model.step(state, action).after
    return _result(model, actions)


def schedule_rollout(
    dag: DAG,
    *,
    top_k: int | None = 2,
    depth: int = 1,
    candidate_mode: str = "longest_tail",
    completion_priority: str = "longest_tail",
    max_expansions: int | None = None,
    time_limit_s: float | None = None,
    use_memo: bool = True,
) -> PreemptiveScheduleResult:
    """Receding-horizon event rollout with an explicit decision depth.

    ``depth`` counts communication decisions only; forced-idle transitions do
    not consume depth.  The completion-policy action is always retained in a
    finite shortlist, so an unexhausted search has a baseline incumbent.
    Deterministic expansion and wall-clock budgets fall back to the completion
    policy and are reported in the result.
    """

    validate_complex_chain(dag)
    if depth < 1:
        raise ValueError("rollout depth must be at least one")
    if top_k is not None and top_k < 1:
        raise ValueError("rollout top_k must be positive or None")
    model = PreeSingleModel(dag)
    state = model.initial_state()
    actions: list[Action] = []
    stats = _SearchStats()
    started = perf_counter()
    termination_reason: str | None = None
    memo: dict[tuple[int, StateKey], int] = {}

    def check_budget() -> None:
        if max_expansions is not None and stats.expanded_nodes >= max_expansions:
            raise _BudgetExceeded("node_expansion_limit")
        if time_limit_s is not None and perf_counter() - started >= time_limit_s:
            raise _BudgetExceeded("time_limit")

    def evaluate(current: ScheduleState, remaining_depth: int) -> int:
        """Return residual completion cost, not an absolute finish time.

        The normalized key intentionally omits absolute time.  Caching a
        residual cost therefore preserves the future-equivalence proof,
        whereas caching an absolute makespan would not.
        """

        forced_state, _forced = _advance_forced_idle(model, current)
        forced_elapsed = forced_state.time - current.time
        if model.is_finished(forced_state):
            return forced_elapsed
        memo_key = (remaining_depth, _normalized_state_key(forced_state))
        if use_memo:
            cached = memo.get(memo_key)
            if cached is not None:
                stats.duplicates += 1
                return forced_elapsed + cached
        if remaining_depth == 0:
            suffix = _complete_actions(model, forced_state, completion_priority)
            residual = _apply_actions(model, forced_state, suffix).time - forced_state.time
            if use_memo:
                memo[memo_key] = residual
            return forced_elapsed + residual
        check_budget()
        stats.expanded_nodes += 1
        eligible = model.eligible_communications(forced_state)
        tail = residual_tail(model, forced_state, eligible)
        ranked = _rank_candidates(
            model,
            forced_state,
            eligible,
            tail,
            top_k,
            candidate_mode,
            completion_priority,
        )
        best = float("inf")
        for task_id in ranked:
            check_budget()
            stats.evaluated_candidates += 1
            after = model.step(forced_state, Action.run(task_id)).after
            elapsed = after.time - forced_state.time
            best = min(best, elapsed + evaluate(after, remaining_depth - 1))
        residual = int(best)
        if use_memo:
            memo[memo_key] = residual
        return forced_elapsed + residual

    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        if not eligible:
            action = Action.wait()
        elif termination_reason is not None:
            action = Action.run(_baseline_choice(model, state, completion_priority))
        else:
            tail = residual_tail(model, state, eligible)
            ranked = _rank_candidates(
                model,
                state,
                eligible,
                tail,
                top_k,
                candidate_mode,
                completion_priority,
            )
            candidates: list[tuple[int, str]] = []
            try:
                for task_id in ranked:
                    check_budget()
                    stats.evaluated_candidates += 1
                    after = model.step(state, Action.run(task_id)).after
                    candidates.append(
                        (after.time - state.time + evaluate(after, depth - 1), task_id)
                    )
            except _BudgetExceeded as error:
                termination_reason = error.reason
                stats.fallback_count += 1
            selected = (
                min(candidates)[1]
                if candidates
                else _baseline_choice(model, state, completion_priority)
            )
            action = Action.run(selected)
        actions.append(action)
        state = model.step(state, action).after
    result = _result(model, actions)
    return result.with_stats(
        runtime_ms=(perf_counter() - started) * 1000,
        deduplicated_states=stats.duplicates,
        peak_states=len(memo),
        termination_reason=termination_reason,
        expanded_nodes=stats.expanded_nodes,
        evaluated_candidates=stats.evaluated_candidates,
        fallback_count=stats.fallback_count,
    )


def beam_search(
    dag: DAG,
    *,
    width: int = 8,
    horizon: int | None = None,
    max_expansions: int | None = None,
    time_limit_s: float | None = None,
) -> PreemptiveScheduleResult:
    """Decision-depth beam using the proven normalized Exact key.

    Equal normalized states are future-equivalent under the Stage 2 contract;
    the earlier representative therefore time-dominates the later one.  The
    Longest-tail completion schedule is retained as an incumbent, including
    when a horizon or budget truncates search.
    """

    validate_complex_chain(dag)
    if width < 1:
        raise ValueError("beam width must be positive")
    if horizon is not None and horizon < 1:
        raise ValueError("beam horizon must be positive or None")
    model = PreeSingleModel(dag)
    initial = model.initial_state()
    incumbent_actions = _complete_actions(model, initial, "longest_tail")
    incumbent_finish = _apply_actions(model, initial, incumbent_actions).time
    frontier: list[tuple[ScheduleState, tuple[Action, ...]]] = [(initial, ())]
    stats = _SearchStats()
    started = perf_counter()
    decision_depth = 0
    termination_reason: str | None = None

    def budget_exhausted() -> str | None:
        if max_expansions is not None and stats.expanded_nodes >= max_expansions:
            return "node_expansion_limit"
        if time_limit_s is not None and perf_counter() - started >= time_limit_s:
            return "time_limit"
        return None

    while frontier and (horizon is None or decision_depth < horizon):
        children: dict[StateKey, tuple[ScheduleState, tuple[Action, ...]]] = {}
        for raw_state, raw_prefix in frontier:
            reason = budget_exhausted()
            if reason is not None:
                termination_reason = reason
                break
            state, forced = _advance_forced_idle(model, raw_state)
            prefix = (*raw_prefix, *forced)
            if model.is_finished(state):
                if state.time < incumbent_finish:
                    incumbent_finish, incumbent_actions = state.time, prefix
                continue
            stats.expanded_nodes += 1
            for task_id in model.eligible_communications(state):
                stats.evaluated_candidates += 1
                action = Action.run(task_id)
                after = model.step(state, action).after
                after, forced_after = _advance_forced_idle(model, after)
                candidate_prefix = (*prefix, action, *forced_after)
                suffix = _complete_actions(model, after, "longest_tail")
                predicted = _apply_actions(model, after, suffix).time
                if predicted < incumbent_finish:
                    incumbent_finish = predicted
                    incumbent_actions = (*candidate_prefix, *suffix)
                key = _normalized_state_key(after)
                old = children.get(key)
                candidate = (after, candidate_prefix)
                if old is None or after.time < old[0].time:
                    if old is not None:
                        stats.duplicates += 1
                    children[key] = candidate
                else:
                    stats.duplicates += 1
        if termination_reason is not None:
            stats.fallback_count += 1
            break
        scored: list[tuple[int, int, tuple[Action, ...], ScheduleState]] = []
        for state, prefix in children.values():
            suffix = _complete_actions(model, state, "longest_tail")
            predicted = _apply_actions(model, state, suffix).time
            scored.append((predicted, state.time, prefix, state))
        scored.sort(key=lambda item: (item[0], item[1], _action_key(item[2])))
        frontier = [(item[3], item[2]) for item in scored[:width]]
        stats.peak_states = max(stats.peak_states, len(frontier))
        decision_depth += 1

    result = _result(model, incumbent_actions)
    return result.with_stats(
        runtime_ms=(perf_counter() - started) * 1000,
        deduplicated_states=stats.duplicates,
        peak_states=stats.peak_states,
        termination_reason=termination_reason,
        expanded_nodes=stats.expanded_nodes,
        evaluated_candidates=stats.evaluated_candidates,
        fallback_count=stats.fallback_count,
    )


def monte_carlo(
    dag: DAG,
    *,
    samples: int = 64,
    seed: int = 0,
) -> PreemptiveScheduleResult:
    """Historical reproducible sampler, retained outside the active registry."""

    validate_complex_chain(dag)
    model = PreeSingleModel(dag)
    rng = random.Random(seed)
    candidates: list[PreemptiveScheduleResult] = [schedule_longest_tail(dag)]
    for _ in range(samples):
        state = model.initial_state()
        actions: list[Action] = []
        while not model.is_finished(state):
            eligible = model.eligible_communications(state)
            if not eligible:
                action = Action.wait()
            else:
                tail = residual_tail(model, state, eligible)
                ranked = sorted(eligible, key=lambda item: (-tail[item], item))
                pool = ranked[: max(1, min(3, len(ranked)))] if rng.random() < 0.7 else ranked
                action = Action.run(rng.choice(pool))
            actions.append(action)
            state = model.step(state, action).after
        candidates.append(_result(model, actions))
    return min(candidates, key=lambda result: (result.makespan, result.dispatches))


def _normalized_state_key(state: ScheduleState) -> StateKey:
    """Future-equivalent key used by generic rollout and beam search."""

    return tuple((runtime.status, runtime.remaining) for runtime in state.tasks)


def residual_tail(
    model: PreeSingleModel,
    state: ScheduleState,
    roots: tuple[str, ...] | list[str] | None = None,
) -> dict[str, int]:
    """Longest residual path including each unfinished task's own work."""

    children = model.children
    if roots is None:
        order = model.task_ids
    else:
        reachable = set(roots)
        pending = list(roots)
        while pending:
            current = pending.pop()
            for child in children[current]:
                if child not in reachable:
                    reachable.add(child)
                    pending.append(child)
        order = tuple(sorted(reachable, key=model.index.__getitem__))
    tail: dict[str, int] = {}
    for task_id in reversed(order):
        tail[task_id] = _own_remaining(model, state, task_id) + max(
            (tail[child] for child in children[task_id]), default=0
        )
    return tail


def immediate_release_gain(
    model: PreeSingleModel,
    state: ScheduleState,
    task_id: str,
) -> int:
    """Sum work immediately released if ``task_id`` were completed now.

    The hypothetical closure includes zero-duration compute nodes, matching
    the simulator's automatic compute closure.  Multiple newly ready positive
    tasks are aggregated by sum; this is a local release score, not a path
    length or an end-to-end benefit claim.
    """

    tasks = model.task_map
    completed = {
        item
        for item in model.task_ids
        if model.task_runtime(state, item).status == "completed"
    }
    completed.add(task_id)
    already_ready = set(model.eligible_communications(state)) | set(model.active_computes(state))
    changed = True
    while changed:
        changed = False
        for item in model.task_ids:
            task = tasks[item]
            runtime = model.task_runtime(state, item)
            if item in completed or runtime.status != "pending":
                continue
            if task.kind == "compute" and task.duration == 0 and set(task.deps) <= completed:
                completed.add(item)
                changed = True
    released = []
    for item in model.task_ids:
        if item in completed or item in already_ready:
            continue
        task = tasks[item]
        runtime = model.task_runtime(state, item)
        if runtime.status == "pending" and set(task.deps) <= completed:
            released.append(task.duration)
    return sum(released)


def immediate_compute_delay(
    model: PreeSingleModel,
    state: ScheduleState,
    task_id: str,
) -> int:
    """Longest compute delay made ready immediately by candidate completion.

    Zero-duration compute closure is traversed, but communication work and the
    breadth/sum of newly ready tasks are deliberately excluded.  The latter is
    the separate ``immediate_release_gain`` feature.
    """

    tasks = model.task_map
    completed = {
        item
        for item in model.task_ids
        if model.task_runtime(state, item).status == "completed"
    }
    completed.add(task_id)
    already_active = set(model.active_computes(state))
    changed = True
    while changed:
        changed = False
        for item in model.task_ids:
            task = tasks[item]
            runtime = model.task_runtime(state, item)
            if item in completed or runtime.status != "pending":
                continue
            if task.kind == "compute" and task.duration == 0 and set(task.deps) <= completed:
                completed.add(item)
                changed = True
    return max(
        (
            task.duration
            for item, task in tasks.items()
            if item not in completed
            and item not in already_active
            and task.kind == "compute"
            and model.task_runtime(state, item).status == "pending"
            and set(task.deps) <= completed
        ),
        default=0,
    )


def direct_last_blocker_gain(
    model: PreeSingleModel,
    state: ScheduleState,
    task_id: str,
    tail: dict[str, int] | None = None,
) -> int:
    """Residual tails of direct joins for which the candidate is last blocker."""

    tails = tail if tail is not None else residual_tail(model, state, [task_id])
    tasks = model.task_map
    gain = 0
    for child in _children(model)[task_id]:
        if len(tasks[child].deps) < 2:
            continue
        others = (item for item in tasks[child].deps if item != task_id)
        if all(model.task_runtime(state, item).status == "completed" for item in others):
            gain += tails[child]
    return gain


def unique_downstream_work(
    model: PreeSingleModel,
    state: ScheduleState,
    task_id: str,
) -> int:
    """Residual work in the candidate's reachable sub-DAG, counted once.

    This is the explicit shared-downstream de-duplication feature: a node
    reached through several fork/join paths contributes once, not once per
    path.
    """

    descendants = _descendants(model, task_id)
    return sum(_own_remaining(model, state, item) for item in descendants)


def downstream_communication_demand(
    model: PreeSingleModel,
    state: ScheduleState,
    task_id: str,
) -> int:
    """Unique residual channel demand downstream of a candidate."""

    tasks = model.task_map
    return sum(
        _own_remaining(model, state, item)
        for item in _descendants(model, task_id)
        if tasks[item].kind == "comm"
    )


def _priority_key(
    model: PreeSingleModel,
    state: ScheduleState,
    task_id: str,
    priority: str,
    tail: dict[str, int],
) -> tuple[object, ...]:
    remaining = _own_remaining(model, state, task_id)
    exclusive_tail = tail[task_id] - remaining
    if priority == "spt":
        return (remaining, 0, task_id)
    if priority == "fixed_order":
        return (task_id,)
    if priority == "lpt":
        return (-remaining, 0, task_id)
    if priority == "longest_delay":
        return (-immediate_compute_delay(model, state, task_id), -exclusive_tail, task_id)
    if priority == "release_gain":
        return (-immediate_release_gain(model, state, task_id), -exclusive_tail, task_id)
    if priority == "longest_tail":
        return (-exclusive_tail, 0, task_id)
    if priority == "lrpt":
        return (-tail[task_id], 0, task_id)
    if priority == "join_aware":
        return (
            -direct_last_blocker_gain(model, state, task_id, tail),
            -exclusive_tail,
            task_id,
        )
    if priority == "shared_downstream":
        return (-unique_downstream_work(model, state, task_id), -exclusive_tail, task_id)
    if priority == "downstream_demand":
        return (
            -downstream_communication_demand(model, state, task_id),
            -exclusive_tail,
            task_id,
        )
    raise ValueError(f"unknown preemptive priority: {priority}")


def _baseline_choice(
    model: PreeSingleModel,
    state: ScheduleState,
    priority: str,
) -> str:
    eligible = model.eligible_communications(state)
    tail = residual_tail(model, state, eligible)
    return min(eligible, key=lambda item: _priority_key(model, state, item, priority, tail))


def _complete_actions(
    model: PreeSingleModel,
    state: ScheduleState,
    priority: str,
) -> tuple[Action, ...]:
    actions: list[Action] = []
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        action = (
            Action.run(_baseline_choice(model, state, priority))
            if eligible
            else Action.wait()
        )
        actions.append(action)
        state = model.step(state, action).after
    return tuple(actions)


def _rank_candidates(
    model: PreeSingleModel,
    state: ScheduleState,
    eligible: tuple[str, ...],
    tail: dict[str, int],
    top_k: int | None,
    mode: str,
    completion_priority: str,
) -> list[str]:
    if mode == "tail":
        mode = "longest_tail"
    if mode not in {
        "longest_tail",
        "lrpt",
        "join",
        "hybrid",
    }:
        raise ValueError(f"unknown candidate mode: {mode}")
    baseline = min(
        eligible,
        key=lambda item: _priority_key(
            model, state, item, completion_priority, tail
        ),
    )
    longest = sorted(
        eligible,
        key=lambda item: _priority_key(model, state, item, "longest_tail", tail),
    )
    lrpt = sorted(
        eligible,
        key=lambda item: _priority_key(model, state, item, "lrpt", tail),
    )
    join = sorted(
        eligible,
        key=lambda item: _priority_key(model, state, item, "join_aware", tail),
    )
    ordered = {
        "longest_tail": longest,
        "lrpt": lrpt,
        "join": join,
        "hybrid": _interleave(longest, join, lrpt),
    }[mode]
    selected = [baseline, *(item for item in ordered if item != baseline)]
    return selected if top_k is None else selected[:top_k]


def _interleave(*rankings: list[str]) -> list[str]:
    result: list[str] = []
    for index in range(max((len(items) for items in rankings), default=0)):
        for items in rankings:
            if index < len(items) and items[index] not in result:
                result.append(items[index])
    return result


def _advance_forced_idle(
    model: PreeSingleModel,
    state: ScheduleState,
) -> tuple[ScheduleState, tuple[Action, ...]]:
    actions: list[Action] = []
    while (
        not model.is_finished(state)
        and not model.eligible_communications(state)
    ):
        action = Action.wait()
        actions.append(action)
        state = model.step(state, action).after
    return state, tuple(actions)


def _apply_actions(
    model: PreeSingleModel,
    state: ScheduleState,
    actions: tuple[Action, ...],
) -> ScheduleState:
    for action in actions:
        state = model.step(state, action).after
    return state


def _own_remaining(
    model: PreeSingleModel,
    state: ScheduleState,
    task_id: str,
) -> int:
    runtime = model.task_runtime(state, task_id)
    if runtime.status == "completed":
        return 0
    if runtime.status in {"running", "suspended"}:
        return runtime.remaining
    return model.task_map[task_id].duration


def _children(model: PreeSingleModel) -> dict[str, list[str]]:
    return model.children


def _descendants(model: PreeSingleModel, task_id: str) -> set[str]:
    children = _children(model)
    result: set[str] = set()
    pending = list(children[task_id])
    while pending:
        item = pending.pop()
        if item in result:
            continue
        result.add(item)
        pending.extend(children[item])
    return result


def _result(
    model: PreeSingleModel,
    actions: tuple[Action, ...] | list[Action],
) -> PreemptiveScheduleResult:
    trace = model.run(actions)
    assert_preemptive_trace(model, trace)
    return result_from_trace(trace)


def _action_key(actions: tuple[Action, ...]) -> tuple[tuple[str, str], ...]:
    return tuple((action.kind, action.task_id or "") for action in actions)
