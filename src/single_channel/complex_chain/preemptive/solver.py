"""Initial baselines for single-channel communication-preemptive DAGs."""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
import random
from time import perf_counter

from core.dag import BenchmarkDAG, topological_order
from core.execution.preemptive import (
    Action,
    PreemptiveDAGModel,
    PreemptiveScheduleResult,
    ScheduleState,
    result_from_trace,
)
from core.trace.preemptive import assert_preemptive_trace


PriorityName = str


def schedule_longest_tail(dag: BenchmarkDAG) -> PreemptiveScheduleResult:
    """Recompute downstream residual tails at every task event."""

    return schedule_priority(dag, "longest_tail")


def schedule_priority(
    dag: BenchmarkDAG,
    priority: PriorityName = "longest_tail",
) -> PreemptiveScheduleResult:
    """Run a deterministic work-conserving priority policy."""

    model = PreemptiveDAGModel(dag)
    state = model.initial_state()
    actions: list[Action] = []
    fifo_order = {task_id: index for index, task_id in enumerate(model.task_ids)}
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        if not eligible:
            action = Action.wait()
        else:
            tail = residual_tail(model, state)
            def key(task_id: str) -> tuple[int, str]:
                runtime = model.task_runtime(state, task_id)
                remaining = runtime.remaining or model.dag.task_map()[task_id].duration
                if priority == "fifo":
                    score = -fifo_order[task_id]
                elif priority == "spt":
                    score = -remaining
                elif priority == "lpt":
                    score = remaining
                elif priority == "longest_delay":
                    score = tail[task_id] - remaining
                elif priority == "lrpt":
                    score = tail[task_id]
                elif priority == "longest_tail":
                    score = tail[task_id] - remaining
                else:
                    raise ValueError(f"unknown preemptive priority: {priority}")
                return (-score, task_id)
            action = Action.run(min(eligible, key=key))
        actions.append(action)
        state = model.step(state, action).after
    trace = model.run(actions)
    assert_preemptive_trace(model, trace)
    return result_from_trace(trace)


def schedule_rollout(
    dag: BenchmarkDAG,
    *,
    top_k: int = 2,
    candidate_mode: str = "tail",
) -> PreemptiveScheduleResult:
    """One-event rollout using dynamic longest-tail as completion policy."""

    model = PreemptiveDAGModel(dag)
    state = model.initial_state()
    actions: list[Action] = []
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        if not eligible:
            action = Action.wait()
        else:
            tail = residual_tail(model, state)
            ranked = _rank_candidates(model, state, eligible, tail, top_k, candidate_mode)
            candidates = []
            for task_id in ranked:
                first = Action.run(task_id)
                after = model.step(state, first).after
                suffix = _complete_actions(model, after, "longest_tail")
                finish = _apply_actions(model, after, suffix).time
                candidates.append((finish, task_id, first))
            action = min(candidates)[2]
        actions.append(action)
        state = model.step(state, action).after
    trace = model.run(actions)
    assert_preemptive_trace(model, trace)
    return result_from_trace(trace)


def beam_search(
    dag: BenchmarkDAG,
    *,
    width: int = 8,
) -> PreemptiveScheduleResult:
    """Bounded event-state beam with a Longest-tail incumbent."""

    model = PreemptiveDAGModel(dag)
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
            actions = list(model.legal_actions(state))
            if model.eligible_communications(state):
                actions = [action for action in actions if action.kind == "run"]
            for action in actions:
                after = model.step(state, action).after
                key = tuple((runtime.status, runtime.remaining) for runtime in after.tasks)
                old = children.get(key)
                candidate = (after, (*prefix, action))
                if old is None or after.time < old[0].time:
                    children[key] = candidate
        if best_actions is not None:
            break
        scored = []
        for state, prefix in children.values():
            suffix = _complete_actions(model, state, "longest_tail")
            predicted = _apply_actions(model, state, suffix).time
            scored.append((predicted, state.time, len(prefix), prefix, state))
        scored.sort(key=lambda item: item[:3])
        frontier = [(item[4], item[3]) for item in scored[:width]]
    if best_actions is None:
        return incumbent
    trace = model.run(best_actions)
    assert_preemptive_trace(model, trace)
    candidate = result_from_trace(trace)
    return min((incumbent, candidate), key=lambda result: (result.makespan, result.dispatches))


def exact_oracle(
    dag: BenchmarkDAG,
    *,
    max_states: int = 500_000,
    time_limit_s: float | None = None,
) -> PreemptiveScheduleResult:
    """Exact memoized event-state search for small single-channel DAGs."""

    model = PreemptiveDAGModel(dag)
    initial = model.initial_state()
    started = perf_counter()
    states = 0
    representative: dict[tuple, ScheduleState] = {}

    def key(state: ScheduleState) -> tuple:
        return tuple((runtime.status, runtime.remaining) for runtime in state.tasks)

    @lru_cache(maxsize=None)
    def search(state_key: tuple) -> tuple[int, tuple[Action, ...]]:
        nonlocal states
        states += 1
        if states > max_states:
            raise RuntimeError(f"preemptive exact oracle exceeded {max_states} states")
        if time_limit_s is not None and perf_counter() - started > time_limit_s:
            raise TimeoutError("preemptive exact oracle exceeded time limit")
        state = representative[state_key]
        if model.is_finished(state):
            return 0, ()
        best: tuple[int, tuple[str, str], tuple[Action, ...]] | None = None
        actions = list(model.legal_actions(state))
        # With linear zero-cost service, voluntary idle is dominated while a
        # communication is eligible; retaining WAIT only for forced idle also
        # avoids exploring equivalent delayed schedules.
        if model.eligible_communications(state):
            actions = [action for action in actions if action.kind == "run"]
        for action in actions:
            transition = model.step(state, action)
            child_key = key(transition.after)
            representative.setdefault(child_key, transition.after)
            remainder, suffix = search(child_key)
            elapsed = transition.after.time - state.time
            candidate = (
                elapsed + remainder,
                (action.kind, action.task_id or ""),
                (action, *suffix),
            )
            if best is None or candidate[:2] < best[:2]:
                best = candidate
        if best is None:
            raise RuntimeError("unfinished state has no legal action")
        return best[0], best[2]

    initial_key = key(initial)
    representative[initial_key] = initial
    _cost, actions = search(initial_key)
    trace = model.run(actions)
    assert_preemptive_trace(model, trace)
    return replace(result_from_trace(trace), explored_states=states)


def monte_carlo(
    dag: BenchmarkDAG,
    *,
    samples: int = 64,
    seed: int = 0,
) -> PreemptiveScheduleResult:
    """Sample reproducible work-conserving schedules and keep the best."""

    model = PreemptiveDAGModel(dag)
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
                tail = residual_tail(model, state)
                ranked = sorted(eligible, key=lambda item: (-tail[item], item))
                pool = ranked[: max(1, min(3, len(ranked)))] if rng.random() < 0.7 else ranked
                action = Action.run(rng.choice(pool))
            actions.append(action)
            state = model.step(state, action).after
        trace = model.run(actions)
        assert_preemptive_trace(model, trace)
        candidates.append(result_from_trace(trace))
    return min(candidates, key=lambda result: (result.makespan, result.dispatches))


def _complete_actions(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    priority: str,
) -> tuple[Action, ...]:
    actions: list[Action] = []
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        if not eligible:
            action = Action.wait()
        else:
            tail = residual_tail(model, state)
            task_map = model.dag.task_map()
            if priority == "longest_tail":
                action = Action.run(min(eligible, key=lambda item: (-(tail[item] - (model.task_runtime(state, item).remaining or task_map[item].duration)), item)))
            else:
                raise ValueError(priority)
        actions.append(action)
        state = model.step(state, action).after
    return tuple(actions)


def _apply_actions(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    actions: tuple[Action, ...],
) -> ScheduleState:
    for action in actions:
        state = model.step(state, action).after
    return state


def _rank_candidates(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    eligible: tuple[str, ...],
    tail: dict[str, int],
    top_k: int,
    mode: str,
) -> list[str]:
    tail_ranked = sorted(eligible, key=lambda item: (-tail[item], item))
    if mode == "tail":
        return tail_ranked[:top_k]
    if mode not in {"join", "hybrid"}:
        raise ValueError(f"unknown candidate mode: {mode}")
    tasks = model.dag.task_map()
    children: dict[str, list[str]] = {task_id: [] for task_id in model.task_ids}
    for task in tasks.values():
        for dependency in task.deps:
            children[dependency].append(task.task_id)

    def join_score(task_id: str) -> tuple[int, int, str]:
        bonus = 0
        for child in children[task_id]:
            if len(tasks[child].deps) < 2:
                continue
            others = [dep for dep in tasks[child].deps if dep != task_id]
            if all(model.task_runtime(state, dep).status == "completed" for dep in others):
                bonus += tasks[child].duration + max(0, tail[child] - tasks[child].duration)
        return (-bonus, -tail[task_id], task_id)

    join_ranked = sorted(eligible, key=join_score)
    if mode == "join":
        return join_ranked[:top_k]
    selected: list[str] = []
    for ranked in (tail_ranked, join_ranked):
        for task_id in ranked:
            if task_id not in selected:
                selected.append(task_id)
                break
    for task_id in tail_ranked:
        if task_id not in selected:
            selected.append(task_id)
        if len(selected) == top_k:
            break
    return selected[:top_k]


def residual_tail(model: PreemptiveDAGModel, state: ScheduleState) -> dict[str, int]:
    """Longest unfinished path length including each task's remaining work."""

    order = topological_order(model.dag)
    tasks = model.dag.task_map()
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
