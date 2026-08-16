"""Stage 3 policies and search for fixed-resource preemptive scheduling.

All time advancement and action legality live in
``core.execution.multi_resource``.  This module only scores communications or
compatible sets and searches over the simulator's legal actions.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from time import perf_counter
from typing import Literal

from core.dag import BenchmarkDAG, topological_order
from core.execution.multi_resource import (
    MultiResourceAction,
    MultiResourceState,
    MultiResourceTrace,
    MultiRuntimeTask,
    PreemptiveMultiResourceModel,
)

# Compatibility names retained for callers while ownership moves to core.
TaskState = MultiRuntimeTask
MultiState = MultiResourceState
MultiAction = MultiResourceAction
MultiTrace = MultiResourceTrace


@dataclass(frozen=True)
class MultiResult:
    makespan: int
    actions: tuple[MultiAction, ...]
    decision_count: int
    preemptions: int
    explored_states: int = 0
    trace: MultiTrace | None = None
    status: Literal["feasible", "optimal"] = "feasible"
    termination_reason: str | None = None
    runtime_ms: float = 0.0
    lower_bound: int = 0
    generated_transitions: int = 0
    deduplicated_states: int = 0
    pruned_states: int = 0
    compatible_sets_generated: int = 0
    mean_branch: float = 0.0
    max_branch: int = 0
    set_enumeration_ms: float = 0.0
    peak_states: int = 0
    peak_memory_bytes: int | None = None
    expanded_nodes: int = 0
    evaluated_candidates: int = 0
    completion_calls: int = 0
    cache_hits: int = 0
    fallback_count: int = 0
    completed_search: bool = True
    fallback_reason: str | None = None


@dataclass
class _SearchStats:
    explored: int = 0
    generated: int = 0
    deduplicated: int = 0
    pruned: int = 0
    compatible_sets: int = 0
    max_branch: int = 0
    set_enumeration_ms: float = 0.0


class _BudgetExceeded(RuntimeError):
    pass


def normalized_state_key(state: MultiState) -> tuple[tuple[str, int], ...]:
    """Future-equivalent key at a stable Stage 3 decision boundary."""

    return tuple((item.status, item.remaining) for item in state.tasks)


def uncompressed_state_key(state: MultiState) -> tuple:
    """Audit key retaining absolute time and every mutable runtime field."""

    return (
        state.time,
        state.tasks,
        state.active_allocations,
        state.resource_owners,
    )


def remaining_lower_bound(
    model: PreemptiveMultiResourceModel, state: MultiState
) -> int:
    """Safe ``max(precedence path, per-resource residual load)`` bound."""

    original_time = state.time
    state, _idle = model.normalize_decision_state(state)
    tails = _residual_tail(model, state)
    precedence = max(tails.values(), default=0)
    resource = max(_resource_load(model, state).values(), default=0)
    return state.time - original_time + max(precedence, resource)


def schedule_pack(
    dag: BenchmarkDAG,
    resources: dict[str, frozenset[str]],
    mode: str = "longest_tail",
) -> MultiResult:
    """Greedy-fill a maximal set using one communication priority."""

    started = perf_counter()
    model = PreemptiveMultiResourceModel(dag, resources)
    state = model.initial_state()
    actions: list[MultiAction] = []
    while not model.finished(state):
        state, _idle = model.normalize_decision_state(state)
        if model.finished(state):
            break
        action = greedy_fill_from_task_scores(
            model, state, score_tasks(model, state, mode)
        )
        actions.append(action)
        state = model.step(state, action)
    return _result(
        model,
        actions,
        runtime_ms=(perf_counter() - started) * 1000,
        lower_bound=remaining_lower_bound(model, model.initial_state()),
    )


def schedule_set_policy(
    dag: BenchmarkDAG,
    resources: dict[str, frozenset[str]],
    mode: str = "union_downstream",
) -> MultiResult:
    """Rank whole maximal sets, de-duplicating shared downstream nodes."""

    started = perf_counter()
    model = PreemptiveMultiResourceModel(dag, resources)
    state = model.initial_state()
    actions: list[MultiAction] = []
    generated = 0
    max_branch = 0
    set_enumeration_ms = 0.0
    while not model.finished(state):
        state, _idle = model.normalize_decision_state(state)
        if model.finished(state):
            break
        set_started = perf_counter()
        candidates = model.maximal_actions(state)
        set_enumeration_ms += (perf_counter() - set_started) * 1000
        generated += len(candidates)
        max_branch = max(max_branch, len(candidates))
        action = select_best_scored_set(score_sets(model, state, candidates, mode))
        actions.append(action)
        state = model.step(state, action)
    return _result(
        model,
        actions,
        runtime_ms=(perf_counter() - started) * 1000,
        lower_bound=remaining_lower_bound(model, model.initial_state()),
        compatible_sets_generated=generated,
        max_branch=max_branch,
        set_enumeration_ms=set_enumeration_ms,
    )


def rollout_sets(
    dag: BenchmarkDAG,
    resources: dict[str, frozenset[str]],
    *,
    top_k: int = 2,
    depth: int = 2,
    node_budget: int = 10_000,
    set_budget: int = 50_000,
    time_limit_s: float | None = 1.0,
) -> MultiResult:
    """Budgeted receding-horizon compatible-set Rollout.

    The LT greedy set is always retained.  A budget exhaustion at any decision
    deterministically falls back to that baseline set.  Forced idle is
    simulator-owned and therefore consumes no search depth.
    """

    if top_k < 1 or depth < 1 or node_budget < 1 or set_budget < 1:
        raise ValueError("rollout budgets, top_k and depth must be positive")
    started = perf_counter()
    model = PreemptiveMultiResourceModel(dag, resources)
    state = model.initial_state()
    actions: list[MultiAction] = []
    memo: dict[tuple[int, tuple[tuple[str, int], ...]], int] = {}
    expanded = evaluated = completion_calls = cache_hits = generated = 0
    set_enumeration_ms = 0.0
    fallback_count = 0
    fallback_reason: str | None = None

    def check_budget() -> None:
        if expanded >= node_budget:
            raise _BudgetExceeded("expanded_node_budget")
        if generated >= set_budget:
            raise _BudgetExceeded("compatible_set_budget")
        if time_limit_s is not None and perf_counter() - started >= time_limit_s:
            raise _BudgetExceeded("wall_clock_budget")

    def candidates(current: MultiState) -> tuple[MultiAction, ...]:
        nonlocal generated, set_enumeration_ms
        check_budget()
        set_started = perf_counter()
        all_actions = model.maximal_actions(current)
        set_enumeration_ms += (perf_counter() - set_started) * 1000
        generated += len(all_actions)
        baseline = greedy_fill_from_task_scores(
            model, current, score_tasks(model, current, "longest_tail")
        )
        ranked_scores = score_sets(
            model, current, all_actions, "union_downstream"
        )
        ranked = sorted(
            all_actions,
            key=lambda item: ranked_scores[item],
        )
        selected = list(ranked[:top_k])
        if baseline not in selected:
            selected.append(baseline)
        return tuple(sorted(set(selected), key=lambda item: item.communications))

    def evaluate(current: MultiState, remaining_depth: int) -> int:
        nonlocal expanded, evaluated, completion_calls, cache_hits
        current, _idle = model.normalize_decision_state(current)
        if model.finished(current):
            return current.time
        key = (remaining_depth, normalized_state_key(current))
        if key in memo:
            cache_hits += 1
            return current.time + memo[key]
        check_budget()
        expanded += 1
        if remaining_depth == 0:
            completion_calls += 1
            completed, _suffix = _complete_pack(model, current)
            value = completed.time
        else:
            values = []
            for action in candidates(current):
                evaluated += 1
                values.append(evaluate(model.step(current, action), remaining_depth - 1))
            value = min(values)
        memo[key] = value - current.time
        return value

    while not model.finished(state):
        state, _idle = model.normalize_decision_state(state)
        if model.finished(state):
            break
        baseline = greedy_fill_from_task_scores(
            model, state, score_tasks(model, state, "longest_tail")
        )
        try:
            scored = []
            for action in candidates(state):
                evaluated += 1
                scored.append(
                    (evaluate(model.step(state, action), depth - 1), action.communications, action)
                )
            action = min(scored)[2]
        except _BudgetExceeded as error:
            action = baseline
            fallback_count += 1
            fallback_reason = str(error)
        actions.append(action)
        state = model.step(state, action)
    return _result(
        model,
        actions,
        runtime_ms=(perf_counter() - started) * 1000,
        lower_bound=remaining_lower_bound(model, model.initial_state()),
        compatible_sets_generated=generated,
        set_enumeration_ms=set_enumeration_ms,
        expanded_nodes=expanded,
        evaluated_candidates=evaluated,
        completion_calls=completion_calls,
        cache_hits=cache_hits,
        fallback_count=fallback_count,
        completed_search=fallback_count == 0,
        fallback_reason=fallback_reason,
    )


def exact_oracle(
    dag: BenchmarkDAG,
    resources: dict[str, frozenset[str]],
    *,
    max_states: int = 300_000,
    time_limit_s: float | None = 5.0,
) -> MultiResult:
    return _exact(dag, resources, max_states, time_limit_s, compressed=True)


def exact_oracle_uncompressed(
    dag: BenchmarkDAG,
    resources: dict[str, frozenset[str]],
    *,
    max_states: int = 100_000,
    time_limit_s: float | None = 5.0,
) -> MultiResult:
    return _exact(dag, resources, max_states, time_limit_s, compressed=False)


def _exact(
    dag: BenchmarkDAG,
    resources: dict[str, frozenset[str]],
    max_states: int,
    time_limit_s: float | None,
    *,
    compressed: bool,
) -> MultiResult:
    if max_states < 1:
        raise ValueError("max_states must be positive")
    started = perf_counter()
    model = PreemptiveMultiResourceModel(dag, resources)
    raw_initial = model.initial_state()
    initial, _idle = model.normalize_decision_state(raw_initial)
    baseline_state, baseline_actions = _complete_pack(model, initial)
    root_lower_bound = remaining_lower_bound(model, raw_initial)
    stats = _SearchStats()
    memo: dict[tuple, tuple[int, tuple[MultiAction, ...]]] = {}
    key_fn = normalized_state_key if compressed else uncompressed_state_key

    def check_budget() -> None:
        if stats.explored >= max_states:
            raise _BudgetExceeded("state_limit")
        if time_limit_s is not None and perf_counter() - started >= time_limit_s:
            raise _BudgetExceeded("time_limit")

    def search(state: MultiState) -> tuple[int, tuple[MultiAction, ...]]:
        state, _forced = model.normalize_decision_state(state)
        key = key_fn(state)
        if key in memo:
            stats.deduplicated += 1
            return memo[key]
        check_budget()
        stats.explored += 1
        if model.finished(state):
            memo[key] = (0, ())
            return memo[key]
        completion, suffix = _complete_pack(model, state)
        best_cost = completion.time - state.time
        best_actions = suffix
        set_started = perf_counter()
        actions = model.maximal_actions(state)
        stats.set_enumeration_ms += (perf_counter() - set_started) * 1000
        stats.compatible_sets += len(actions)
        stats.max_branch = max(stats.max_branch, len(actions))
        branch_scores = score_sets(model, state, actions, "union_downstream")
        for action in sorted(actions, key=lambda item: branch_scores[item]):
            check_budget()
            after = model.step(state, action)
            after, _forced = model.normalize_decision_state(after)
            stats.generated += 1
            immediate = after.time - state.time
            child_bound = remaining_lower_bound(model, after)
            if immediate + child_bound > best_cost:
                stats.pruned += 1
                continue
            residual, child_actions = search(after)
            candidate = immediate + residual
            candidate_actions = (action, *child_actions)
            if (candidate, tuple(item.communications for item in candidate_actions)) < (
                best_cost,
                tuple(item.communications for item in best_actions),
            ):
                best_cost = candidate
                best_actions = candidate_actions
        memo[key] = (best_cost, best_actions)
        return memo[key]

    try:
        _cost, actions = search(initial)
        status: Literal["feasible", "optimal"] = "optimal"
        reason = "complete_enumeration"
    except _BudgetExceeded as error:
        actions = baseline_actions
        status = "feasible"
        reason = str(error)
    runtime_ms = (perf_counter() - started) * 1000
    result = _result(
        model,
        actions,
        status=status,
        termination_reason=reason,
        runtime_ms=runtime_ms,
        lower_bound=root_lower_bound,
        explored_states=stats.explored,
        generated_transitions=stats.generated,
        deduplicated_states=stats.deduplicated,
        pruned_states=stats.pruned,
        compatible_sets_generated=stats.compatible_sets,
        mean_branch=(stats.compatible_sets / stats.explored if stats.explored else 0.0),
        max_branch=stats.max_branch,
        set_enumeration_ms=stats.set_enumeration_ms,
        peak_states=stats.explored,
        peak_memory_bytes=None,
    )
    if status == "feasible" and result.makespan != baseline_state.time:
        raise AssertionError("budget fallback must return the deterministic baseline")
    return result


def resource_downstream_demand(
    model: PreemptiveMultiResourceModel,
    state: MultiState,
    task_id: str,
) -> dict[str, int]:
    """Unique reachable communication demand represented per fixed resource."""

    reachable = _reachable(model, (task_id,))
    result: dict[str, int] = {}
    for descendant in reachable:
        index = model.index[descendant]
        task = model.tasks[index]
        runtime = state.tasks[index]
        if task.kind != "comm" or runtime.status == "completed":
            continue
        remaining = runtime.remaining or task.duration
        for resource in model.resources[descendant]:
            result[resource] = result.get(resource, 0) + remaining
    return result


def multi_resource_statistics(
    trace: MultiTrace, resources: dict[str, frozenset[str]]
) -> dict[str, object]:
    """Objective trace statistics used by the thin Stage 3 runner."""

    busy: dict[str, int] = {}
    for interval in trace.resource_intervals:
        busy[interval.resource_id] = busy.get(interval.resource_id, 0) + (
            interval.end - interval.start
        )
    all_resources = sorted({resource for values in resources.values() for resource in values})
    utilization = {
        resource: (busy.get(resource, 0) / trace.makespan if trace.makespan else 0.0)
        for resource in all_resources
    }
    set_sizes = [len(decision.action.communications) for decision in trace.decisions]
    forced_idle_time = sum(item.end - item.start for item in trace.forced_idle)
    return {
        "resource_busy": {item: busy.get(item, 0) for item in all_resources},
        "resource_utilization": utilization,
        "hotspot_utilization": max(utilization.values(), default=0.0),
        "unused_resources": sum(value == 0 for value in busy.values())
        + sum(item not in busy for item in all_resources),
        "mean_set_size": mean(set_sizes) if set_sizes else 0.0,
        "max_set_size": max(set_sizes, default=0),
        "forced_idle_time": forced_idle_time,
        "forced_idle_count": len(trace.forced_idle),
    }


def _result(
    model: PreemptiveMultiResourceModel,
    actions: list[MultiAction] | tuple[MultiAction, ...],
    **values: object,
) -> MultiResult:
    action_tuple = tuple(actions)
    trace = model.run(action_tuple)
    from muti_channel.preemptive.trace import assert_multi_resource_trace

    assert_multi_resource_trace(model.dag, model.resources, trace)
    defaults = {
        "status": "feasible",
        "runtime_ms": 0.0,
        "lower_bound": 0,
    }
    defaults.update(values)
    return MultiResult(
        trace.makespan,
        action_tuple,
        len(action_tuple),
        _count_set_preemptions(model, action_tuple),
        trace=trace,
        **defaults,
    )


def _complete_pack(
    model: PreemptiveMultiResourceModel, state: MultiState
) -> tuple[MultiState, tuple[MultiAction, ...]]:
    actions: list[MultiAction] = []
    while not model.finished(state):
        state, _idle = model.normalize_decision_state(state)
        if model.finished(state):
            break
        action = greedy_fill_from_task_scores(
            model, state, score_tasks(model, state, "longest_tail")
        )
        actions.append(action)
        state = model.step(state, action)
    return state, tuple(actions)


def score_tasks(
    model: PreemptiveMultiResourceModel, state: MultiState, mode: str
) -> dict[str, tuple]:
    """Score eligible communications without constructing a set."""

    eligible = model.eligible(state)
    tails = _residual_tail(model, state)
    load = _resource_load(model, state)

    def key(task_id: str) -> tuple:
        bottleneck = max((load[item] for item in model.resources[task_id]), default=0)
        if mode == "longest_tail":
            return (-tails[task_id], task_id)
        if mode == "resource_tail":
            return (-tails[task_id], -bottleneck, task_id)
        if mode == "bottleneck":
            return (-bottleneck, -tails[task_id], task_id)
        if mode == "resource_downstream":
            demand = resource_downstream_demand(model, state, task_id)
            hotspot = max(demand.values(), default=0)
            total = sum(demand.values())
            return (-hotspot, -total, -tails[task_id], task_id)
        raise ValueError(mode)

    return {task_id: key(task_id) for task_id in eligible}


def greedy_fill_from_task_scores(
    model: PreemptiveMultiResourceModel,
    state: MultiState,
    scores: dict[str, tuple],
) -> MultiAction:
    """Convert task scores into one deterministic maximal compatible set."""

    eligible = model.eligible(state)
    if set(scores) != set(eligible):
        raise ValueError("task scores must cover exactly the eligible communications")
    selected: list[str] = []
    for task_id in sorted(eligible, key=lambda item: scores[item]):
        if model.compatible((*selected, task_id)):
            selected.append(task_id)
    return MultiAction(tuple(sorted(selected)))


def score_sets(
    model: PreemptiveMultiResourceModel,
    state: MultiState,
    actions: tuple[MultiAction, ...] | list[MultiAction],
    mode: str,
) -> dict[MultiAction, tuple]:
    """Score complete maximal sets without choosing one of them."""

    if mode != "union_downstream":
        raise ValueError(mode)
    eligible = set(model.eligible(state))
    for action in actions:
        selected = set(action.communications)
        used = set().union(*(model.resources[item] for item in selected))
        maximal = all(
            item in selected or bool(used & model.resources[item]) for item in eligible
        )
        if not selected <= eligible or not model.compatible(action.communications) or not maximal:
            raise ValueError("set scores require legal maximal compatible actions")
    tails = _residual_tail(model, state)
    return {
        action: _union_downstream_set_score(model, state, action, tails)
        for action in actions
    }


def select_best_scored_set(scores: dict[MultiAction, tuple]) -> MultiAction:
    """Choose one action from externally supplied whole-set scores."""

    if not scores:
        raise ValueError("at least one scored compatible set is required")
    return min(scores, key=lambda action: (scores[action], action.communications))


def _union_downstream_set_score(
    model: PreemptiveMultiResourceModel,
    state: MultiState,
    action: MultiAction,
    tails: dict[str, int],
) -> tuple:
    reachable = _reachable(model, action.communications)
    unique_work = 0
    resource_demand: dict[str, int] = {}
    for task_id in reachable:
        index = model.index[task_id]
        runtime = state.tasks[index]
        if runtime.status == "completed":
            continue
        remaining = runtime.remaining or model.tasks[index].duration
        unique_work += remaining
        if model.tasks[index].kind == "comm":
            for resource in model.resources[task_id]:
                resource_demand[resource] = resource_demand.get(resource, 0) + remaining
    return (
        -unique_work,
        -max(resource_demand.values(), default=0),
        -max((tails[item] for item in action.communications), default=0),
        -len(action.communications),
        action.communications,
    )


def _reachable(
    model: PreemptiveMultiResourceModel, roots: tuple[str, ...]
) -> frozenset[str]:
    children = {item: [] for item in model.task_ids}
    for task in model.tasks:
        for parent in task.deps:
            children[parent].append(task.task_id)
    seen = set(roots)
    stack = list(roots)
    while stack:
        item = stack.pop()
        for child in children[item]:
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return frozenset(seen)


def _residual_tail(
    model: PreemptiveMultiResourceModel, state: MultiState
) -> dict[str, int]:
    order = topological_order(model.dag)
    tasks = model.dag.task_map()
    children = {item: [] for item in order}
    for task in tasks.values():
        for dep in task.deps:
            children[dep].append(task.task_id)
    tail: dict[str, int] = {}
    for task_id in reversed(order):
        runtime = state.tasks[model.index[task_id]]
        own = 0 if runtime.status == "completed" else (
            runtime.remaining or tasks[task_id].duration
        )
        tail[task_id] = own + max((tail[child] for child in children[task_id]), default=0)
    return tail


def _resource_load(
    model: PreemptiveMultiResourceModel, state: MultiState
) -> dict[str, int]:
    load: dict[str, int] = {}
    for task_id, resources in model.resources.items():
        runtime = state.tasks[model.index[task_id]]
        if runtime.status == "completed":
            continue
        remaining = runtime.remaining or model.tasks[model.index[task_id]].duration
        for resource in resources:
            load[resource] = load.get(resource, 0) + remaining
    return load


def _count_set_preemptions(
    model: PreemptiveMultiResourceModel,
    actions: tuple[MultiAction, ...],
) -> int:
    count = 0
    previous: set[str] = set()
    state = model.initial_state()
    for action in actions:
        state, _idle = model.normalize_decision_state(state)
        current = set(action.communications)
        after = model.step(state, action)
        count += sum(
            after.tasks[model.index[task_id]].status != "completed"
            for task_id in previous - current
        )
        previous = current
        state = after
    return count
