"""R3 study: non-preemptive optional-idle scheduling on general DAGs.

The implementation is deliberately isolated from the production executor.  It
uses the R0 transition system, so an action either runs one whole communication
or waits until the next compute completion.  DAG features propose candidates;
complete counterfactual schedules evaluate them.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter
from typing import Literal

ROOT = Path(__file__).resolve().parents[2]

from core.dag import DAG
from core.execution.nonpreemptive import (
    Action,
    NonPreeSingleModel,
    ScheduleState,
    ScheduleTrace,
)
from core.trace.nonpreemptive import assert_nonpreemptive_trace

CandidateMode = Literal["dynamic", "hybrid"]


@dataclass(frozen=True)
class ResidualFeatures:
    path: tuple[int, ...]
    tail_after: tuple[int, ...]
    earliest_finish: tuple[int, ...]
    join_gain: tuple[int, ...]
    next_compute_release: int | None
    communication_bound: int
    critical_path_bound: int

    @property
    def lower_bound(self) -> int:
        return max(self.communication_bound, self.critical_path_bound)


@dataclass(frozen=True)
class GeneralSchedule:
    makespan: int
    actions: tuple[Action, ...]
    trace: ScheduleTrace
    voluntary_waits: int
    voluntary_wait_time: int
    forced_waits: int
    forced_wait_time: int
    runtime_ms: float
    fallback: bool = False


class ResidualGeneralDAG:
    """Residual critical paths and candidate generators for an R0 model."""

    def __init__(self, dag: DAG):
        self.model = NonPreeSingleModel(dag)
        children: list[list[int]] = [[] for _ in self.model.tasks]
        for child, parents in enumerate(self.model.deps):
            for parent in parents:
                children[parent].append(child)
        self.children = tuple(tuple(items) for items in children)

    def remaining(self, state: ScheduleState, index: int) -> int:
        runtime = state.tasks[index]
        if runtime.status == "completed":
            return 0
        if runtime.status == "running":
            return runtime.remaining
        return self.model.tasks[index].duration

    def analyze(self, state: ScheduleState) -> ResidualFeatures:
        count = len(self.model.tasks)
        remaining = [self.remaining(state, index) for index in range(count)]
        earliest = [0] * count
        for index in range(count):
            if remaining[index] == 0:
                continue
            predecessor = max(
                (
                    earliest[parent]
                    for parent in self.model.deps[index]
                    if remaining[parent] > 0
                ),
                default=0,
            )
            earliest[index] = predecessor + remaining[index]

        path = [0] * count
        tail_after = [0] * count
        for index in reversed(range(count)):
            if remaining[index] == 0:
                continue
            tail_after[index] = max(
                (path[child] for child in self.children[index]), default=0
            )
            path[index] = remaining[index] + tail_after[index]

        join_gain = [0] * count
        for child, parents in enumerate(self.model.deps):
            unfinished = [parent for parent in parents if remaining[parent] > 0]
            if len(parents) < 2 or not unfinished:
                continue
            for parent in unfinished:
                other = max(
                    (earliest[item] for item in unfinished if item != parent),
                    default=0,
                )
                gain = max(0, earliest[parent] - other)
                join_gain[parent] = max(join_gain[parent], gain + path[child])

        running_compute = [
            state.tasks[index].remaining
            for index, task in enumerate(self.model.tasks)
            if task.kind == "compute" and state.tasks[index].status == "running"
        ]
        communication = sum(
            remaining[index]
            for index, task in enumerate(self.model.tasks)
            if task.kind == "comm"
        )
        return ResidualFeatures(
            tuple(path),
            tuple(tail_after),
            tuple(earliest),
            tuple(join_gain),
            min(running_compute) if running_compute else None,
            communication,
            max(path, default=0),
        )

    def ranked(self, state: ScheduleState, source: str) -> list[str]:
        ready = list(self.model.ready_flows(state))
        analysis = self.analyze(state)

        def index(task_id: str) -> int:
            return self.model.index[task_id]

        if source == "dynamic":
            key = lambda task_id: (
                analysis.tail_after[index(task_id)],
                -self.remaining(state, index(task_id)),
                task_id,
            )
            return sorted(ready, key=key, reverse=True)
        if source == "raw_join":
            key = lambda task_id: (
                analysis.tail_after[index(task_id)]
                + analysis.join_gain[index(task_id)],
                analysis.join_gain[index(task_id)],
                analysis.tail_after[index(task_id)],
                task_id,
            )
            return sorted(ready, key=key, reverse=True)
        if source == "join":
            key = lambda task_id: (
                analysis.join_gain[index(task_id)],
                analysis.tail_after[index(task_id)],
                task_id,
            )
            return sorted(ready, key=key, reverse=True)
        if source == "spt":
            return sorted(
                ready,
                key=lambda task_id: (
                    self.remaining(state, index(task_id)), task_id
                ),
            )
        if source == "longest_delay":
            def delay(task_id: str) -> int:
                item = index(task_id)
                return max(
                    (
                        self.remaining(state, child)
                        for child in self.children[item]
                        if self.model.tasks[child].kind == "compute"
                    ),
                    default=0,
                )

            return sorted(ready, key=lambda task_id: (delay(task_id), task_id), reverse=True)
        if source == "future_release":
            release = analysis.next_compute_release
            if release is None:
                return self.ranked(state, "dynamic")
            # Prefer a complete flow that fits before the next release, then
            # minimize overrun.  This is only a candidate source, not a score.
            return sorted(
                ready,
                key=lambda task_id: (
                    self.remaining(state, index(task_id)) > release,
                    max(0, self.remaining(state, index(task_id)) - release),
                    -analysis.tail_after[index(task_id)],
                    task_id,
                ),
            )
        raise ValueError(f"unknown candidate source: {source}")

    def candidates(
        self,
        state: ScheduleState,
        *,
        top_k: int,
        mode: CandidateMode,
        allow_wait: bool,
    ) -> tuple[Action, ...]:
        ready = self.model.ready_flows(state)
        if not ready:
            return (Action.wait(),) if self.model.active_computes(state) else ()
        selected = self.ranked(state, "dynamic")[:top_k]
        if mode == "hybrid":
            for source in ("spt", "longest_delay", "join", "future_release"):
                ranked = self.ranked(state, source)
                if ranked and ranked[0] not in selected:
                    selected.append(ranked[0])
        actions = [Action.flow(task_id) for task_id in selected]
        if allow_wait and self.model.active_computes(state):
            actions.append(Action.wait())
        return tuple(dict.fromkeys(actions))


def _base_action(
    graph: ResidualGeneralDAG, state: ScheduleState, policy: str
) -> Action:
    ready = graph.model.ready_flows(state)
    if ready:
        source = "raw_join" if policy == "raw_join" else "dynamic"
        return Action.flow(graph.ranked(state, source)[0])
    if graph.model.active_computes(state):
        return Action.wait()
    raise RuntimeError("unfinished DAG has no legal action")


def _complete(
    graph: ResidualGeneralDAG,
    state: ScheduleState,
    policy: str = "dynamic",
) -> tuple[int, tuple[Action, ...]]:
    elapsed = 0
    actions: list[Action] = []
    while not graph.model.is_finished(state):
        action = _base_action(graph, state, policy)
        transition = graph.model.step(state, action)
        elapsed += transition.after.time - transition.before.time
        actions.append(action)
        state = transition.after
    return elapsed, tuple(actions)


def _result(
    graph: ResidualGeneralDAG,
    actions: Iterable[Action],
    runtime_ms: float,
    *,
    fallback: bool = False,
) -> GeneralSchedule:
    path = tuple(actions)
    trace = graph.model.run(path)
    assert graph.model.is_finished(trace.final_state)
    assert_nonpreemptive_trace(graph.model.dag, trace, mode="optional_idle")
    voluntary_waits = voluntary_wait_time = 0
    forced_waits = forced_wait_time = 0
    for transition in trace.transitions:
        if transition.action.kind != "wait":
            continue
        duration = transition.after.time - transition.before.time
        if graph.model.ready_flows(transition.before):
            voluntary_waits += 1
            voluntary_wait_time += duration
        else:
            forced_waits += 1
            forced_wait_time += duration
    return GeneralSchedule(
        trace.makespan,
        path,
        trace,
        voluntary_waits,
        voluntary_wait_time,
        forced_waits,
        forced_wait_time,
        runtime_ms,
        fallback,
    )


def schedule_priority(dag: DAG, policy: str = "dynamic") -> GeneralSchedule:
    started = perf_counter()
    graph = ResidualGeneralDAG(dag)
    _elapsed, actions = _complete(graph, graph.model.initial_state(), policy)
    return _result(graph, actions, (perf_counter() - started) * 1000)


def _lookahead_value(
    graph: ResidualGeneralDAG,
    state: ScheduleState,
    *,
    depth: int,
    top_k: int,
    mode: CandidateMode,
    allow_wait: bool,
) -> int:
    if graph.model.is_finished(state):
        return 0
    if depth == 0:
        return _complete(graph, state)[0]
    values = []
    for action in graph.candidates(
        state, top_k=top_k, mode=mode, allow_wait=allow_wait
    ):
        transition = graph.model.step(state, action)
        delta = transition.after.time - transition.before.time
        values.append(
            delta
            + _lookahead_value(
                graph,
                transition.after,
                depth=depth - 1,
                top_k=top_k,
                mode=mode,
                allow_wait=allow_wait,
            )
        )
    if not values:
        raise RuntimeError("unfinished DAG has no rollout candidate")
    return min(values)


def schedule_rollout(
    dag: DAG,
    *,
    top_k: int = 2,
    allow_wait: bool,
    candidate_mode: CandidateMode = "dynamic",
    depth: int = 1,
    time_limit_s: float = 2.0,
) -> GeneralSchedule:
    if top_k < 1 or depth < 1:
        raise ValueError("top_k and depth must be positive")
    started = perf_counter()
    graph = ResidualGeneralDAG(dag)
    baseline = schedule_priority(dag)
    state = graph.model.initial_state()
    actions: list[Action] = []
    fallback = False
    while not graph.model.is_finished(state):
        base = _base_action(graph, state, "dynamic")
        if perf_counter() - started > time_limit_s:
            action = base
            fallback = True
        else:
            scored = []
            candidates = graph.candidates(
                state,
                top_k=top_k,
                mode=candidate_mode,
                allow_wait=allow_wait,
            )
            if base not in candidates:
                candidates = (*candidates, base)
            for action in candidates:
                transition = graph.model.step(state, action)
                delta = transition.after.time - transition.before.time
                value = delta + _lookahead_value(
                    graph,
                    transition.after,
                    depth=depth - 1,
                    top_k=top_k,
                    mode=candidate_mode,
                    allow_wait=allow_wait,
                )
                scored.append(
                    (value, action != base, action.kind == "wait", action.task_id or "", action)
                )
            action = min(scored, key=lambda item: item[:-1])[-1]
        transition = graph.model.step(state, action)
        actions.append(action)
        state = transition.after
    result = _result(
        graph, actions, (perf_counter() - started) * 1000, fallback=fallback
    )
    if baseline.makespan < result.makespan:
        return replace(
            baseline,
            runtime_ms=(perf_counter() - started) * 1000,
            fallback=fallback,
        )
    return result


def beam_search(
    dag: DAG,
    *,
    width: int = 8,
    allow_wait: bool = True,
    candidate_mode: CandidateMode = "hybrid",
    top_k: int = 2,
    state_budget: int = 100_000,
    time_limit_s: float = 2.0,
) -> GeneralSchedule:
    if width < 1:
        raise ValueError("width must be positive")
    started = perf_counter()
    graph = ResidualGeneralDAG(dag)
    incumbent = schedule_priority(dag)
    best = incumbent
    frontier: dict[ScheduleState, tuple[Action, ...]] = {
        graph.model.initial_state(): ()
    }
    explored = 0
    fallback = False
    while frontier:
        successors: dict[ScheduleState, tuple[Action, ...]] = {}
        for state, path in frontier.items():
            candidates = graph.candidates(
                state,
                top_k=top_k,
                mode=candidate_mode,
                allow_wait=allow_wait,
            )
            for action in candidates:
                explored += 1
                if explored > state_budget or perf_counter() - started > time_limit_s:
                    fallback = True
                    successors = {}
                    frontier = {}
                    break
                transition = graph.model.step(state, action)
                child = transition.after
                child_path = (*path, action)
                if graph.model.is_finished(child):
                    candidate = _result(graph, child_path, 0.0)
                    if candidate.makespan < best.makespan:
                        best = candidate
                    continue
                if child.time + graph.analyze(child).lower_bound >= best.makespan:
                    continue
                old = successors.get(child)
                if old is None or len(child_path) < len(old):
                    successors[child] = child_path
            if not frontier:
                break
        if not successors:
            break
        ranked = sorted(
            successors.items(),
            key=lambda item: (
                item[0].time + graph.analyze(item[0]).lower_bound,
                item[0].time + _complete(graph, item[0])[0],
                tuple(
                    "~WAIT" if action.kind == "wait" else action.task_id or ""
                    for action in item[1]
                ),
            ),
        )[:width]
        frontier = dict(ranked)
    return replace(
        best,
        runtime_ms=(perf_counter() - started) * 1000,
        fallback=fallback,
    )
