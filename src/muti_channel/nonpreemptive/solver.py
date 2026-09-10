"""R4: non-preemptive optional-idle scheduling on route resources.

Every started flow reserves all resources on its route until completion.  At a
task-completion event the scheduler may start a compatible subset of ready
flows, or start nothing and wait for the next active task completion.  The
module is isolated research infrastructure and does not change the production
executor.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from time import perf_counter

from core.dag import DAG
from core.execution.nonpreemptive import (
    NonPreeMultiModel,
    OracleMode,
    Resource,
    ResourceAction,
    ResourceInterval,
    ResourceState,
)
from core.oracle.nonpree_multi import MultiResourceOracleResult as ResourceSchedule
from core.oracle.nonpree_multi import exact_oracle as core_exact_oracle

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


@dataclass(frozen=True)
class ResourceDecisionContext:
    ready: tuple[str, ...]
    path: tuple[int, ...]
    tail: tuple[int, ...]
    loads: dict[Resource, int]


def build_context(model: NonPreeMultiModel, state: ResourceState) -> ResourceDecisionContext:
    path, tail = model.residual_features(state)
    return ResourceDecisionContext(
        ready=tuple(model.ready_flows(state)),
        path=path,
        tail=tail,
        loads=residual_resource_loads(model, state),
    )


def context_for(
    model: NonPreeMultiModel,
    state: ResourceState,
    cache: dict[ResourceState, ResourceDecisionContext] | None = None,
) -> ResourceDecisionContext:
    if cache is None:
        return build_context(model, state)
    context = cache.get(state)
    if context is None:
        context = build_context(model, state)
        cache[state] = context
    return context


def lower_bounds(model: NonPreeMultiModel, state: ResourceState) -> dict[str, int]:
    path, _tail = model.residual_features(state)
    loads = residual_resource_loads(model, state)
    result = {
        "critical_path": max(path, default=0),
        "max_resource_load": max(loads.values(), default=0),
    }
    result["combined"] = max(result.values())
    return result


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
    return core_exact_oracle(
        instance,
        mode=mode,
        max_states=max_states,
        time_limit_s=time_limit_s,
    )


def _ranked_ready(
    model: NonPreeMultiModel,
    state: ResourceState,
    policy: str,
    context: ResourceDecisionContext | None = None,
) -> list[str]:
    context = context or context_for(model, state)
    ready = list(context.ready)
    tail = context.tail
    loads = context.loads

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
    context_cache: dict[ResourceState, ResourceDecisionContext] | None = None,
) -> ResourceAction:
    context = context_for(model, state, context_cache)
    selected = []
    occupied = set(model.occupied_resources(state))
    for task_id in _ranked_ready(model, state, policy, context):
        resources = model.resources[model.index[task_id]]
        if occupied & resources:
            continue
        selected.append(task_id)
        occupied.update(resources)
    return ResourceAction.start(selected) if selected else ResourceAction.wait()


def complete(
    model: NonPreeMultiModel,
    state: ResourceState,
    policy: str,
    context_cache: dict[ResourceState, ResourceDecisionContext] | None = None,
) -> tuple[int, tuple[ResourceAction, ...]]:
    start = state.time
    actions = []
    while not model.is_finished(state):
        action = greedy_action(model, state, policy, context_cache)
        actions.append(action)
        state = model.step(state, action).after
    return state.time - start, tuple(actions)


def schedule_greedy(
    instance: DAG,
    policy: str = "dynamic_tail",
) -> ResourceSchedule:
    started = perf_counter()
    model = NonPreeMultiModel(instance)
    _elapsed, actions = complete(model, model.initial_state(), policy, {})
    return _replay(model, actions, runtime_ms=(perf_counter() - started) * 1000)


def _iter_compatible_subsets(
    model: NonPreeMultiModel,
    state: ResourceState,
    *,
    maximal_only: bool,
    operation_limit: int,
) -> Iterator[tuple[str, ...]]:
    """Yield legal start sets without materializing the complete powerset."""

    ready = tuple(sorted(model.startable_flows(state)))
    operations = 0
    if maximal_only:
        neighbors = {
            item: {
                other for other in ready
                if other != item
                and model.resources[model.index[item]].isdisjoint(
                    model.resources[model.index[other]]
                )
            }
            for item in ready
        }

        def maximal(
            chosen: tuple[str, ...],
            candidates: set[str],
            excluded: set[str],
        ) -> Iterator[tuple[str, ...]]:
            nonlocal operations
            if operations >= operation_limit:
                return
            operations += 1
            if not candidates and not excluded:
                if chosen:
                    yield chosen
                return
            pivot_pool = candidates | excluded
            pivot = max(
                pivot_pool,
                key=lambda item: (len(candidates & neighbors[item]), item),
                default=None,
            )
            branch = candidates - (neighbors[pivot] if pivot is not None else set())
            for item in sorted(branch):
                yield from maximal(
                    tuple(sorted((*chosen, item))),
                    candidates & neighbors[item],
                    excluded & neighbors[item],
                )
                candidates.remove(item)
                excluded.add(item)

        yield from maximal((), set(ready), set())
        return

    def subsets(
        position: int,
        chosen: tuple[str, ...],
        used: frozenset[Resource],
    ) -> Iterator[tuple[str, ...]]:
        nonlocal operations
        if operations >= operation_limit:
            return
        operations += 1
        if position == len(ready):
            if chosen:
                yield chosen
            return
        yield from subsets(position + 1, chosen, used)
        item = ready[position]
        resources = model.resources[model.index[item]]
        if used.isdisjoint(resources):
            yield from subsets(position + 1, (*chosen, item), used | resources)

    yield from subsets(0, (), model.occupied_resources(state))


def _rollout_candidates(
    model: NonPreeMultiModel,
    state: ResourceState,
    *,
    top_k: int,
    optional_actions: bool,
    context_cache: dict[ResourceState, ResourceDecisionContext] | None = None,
) -> tuple[ResourceAction, ...]:
    context = context_for(model, state, context_cache)
    tail = context.tail
    ranked: list[tuple[str, ...]] = []
    for selected in _iter_compatible_subsets(
        model,
        state,
        maximal_only=not optional_actions,
        operation_limit=max(64, top_k * 32),
    ):
        ranked.append(selected)
        ranked.sort(
            key=lambda item: (
                sum(tail[model.index[value]] for value in item),
                -sum(model.remaining(state, model.index[value]) for value in item),
                item,
            ),
            reverse=True,
        )
        del ranked[top_k:]
    result = [ResourceAction.start(items) for items in ranked]
    for policy in ("dynamic_tail", "resource_tail", "bottleneck_first", "spt"):
        action = greedy_action(model, state, policy, context_cache)
        if action.kind == "start" and action not in result:
            result.append(action)
    if optional_actions and model.has_future_event(state):
        result.append(ResourceAction.wait())
    if not result and model.has_future_event(state):
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
    context_cache: dict[ResourceState, ResourceDecisionContext] = {}
    actions = []
    candidate_actions = 0
    fallback = False
    while not model.is_finished(state):
        base = greedy_action(model, state, "dynamic_tail", context_cache)
        if perf_counter() - started > time_limit_s:
            action = base
            fallback = True
        else:
            candidates = _rollout_candidates(
                model,
                state,
                top_k=top_k,
                optional_actions=optional_actions,
                context_cache=context_cache,
            )
            if base not in candidates:
                candidates = (*candidates, base)
            candidate_actions += len(candidates)
            scored = []
            for action in candidates:
                transition = model.step(state, action)
                delta = transition.after.time - transition.before.time
                value = delta + complete(
                    model, transition.after, "dynamic_tail", context_cache
                )[0]
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
