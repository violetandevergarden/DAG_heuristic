"""Stage 3 policies and search for fixed-resource preemptive scheduling.

All time advancement and action legality live in
``core.execution.preemptive``.  This module only scores communications or
compatible sets and searches over the simulator's legal actions.
"""

from __future__ import annotations

from random import Random
from time import perf_counter

from core.dag import DAG
from core.execution.preemptive import (
    MultiResourceAction,
    MultiResourceState,
    MultiResourceTrace,
    MultiRuntimeTask,
    PreeMultiModel,
)
from core.oracle.pree_multi import MultiOracleResult as MultiResult
from core.oracle.pree_multi import PackingStats

# Compatibility names retained for callers while ownership moves to core.
TaskState = MultiRuntimeTask
MultiState = MultiResourceState
MultiAction = MultiResourceAction
MultiTrace = MultiResourceTrace


class CompletionCache:
    """Cache greedy suffixes at stable future-equivalent states."""

    def __init__(self) -> None:
        self._values: dict[tuple[tuple[str, int], ...], tuple[int, tuple[MultiAction, ...]]] = {}
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(state: MultiState) -> tuple[tuple[str, int], ...]:
        return tuple((item.status, item.remaining) for item in state.tasks)


def complete_pack(
    model: PreeMultiModel,
    state: MultiState,
    *,
    cache: CompletionCache | None = None,
) -> tuple[MultiState, tuple[MultiAction, ...]]:
    """Complete a stable state with longest-tail maximal packing."""

    start_key = cache.key(state) if cache is not None else None
    if cache is not None:
        cached = cache._values.get(start_key)
        if cached is not None:
            cache.hits += 1
            _elapsed, suffix = cached
            for action in suffix:
                state, _ = model.normalize_decision_state(state)
                state = model.step(state, action)
            state, _ = model.normalize_decision_state(state)
            return state, suffix
        cache.misses += 1
    started = state.time
    actions: list[MultiAction] = []
    while not model.finished(state):
        state, _ = model.normalize_decision_state(state)
        if model.finished(state):
            break
        tails = _residual_tail(model, state)
        selected: list[str] = []
        for task_id in sorted(model.eligible(state), key=lambda item: (-tails[item], item)):
            if model.compatible((*selected, task_id)):
                selected.append(task_id)
        action = MultiAction(tuple(sorted(selected)))
        actions.append(action)
        state = model.step(state, action)
    suffix = tuple(actions)
    if cache is not None:
        cache._values[start_key] = (state.time - started, suffix)
    return state, suffix


def remaining_lower_bound(
    model: PreeMultiModel, state: MultiState
) -> int:
    """Safe ``max(precedence path, per-resource residual load)`` bound."""

    original_time = state.time
    state, _idle = model.normalize_decision_state(state)
    tails = _residual_tail(model, state)
    precedence = max(tails.values(), default=0)
    resource = max(_resource_load(model, state).values(), default=0)
    return state.time - original_time + max(precedence, resource)


def schedule_pack(
    dag: DAG,
    resources: dict[str, frozenset[str]],
    mode: str = "longest_tail",
    *,
    seed: int = 0,
) -> MultiResult:
    """Greedy-fill a maximal set using one communication priority."""

    started = perf_counter()
    model = PreeMultiModel(dag, resources)
    state = model.initial_state()
    actions: list[MultiAction] = []
    while not model.finished(state):
        state, _idle = model.normalize_decision_state(state)
        if model.finished(state):
            break
        if mode == "random":
            order = list(model.eligible(state))
            Random(seed + len(actions)).shuffle(order)
            scores = {task_id: (order.index(task_id), task_id) for task_id in order}
        else:
            scores = score_tasks(model, state, mode)
        action = greedy_fill_from_task_scores(model, state, scores)
        actions.append(action)
        state = model.step(state, action)
    return _result(
        model,
        actions,
        runtime_ms=(perf_counter() - started) * 1000,
        lower_bound=remaining_lower_bound(model, model.initial_state()),
    )


def schedule_set_policy(
    dag: DAG,
    resources: dict[str, frozenset[str]],
    mode: str = "union_downstream",
) -> MultiResult:
    """Rank whole maximal sets, de-duplicating shared downstream nodes."""

    started = perf_counter()
    model = PreeMultiModel(dag, resources)
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


def resource_downstream_demand(
    model: PreeMultiModel,
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


def result_from_actions(
    model: PreeMultiModel,
    actions: list[MultiAction] | tuple[MultiAction, ...],
    **values: object,
) -> MultiResult:
    action_tuple = tuple(actions)
    trace = model.run(action_tuple)
    from core.trace.pree_multi import assert_multi_resource_trace

    assert_multi_resource_trace(model.dag, model.resources, trace)
    defaults = {
        "status": "feasible",
        "runtime_ms": 0.0,
        "lower_bound": 0,
    }
    defaults.update(values)
    if "packing_stats" not in defaults and any(
        key in defaults for key in ("compatible_sets_generated", "max_branch", "set_enumeration_ms")
    ):
        defaults["packing_stats"] = PackingStats(
            compatible_sets_generated=int(defaults.get("compatible_sets_generated", 0)),
            max_branch=int(defaults.get("max_branch", 0)),
            set_enumeration_ms=float(defaults.get("set_enumeration_ms", 0.0)),
        )
    return MultiResult(
        trace.makespan,
        action_tuple,
        len(action_tuple),
        _count_set_preemptions(model, action_tuple),
        trace=trace,
        **defaults,
    )


_result = result_from_actions


def score_tasks(
    model: PreeMultiModel, state: MultiState, mode: str
) -> dict[str, tuple]:
    """Score eligible communications without constructing a set."""

    eligible = model.eligible(state)
    tails = _residual_tail(model, state)
    load = _resource_load(model, state)
    def key(task_id: str) -> tuple:
        bottleneck = max((load[item] for item in model.resources[task_id]), default=0)
        if mode == "longest_tail":
            return (-tails[task_id], task_id)
        if mode == "fixed_order":
            return (task_id,)
        if mode == "fifo":
            # An eligible set is formed at one event time; input/topological
            # order is the deterministic FIFO tie-break within that batch.
            return (model.index[task_id], task_id)
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
    model: PreeMultiModel,
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
    model: PreeMultiModel,
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
    model: PreeMultiModel,
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
    model: PreeMultiModel, roots: tuple[str, ...]
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
    model: PreeMultiModel, state: MultiState
) -> dict[str, int]:
    order = model.dag.topological_order()
    tasks = model.task_map
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
    model: PreeMultiModel, state: MultiState
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
    model: PreeMultiModel,
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
