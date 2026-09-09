"""Exact single-channel preemptive scheduling over public event states."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from time import perf_counter
from typing import Callable, Literal

from core.dag import DAG
from core.execution.preemptive import (
    Action,
    PreeSingleModel,
    PreemptiveScheduleResult,
    ScheduleState,
    result_from_trace,
)
from core.trace.pree_single import assert_preemptive_trace

StateKey = tuple[object, ...]


def bounded_event_search(
    model: PreeSingleModel,
    action_provider: Callable[[ScheduleState], tuple[Action, ...]],
    state_key: Callable[[ScheduleState], StateKey],
    *,
    max_states: int = 500_000,
    time_limit_s: float | None = None,
    transition_cost: Callable[[ScheduleState, Action, ScheduleState], float] | None = None,
) -> PreemptiveScheduleResult:
    """Run one bounded exact event search over a caller-defined action space.

    The caller supplies only structure-specific candidate exposure and state
    quotienting. State storage, memoization, budget handling, optimal suffix
    extraction, and trace validation remain in the public core oracle.
    """

    started = perf_counter()
    representatives: dict[StateKey, ScheduleState] = {}
    explored = 0
    generated_transitions = 0
    cost = transition_cost or (lambda before, _action, after: after.time - before.time)

    def remember(state: ScheduleState) -> StateKey:
        key = state_key(state)
        representatives.setdefault(key, state)
        return key

    @lru_cache(maxsize=None)
    def value(key: StateKey) -> float:
        nonlocal explored, generated_transitions
        explored += 1
        if explored > max_states:
            raise RuntimeError("exact event search exceeded state limit")
        if time_limit_s is not None and perf_counter() - started > time_limit_s:
            raise TimeoutError("exact event search exceeded time limit")
        state = representatives[key]
        if model.is_finished(state):
            return 0
        actions = action_provider(state)
        if not actions:
            raise RuntimeError("unfinished state has no legal action")
        best: float | None = None
        for action in actions:
            after = model.step(state, action).after
            generated_transitions += 1
            child = remember(after)
            candidate = cost(state, action, after) + value(child)
            best = candidate if best is None else min(best, candidate)
        return best if best is not None else 0

    state = model.initial_state()
    root = remember(state)
    value(root)
    actions: list[Action] = []
    while not model.is_finished(state):
        candidates = []
        for action in action_provider(state):
            after = model.step(state, action).after
            child = remember(after)
            candidates.append((
                cost(state, action, after) + value(child),
                action.kind,
                action.task_id or "",
                action,
                after,
            ))
        if not candidates:
            raise RuntimeError("unfinished state has no legal action")
        _score, _kind, _task_id, action, state = min(candidates)
        actions.append(action)
    trace = model.run(actions)
    assert_preemptive_trace(model, trace)
    return result_from_trace(trace).with_stats(
        explored_states=explored,
        generated_transitions=generated_transitions,
        deduplicated_states=value.cache_info().hits,
        memo_hits=value.cache_info().hits,
        status="optimal",
        termination_reason="complete_enumeration",
        runtime_ms=(perf_counter() - started) * 1000,
    )


@dataclass(frozen=True)
class ExactSuffixResult:
    makespan: int
    actions: tuple[Action, ...]
    status: Literal["feasible", "optimal"]
    termination_reason: str
    explored_states: int
    generated_transitions: int
    runtime_ms: float


class _BudgetExceeded(RuntimeError):
    pass


def audit_state_key(state: ScheduleState) -> StateKey:
    return (state.time, state.tasks, state.last_communication)


def normalized_state_key(state: ScheduleState) -> StateKey:
    return tuple((item.status, item.remaining) for item in state.tasks)


def _remaining(model: PreeSingleModel, state: ScheduleState, task_id: str) -> int:
    runtime = model.task_runtime(state, task_id)
    if runtime.status == "completed":
        return 0
    return runtime.remaining if runtime.status in {"running", "suspended"} else model.task_map[task_id].duration


def _tail(model: PreeSingleModel, state: ScheduleState) -> dict[str, int]:
    values: dict[str, int] = {}
    for task_id in reversed(model.task_ids):
        values[task_id] = _remaining(model, state, task_id) + max(
            (values[child] for child in model.children[task_id]), default=0
        )
    return values


def remaining_lower_bound(model: PreeSingleModel, state: ScheduleState, *, mode: str = "combined") -> int:
    if mode not in {"none", "communication", "path", "combined"}:
        raise ValueError("bound_mode must be one of: none, communication, path, combined")
    if mode == "none":
        return 0
    communication = sum(
        _remaining(model, state, task_id)
        for task_id in model.task_ids
        if model.task_map[task_id].kind == "comm"
    )
    path = max(_tail(model, state).values(), default=0)
    return communication if mode == "communication" else path if mode == "path" else max(communication, path)


def _completion(model: PreeSingleModel, state: ScheduleState) -> tuple[Action, ...]:
    actions: list[Action] = []
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        action = Action.wait() if not eligible else Action.run(min(eligible, key=lambda item: (-_tail(model, state)[item], item)))
        actions.append(action)
        state = model.step(state, action).after
    return tuple(actions)


def _apply(model: PreeSingleModel, state: ScheduleState, actions: tuple[Action, ...]) -> ScheduleState:
    for action in actions:
        state = model.step(state, action).after
    return state


def _result(model: PreeSingleModel, actions: tuple[Action, ...]) -> PreemptiveScheduleResult:
    trace = model.run(actions)
    assert_preemptive_trace(model, trace)
    return result_from_trace(trace)


def exact_oracle(
    dag: DAG,
    *,
    max_states: int = 500_000,
    time_limit_s: float | None = None,
    normalized: bool = True,
    bound_mode: str = "combined",
    use_memo: bool = True,
    use_incumbent: bool = True,
) -> PreemptiveScheduleResult:
    """Return an optimal result, or an explicitly feasible budget fallback."""

    if max_states < 1:
        raise ValueError("max_states must be positive")
    model = PreeSingleModel(dag)
    initial = model.initial_state()
    key_for = normalized_state_key if normalized else audit_state_key
    started = perf_counter()
    explored = generated = duplicates = pruned = 0
    memo: dict[StateKey, tuple[int, tuple[Action, ...]]] = {}
    baseline = _completion(model, initial)
    root_bound = remaining_lower_bound(model, initial)

    def check() -> None:
        if explored >= max_states:
            raise _BudgetExceeded("state_limit")
        if time_limit_s is not None and perf_counter() - started >= time_limit_s:
            raise _BudgetExceeded("time_limit")

    def search(state: ScheduleState) -> tuple[int, tuple[Action, ...]]:
        nonlocal explored, generated, duplicates, pruned
        key = key_for(state)
        if use_memo and key in memo:
            duplicates += 1
            return memo[key]
        check()
        explored += 1
        if model.is_finished(state):
            result = (0, ())
        else:
            completion = _completion(model, state)
            best_cost = _apply(model, state, completion).time - state.time if use_incumbent else float("inf")
            best_actions = completion
            for action in model.legal_actions(state):
                after = model.step(state, action).after
                generated += 1
                elapsed = after.time - state.time
                if bound_mode != "none" and elapsed + remaining_lower_bound(model, after, mode=bound_mode) > best_cost:
                    pruned += 1
                    continue
                suffix_cost, suffix = search(after)
                candidate = (elapsed + suffix_cost, ((action.kind, action.task_id or ""),), (action, *suffix))
                current = (best_cost, tuple((item.kind, item.task_id or "") for item in best_actions), best_actions)
                if candidate[:2] < current[:2]:
                    best_cost, best_actions = candidate[0], candidate[2]
            result = (int(best_cost), best_actions)
        if use_memo:
            memo[key] = result
        return result

    try:
        _cost, actions = search(initial)
        status, reason = "optimal", "complete_enumeration"
    except _BudgetExceeded as error:
        actions = baseline
        status, reason = "feasible", str(error)
    return _result(model, actions).with_stats(
        runtime_ms=(perf_counter() - started) * 1000,
        explored_states=explored,
        generated_transitions=generated,
        deduplicated_states=duplicates,
        pruned_states=pruned,
        lower_bound=root_bound,
        status=status,
        termination_reason=reason,
    )


def exact_oracle_uncompressed(dag: DAG, **options: object) -> PreemptiveScheduleResult:
    return exact_oracle(dag, normalized=False, **options)  # type: ignore[arg-type]


def exact_completion_from_state_uncompressed(
    model: PreeSingleModel, state: ScheduleState, *, max_states: int = 100_000,
    time_limit_s: float | None = 5.0,
) -> ExactSuffixResult:
    """Compute an audit-key Exact suffix without constructing a whole trace."""
    if max_states < 1:
        raise ValueError("max_states must be positive")
    started = perf_counter()
    explored = generated = duplicates = 0
    memo: dict[StateKey, tuple[int, tuple[Action, ...]]] = {}
    baseline = _completion(model, state)

    def check() -> None:
        if explored >= max_states:
            raise _BudgetExceeded("state_limit")
        if time_limit_s is not None and perf_counter() - started >= time_limit_s:
            raise _BudgetExceeded("time_limit")

    def search(current: ScheduleState) -> tuple[int, tuple[Action, ...]]:
        nonlocal explored, generated, duplicates
        key = audit_state_key(current)
        cached = memo.get(key)
        if cached is not None:
            duplicates += 1
            return cached
        check()
        explored += 1
        if model.is_finished(current):
            result = (0, ())
        else:
            completion = _completion(model, current)
            best_cost = _apply(model, current, completion).time - current.time
            best_actions = completion
            for action in model.legal_actions(current):
                after = model.step(current, action).after
                generated += 1
                elapsed = after.time - current.time
                if elapsed + remaining_lower_bound(model, after) > best_cost:
                    continue
                suffix_cost, suffix = search(after)
                candidate = (elapsed + suffix_cost, (action, *suffix))
                if (candidate[0], tuple((item.kind, item.task_id or "") for item in candidate[1])) < (
                    best_cost, tuple((item.kind, item.task_id or "") for item in best_actions)
                ):
                    best_cost, best_actions = candidate
            result = (best_cost, best_actions)
        memo[key] = result
        return result

    try:
        cost, actions = search(state)
        status, reason, makespan = "optimal", "complete_enumeration", state.time + cost
    except _BudgetExceeded as error:
        actions = baseline
        status, reason = "feasible", str(error)
        makespan = _apply(model, state, baseline).time
    return ExactSuffixResult(
        makespan, actions, status, reason, explored, generated,
        (perf_counter() - started) * 1000,
    )
