"""Exact oracles for non-preemptive, optional-idle DAG scheduling.

The two solvers intentionally use different search strategies over the R0
transition system:

* ``exact_oracle`` is a memoized residual-cost dynamic program;
* ``branch_and_bound_oracle`` is a forward DFS with a feasible incumbent,
  residual lower bounds, dominance, and hard state/time limits.

Both can solve the true optional-idle problem or its work-conserving
restriction. They return whole-flow/WAIT actions and reconstruct a continuous
timeline through :mod:`core.execution.nonpreemptive`.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from time import perf_counter
from typing import Literal, Sequence

from core.dag import DAG
from core.execution.nonpreemptive import (
    Action,
    NonPreeSingleModel,
    RuntimeTask,
    ScheduleState,
    ScheduleTrace,
)
from core.trace.nonpreemptive import assert_nonpreemptive_trace

OracleMode = Literal["optional_idle", "work_conserving"]
StateKey = tuple[tuple[str, int], ...]
GreedyStrategy = tuple[bool, bool]
GREEDY_STRATEGIES: tuple[GreedyStrategy, ...] = (
    (False, False),
    (False, True),
    (True, False),
    (True, True),
)


@dataclass(frozen=True)
class OracleSearchConfig:
    max_states: int = 2_000_000
    time_limit_s: float = 40.0


@dataclass(frozen=True)
class NonPreemptiveOracleResult:
    mode: OracleMode
    makespan: int
    actions: tuple[Action, ...]
    trace: ScheduleTrace
    explored_states: int
    cache_hits: int
    runtime_ms: float
    lower_bounds: dict[str, int]
    voluntary_waits: int
    forced_waits: int
    voluntary_wait_time: int
    forced_wait_time: int
    wait_time: int


@dataclass(frozen=True)
class OracleComparison:
    optional_idle: NonPreemptiveOracleResult
    work_conserving: NonPreemptiveOracleResult

    @property
    def idle_regret(self) -> int:
        return self.work_conserving.makespan - self.optional_idle.makespan


class OracleStateManager:
    """Serialize decision states and enumerate legal oracle transitions."""

    def __init__(self, model: NonPreeSingleModel, mode: OracleMode):
        self.model = model
        self.mode = mode

    def key(self, state: ScheduleState) -> StateKey:
        if state.active_flow is not None:
            raise ValueError("oracle keys are defined only at idle-channel decisions")
        return tuple((runtime.status, runtime.remaining) for runtime in state.tasks)

    def from_key(self, key: StateKey) -> ScheduleState:
        runtimes: list[RuntimeTask] = []
        for status, remaining in key:
            if status == "pending":
                runtimes.append(RuntimeTask())
            elif status == "running":
                runtimes.append(RuntimeTask("running", remaining, 0, None))
            elif status == "completed":
                runtimes.append(RuntimeTask("completed", 0, 0, 0))
            else:
                raise ValueError(f"unknown runtime status in oracle key: {status}")
        return ScheduleState(0, tuple(runtimes))

    def candidate_actions(self, state: ScheduleState) -> tuple[Action, ...]:
        ready = self.model.ready_flows(state)
        flows = tuple(Action.flow(task_id) for task_id in ready)
        can_wait = bool(self.model.active_computes(state))
        if self.mode == "work_conserving":
            return flows if flows else ((Action.wait(),) if can_wait else ())
        if self.mode == "optional_idle":
            return (*flows, Action.wait()) if can_wait else flows
        raise ValueError(f"unknown oracle mode: {self.mode}")

    def successors(self, state: ScheduleState) -> list[tuple[Action, int, StateKey]]:
        result: list[tuple[Action, int, StateKey]] = []
        seen: set[StateKey] = set()
        for action in self.candidate_actions(state):
            transition = self.model.step(state, action)
            successor = self.key(transition.after)
            if successor in seen:
                continue
            seen.add(successor)
            result.append((action, transition.after.time - state.time, successor))
        return result


class OracleBounds:
    """Initial and residual lower bounds used by both search strategies."""

    def __init__(self, dag: DAG, model: NonPreeSingleModel):
        self.dag = dag
        self.model = model
        self._tails: dict[str, int] | None = None

    @staticmethod
    def _compute_tail_lengths(dag: DAG) -> dict[str, int]:
        # 用于longest tail
        order = dag.topological_order()
        tasks = dag.task_map()
        children: dict[str, list[str]] = {task_id: [] for task_id in order}
        for task in tasks.values():
            for parent in task.deps:
                children[parent].append(task.task_id)
        tails: dict[str, int] = {}
        for task_id in reversed(order):
            tails[task_id] = max(
                (tasks[child].duration + tails[child] for child in children[task_id]),
                default=0,
            )
        return tails

    def tail_lengths(self) -> dict[str, int]:
        if self._tails is None:
            self._tails = self._compute_tail_lengths(self.dag)
        return self._tails

    def release_tail(self) -> int:
        # 用于计算全图的初始下界
        order = self.dag.topological_order()
        tasks = self.dag.task_map()
        children: dict[str, list[str]] = {task_id: [] for task_id in order}
        for task in tasks.values():
            for parent in task.deps:
                children[parent].append(task.task_id)
        compute_earliest: dict[str, int] = {}
        for task_id in order:
            task = tasks[task_id]
            compute_earliest[task_id] = max(
                (compute_earliest[parent] for parent in task.deps), default=0
            ) + (task.duration if task.kind == "compute" else 0)
        compute_tail: dict[str, int] = {}
        for task_id in reversed(order):
            compute_tail[task_id] = max(
                (
                    (tasks[child].duration if tasks[child].kind == "compute" else 0)
                    + compute_tail[child]
                    for child in children[task_id]
                ),
                default=0,
            )
        comms = [task for task in self.dag.tasks if task.kind == "comm"]
        if not comms:
            return max(compute_earliest.values(), default=0)
        releases = {
            task.task_id: max(
                (compute_earliest[parent] for parent in task.deps), default=0
            )
            for task in comms
        }
        release_values = {0, *(releases[task.task_id] for task in comms)}
        tail_values = {0, *(compute_tail[task.task_id] for task in comms)}
        best = 0
        for release in release_values:
            for tail in tail_values:
                work = sum(
                    task.duration
                    for task in comms
                    if releases[task.task_id] >= release
                    and compute_tail[task.task_id] >= tail
                )
                if work:
                    best = max(best, release + work + tail)
        return best

    def initial(self) -> dict[str, int]:
        result = dict(self.dag.lower_bounds())
        result["release_tail"] = self.release_tail()
        initial = self.model.initial_state()
        result["next_event"] = (
            min(
                self.model.task_runtime(initial, task_id).remaining
                for task_id in self.model.active_computes(initial)
            )
            if not self.model.ready_flows(initial)
            and self.model.active_computes(initial)
            else 0
        )
        result["combined"] = max(result.values())
        return result

    def residual(self, key: StateKey) -> int:
        # 计算剩余图的下界: max(communication load, critical path)，用于剪枝
        durations = [
            (
                0
                if status == "completed"
                else remaining if status == "running" else task.duration
            )
            for task, (status, remaining) in zip(self.model.tasks, key, strict=True)
        ]
        communication = sum(
            duration
            for task, duration in zip(self.model.tasks, durations, strict=True)
            if task.kind == "comm"
        )
        path = [0] * len(self.model.tasks)
        for index in reversed(range(len(self.model.tasks))):
            children = [
                child
                for child, parents in enumerate(self.model.deps)
                if index in parents
            ]
            path[index] = durations[index] + max(
                (path[child] for child in children), default=0
            )
        return max(communication, max(path, default=0))


class OracleSolver:
    """Shared infrastructure; subclasses are unnecessary for the two searches."""

    def __init__(self, dag: DAG, mode: OracleMode, config: OracleSearchConfig):
        self.model = NonPreeSingleModel(dag)
        self.mode = mode
        self.config = config
        self.states = OracleStateManager(self.model, mode)
        self.bounds = OracleBounds(dag, self.model)

    def greedy_completion(
        self,
        state: ScheduleState,
        *,
        wait_when_ready: bool,
        longest_tail: bool,
    ) -> tuple[int, tuple[Action, ...]]:
        elapsed = 0
        actions: list[Action] = []
        tails = self.bounds.tail_lengths()
        while not self.model.is_finished(state):
            ready = self.model.ready_flows(state)
            active = self.model.active_computes(state)
            if active and (wait_when_ready or not ready):
                action = Action.wait()
            elif ready:
                task_id = (
                    max(ready, key=lambda item: (tails[item], item))
                    if longest_tail
                    else ready[0]
                )
                action = Action.flow(task_id)
            else:
                raise RuntimeError(
                    "unfinished DAG has no ready flow or active compute"
                )
            actions.append(action)
            transition = self.model.step(state, action)
            elapsed += transition.after.time - state.time
            state = transition.after
        return elapsed, tuple(actions)

    def greedy_candidates(
        self, state: ScheduleState
    ) -> tuple[tuple[int, tuple[Action, ...]], ...]:
        if self.mode == "work_conserving":
            strategies = tuple(
                strategy for strategy in GREEDY_STRATEGIES if not strategy[0]
            )
        elif self.mode == "optional_idle":
            strategies = GREEDY_STRATEGIES
        else:
            raise ValueError(f"unknown oracle mode: {self.mode}")
        return tuple(
            self.greedy_completion(
                state,
                wait_when_ready=wait,
                longest_tail=tail,
            )
            for wait, tail in strategies
        )

    def check_limits(self, explored: int, started: float, algorithm: str) -> None:
        if explored > self.config.max_states:
            raise RuntimeError(
                f"{algorithm} exceeded max_states={self.config.max_states}"
            )
        if perf_counter() - started > self.config.time_limit_s:
            raise TimeoutError(
                f"{algorithm} exceeded time_limit_s={self.config.time_limit_s}"
            )

    def ranked_successors(
        self, state: ScheduleState, elapsed: int = 0
    ) -> list[tuple[Action, int, StateKey]]:
        return sorted(
            self.states.successors(state),
            key=lambda item: (
                elapsed + item[1] + self.bounds.residual(item[2]),
                item[0].kind == "wait",
                item[0].task_id or "",
            ),
        )

    def replay_result(
        self,
        actions: Sequence[Action],
        explored_states: int,
        cache_hits: int,
        runtime_ms: float,
        expected_makespan: int | None = None,
    ) -> NonPreemptiveOracleResult:
        trace = self.model.run(actions)
        if not self.model.is_finished(trace.final_state):
            raise AssertionError("oracle action path did not finish the DAG")
        assert_nonpreemptive_trace(self.model.dag, trace, mode=self.mode)
        voluntary_waits = forced_waits = voluntary_wait_time = forced_wait_time = 0
        wait_time = 0
        for transition in trace.transitions:
            if transition.action.kind != "wait":
                continue
            duration = transition.after.time - transition.before.time
            wait_time += duration
            if self.model.ready_flows(transition.before):
                voluntary_waits += 1
                voluntary_wait_time += duration
            else:
                forced_waits += 1
                forced_wait_time += duration
        bounds = self.bounds.initial()
        if bounds["combined"] > trace.makespan:
            raise AssertionError(
                f"invalid lower bound {bounds} > optimum {trace.makespan}"
            )
        if expected_makespan is not None and trace.makespan != expected_makespan:
            raise AssertionError(
                f"replay {trace.makespan} != expected {expected_makespan}"
            )
        return NonPreemptiveOracleResult(
            self.mode,
            trace.makespan,
            tuple(actions),
            trace,
            explored_states,
            cache_hits,
            runtime_ms,
            bounds,
            voluntary_waits,
            forced_waits,
            voluntary_wait_time,
            forced_wait_time,
            wait_time,
        )

    def finalize(
        self,
        actions: Sequence[Action],
        explored_states: int,
        cache_hits: int,
        started: float,
        expected_makespan: int,
    ) -> NonPreemptiveOracleResult:
        return self.replay_result(
            actions,
            explored_states,
            cache_hits,
            (perf_counter() - started) * 1000,
            expected_makespan,
        )


def _config(
    config: OracleSearchConfig | None,
    max_states: int | None,
    time_limit_s: float | None,
) -> OracleSearchConfig:
    if config is not None and (max_states is not None or time_limit_s is not None):
        raise ValueError("config cannot be combined with max_states or time_limit_s")
    return config or OracleSearchConfig(
        max_states=2_000_000 if max_states is None else max_states,
        time_limit_s=30.0 if time_limit_s is None else time_limit_s,
    )


def exact_oracle(
    dag: DAG,
    *,
    mode: OracleMode = "optional_idle",
    max_states: int | None = None,
    time_limit_s: float | None = None,
    config: OracleSearchConfig | None = None,
) -> NonPreemptiveOracleResult:
    config = _config(config, max_states, time_limit_s)
    solver = OracleSolver(dag, mode, config)
    initial = solver.states.key(solver.model.initial_state())
    explored = 0
    started = perf_counter()

    @lru_cache(maxsize=None)
    def solve(key: StateKey) -> tuple[int, tuple[Action, ...]]:
        nonlocal explored
        explored += 1
        solver.check_limits(explored, started, "exact oracle")
        state = solver.states.from_key(key)
        if solver.model.is_finished(state):
            return 0, ()
        successors = solver.states.successors(state)
        if not successors:
            raise RuntimeError("unfinished DAG has no legal action")
        best_value, best_path = min(
            solver.greedy_candidates(state), key=lambda item: item[0]
        )
        ranked = solver.ranked_successors(state)
        for action, elapsed, successor in ranked:
            if elapsed + solver.bounds.residual(successor) >= best_value:
                continue
            child_value, child_path = solve(successor)
            value = elapsed + child_value
            tie = "~WAIT" if action.kind == "wait" else action.task_id or ""
            best_tie = (
                "~WAIT"
                if best_path and best_path[0].kind == "wait"
                else (best_path[0].task_id or "") if best_path else ""
            )
            if (value, tie) < (best_value, best_tie):
                best_value, best_path = value, (action, *child_path)
        return best_value, best_path

    optimum, actions = solve(initial)
    return solver.finalize(actions, explored, solve.cache_info().hits, started, optimum)


def branch_and_bound_oracle(
    dag: DAG,
    *,
    mode: OracleMode = "optional_idle",
    max_states: int | None = None,
    time_limit_s: float | None = None,
    config: OracleSearchConfig | None = None,
) -> NonPreemptiveOracleResult:
    config = _config(config, max_states, time_limit_s)
    solver = OracleSolver(dag, mode, config)
    incumbent = min(
        solver.greedy_candidates(solver.model.initial_state()), key=lambda item: item[0]
    )[1]
    best_actions = incumbent
    best_time = solver.model.run(incumbent).makespan
    initial = solver.states.key(solver.model.initial_state())
    seen_elapsed: dict[StateKey, int] = {}
    explored = 0
    started = perf_counter()

    def visit(key: StateKey, elapsed: int, path: tuple[Action, ...]) -> None:
        nonlocal best_actions, best_time, explored
        explored += 1
        solver.check_limits(explored, started, "branch-and-bound")
        state = solver.states.from_key(key)
        if solver.model.is_finished(state):
            if elapsed < best_time:
                best_time, best_actions = elapsed, path
            return
        if elapsed + solver.bounds.residual(key) >= best_time:
            return
        if seen_elapsed.get(key, best_time + 1) <= elapsed:
            return
        seen_elapsed[key] = elapsed
        ranked = solver.ranked_successors(state, elapsed)
        for action, duration, successor in ranked:
            visit(successor, elapsed + duration, (*path, action))

    visit(initial, 0, ())
    return solver.finalize(best_actions, explored, 0, started, best_time)


def compare_oracles(
    dag: DAG,
    *,
    max_states: int | None = None,
    time_limit_s: float | None = None,
    config: OracleSearchConfig | None = None,
) -> OracleComparison:
    config = _config(config, max_states, time_limit_s)
    return OracleComparison(
        exact_oracle(dag, mode="optional_idle", config=config),
        exact_oracle(dag, mode="work_conserving", config=config),
    )
