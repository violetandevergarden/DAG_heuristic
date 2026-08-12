"""Event-driven fluid-preemptive scheduling on fixed resource sets.

At a decision event an action selects a pairwise-compatible set of eligible
communications.  Every selected communication receives unit service on all of
its fixed resources until the first selected communication or active compute
finishes.  Other communications are suspended and release their resources.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
from time import perf_counter

from core.dag import BenchmarkDAG, topological_order


@dataclass(frozen=True)
class TaskState:
    status: str = "pending"
    remaining: int = 0


@dataclass(frozen=True)
class MultiState:
    time: int
    tasks: tuple[TaskState, ...]


@dataclass(frozen=True)
class MultiAction:
    communications: tuple[str, ...] = ()

    @property
    def is_wait(self) -> bool:
        return not self.communications


@dataclass(frozen=True)
class MultiResult:
    makespan: int
    actions: tuple[MultiAction, ...]
    decision_count: int
    preemptions: int
    explored_states: int = 0


class PreemptiveMultiResourceModel:
    def __init__(self, dag: BenchmarkDAG, resources: dict[str, frozenset[str]]):
        errors = dag.validate()
        if errors:
            raise ValueError(f"invalid DAG: {errors}")
        order = topological_order(dag)
        task_map = dag.task_map()
        self.dag = dag
        self.task_ids = tuple(order)
        self.tasks = tuple(task_map[item] for item in order)
        self.index = {item: index for index, item in enumerate(order)}
        self.deps = tuple(tuple(self.index[parent] for parent in task.deps) for task in self.tasks)
        comm_ids = {task.task_id for task in self.tasks if task.kind == "comm"}
        if set(resources) != comm_ids or any(not resources[item] for item in comm_ids):
            raise ValueError("every communication must have a non-empty fixed resource set")
        self.resources = resources

    def initial_state(self) -> MultiState:
        return self._compute_closure(MultiState(0, tuple(TaskState() for _ in self.tasks)))

    def eligible(self, state: MultiState) -> tuple[str, ...]:
        result = []
        for index, task in enumerate(self.tasks):
            runtime = state.tasks[index]
            if task.kind != "comm" or runtime.status == "completed":
                continue
            if runtime.status == "suspended" or self._deps_completed(state.tasks, index):
                result.append(task.task_id)
        return tuple(result)

    def active_computes(self, state: MultiState) -> tuple[int, ...]:
        return tuple(
            index for index, (task, runtime) in enumerate(zip(self.tasks, state.tasks, strict=True))
            if task.kind == "compute" and runtime.status == "running"
        )

    def compatible(self, items: tuple[str, ...]) -> bool:
        used: set[str] = set()
        for item in items:
            if used & self.resources[item]:
                return False
            used.update(self.resources[item])
        return True

    def maximal_actions(self, state: MultiState) -> tuple[MultiAction, ...]:
        eligible = self.eligible(state)
        compatible_sets = [
            subset
            for size in range(1, len(eligible) + 1)
            for subset in combinations(eligible, size)
            if self.compatible(subset)
        ]
        maximal = [
            subset for subset in compatible_sets
            if not any(set(subset) < set(other) for other in compatible_sets)
        ]
        if maximal:
            return tuple(MultiAction(tuple(sorted(items))) for items in maximal)
        return (MultiAction(),) if self.active_computes(state) else ()

    def step(self, state: MultiState, action: MultiAction) -> MultiState:
        eligible = set(self.eligible(state))
        selected = action.communications
        if selected:
            if not set(selected) <= eligible or not self.compatible(selected):
                raise ValueError(f"illegal multi-resource action: {action}")
        elif not self.active_computes(state):
            raise ValueError("WAIT requires an active compute")
        deltas = [state.tasks[index].remaining for index in self.active_computes(state)]
        for task_id in selected:
            runtime = state.tasks[self.index[task_id]]
            deltas.append(runtime.remaining or self.tasks[self.index[task_id]].duration)
        if not deltas:
            raise ValueError("action cannot advance time")
        delta = min(deltas)
        values = list(state.tasks)
        for index in self.active_computes(state):
            runtime = values[index]
            remaining = runtime.remaining - delta
            values[index] = TaskState("completed" if remaining == 0 else "running", remaining)
        selected_set = set(selected)
        for task_id in self.eligible(state):
            index = self.index[task_id]
            runtime = values[index]
            if task_id in selected_set:
                remaining = (runtime.remaining or self.tasks[index].duration) - delta
                values[index] = TaskState("completed" if remaining == 0 else "suspended", remaining)
            elif runtime.status == "suspended":
                values[index] = runtime
        return self._compute_closure(MultiState(state.time + delta, tuple(values)))

    def finished(self, state: MultiState) -> bool:
        return all(item.status == "completed" for item in state.tasks)

    def _compute_closure(self, state: MultiState) -> MultiState:
        values = list(state.tasks)
        changed = True
        while changed:
            changed = False
            for index, task in enumerate(self.tasks):
                if task.kind != "compute" or values[index].status != "pending":
                    continue
                if self._deps_completed(values, index):
                    values[index] = TaskState(
                        "completed" if task.duration == 0 else "running", task.duration
                    )
                    changed = True
        return MultiState(state.time, tuple(values))

    def _deps_completed(self, runtimes: tuple[TaskState, ...] | list[TaskState], index: int) -> bool:
        return all(runtimes[parent].status == "completed" for parent in self.deps[index])


def schedule_pack(
    dag: BenchmarkDAG,
    resources: dict[str, frozenset[str]],
    mode: str = "longest_tail",
) -> MultiResult:
    model = PreemptiveMultiResourceModel(dag, resources)
    state = model.initial_state()
    actions: list[MultiAction] = []
    while not model.finished(state):
        eligible = model.eligible(state)
        if not eligible:
            action = MultiAction()
        else:
            tail = _residual_tail(model, state)
            load = _resource_load(model, state)
            def key(task_id: str) -> tuple:
                bottleneck = max((load[item] for item in resources[task_id]), default=0)
                if mode == "longest_tail":
                    return (-tail[task_id], task_id)
                if mode == "resource_tail":
                    return (-tail[task_id], -bottleneck, task_id)
                if mode == "bottleneck":
                    return (-bottleneck, -tail[task_id], task_id)
                raise ValueError(mode)
            selected: list[str] = []
            for task_id in sorted(eligible, key=key):
                if model.compatible(tuple((*selected, task_id))):
                    selected.append(task_id)
            action = MultiAction(tuple(sorted(selected)))
        actions.append(action)
        state = model.step(state, action)
    return MultiResult(state.time, tuple(actions), len(actions), _count_set_preemptions(model, actions))


def rollout_sets(
    dag: BenchmarkDAG,
    resources: dict[str, frozenset[str]],
    *,
    top_k: int = 2,
) -> MultiResult:
    model = PreemptiveMultiResourceModel(dag, resources)
    state = model.initial_state()
    actions: list[MultiAction] = []
    while not model.finished(state):
        candidates = list(model.maximal_actions(state))
        if len(candidates) > top_k:
            tail = _residual_tail(model, state)
            candidates.sort(key=lambda action: (-sum(tail[item] for item in action.communications), action.communications))
            candidates = candidates[:top_k]
        scored = []
        for action in candidates:
            after = model.step(state, action)
            completion = _complete_pack(model, after)
            scored.append((completion.time, action.communications, action))
        action = min(scored)[2]
        actions.append(action)
        state = model.step(state, action)
    return MultiResult(state.time, tuple(actions), len(actions), _count_set_preemptions(model, actions))


def exact_oracle(
    dag: BenchmarkDAG,
    resources: dict[str, frozenset[str]],
    *,
    max_states: int = 300_000,
    time_limit_s: float | None = None,
) -> MultiResult:
    model = PreemptiveMultiResourceModel(dag, resources)
    initial = model.initial_state()
    representatives: dict[tuple, MultiState] = {}
    started = perf_counter()
    explored = 0

    def key(state: MultiState) -> tuple:
        return tuple((item.status, item.remaining) for item in state.tasks)

    @lru_cache(maxsize=None)
    def search(state_key: tuple) -> tuple[int, tuple[MultiAction, ...]]:
        nonlocal explored
        explored += 1
        if explored > max_states:
            raise RuntimeError("preemptive multi-resource oracle exceeded state limit")
        if time_limit_s is not None and perf_counter() - started > time_limit_s:
            raise TimeoutError("preemptive multi-resource oracle exceeded time limit")
        state = representatives[state_key]
        if model.finished(state):
            return 0, ()
        best = None
        for action in model.maximal_actions(state):
            after = model.step(state, action)
            child_key = key(after)
            representatives.setdefault(child_key, after)
            residual, suffix = search(child_key)
            candidate = (after.time - state.time + residual, action.communications, (action, *suffix))
            if best is None or candidate[:2] < best[:2]:
                best = candidate
        if best is None:
            raise RuntimeError("unfinished state has no action")
        return best[0], best[2]

    root = key(initial)
    representatives[root] = initial
    makespan, actions = search(root)
    return MultiResult(makespan, actions, len(actions), _count_set_preemptions(model, actions), explored)


def _complete_pack(model: PreemptiveMultiResourceModel, state: MultiState) -> MultiState:
    while not model.finished(state):
        eligible = model.eligible(state)
        if not eligible:
            action = MultiAction()
        else:
            tail = _residual_tail(model, state)
            selected: list[str] = []
            for task_id in sorted(eligible, key=lambda item: (-tail[item], item)):
                if model.compatible(tuple((*selected, task_id))):
                    selected.append(task_id)
            action = MultiAction(tuple(sorted(selected)))
        state = model.step(state, action)
    return state


def _residual_tail(model: PreemptiveMultiResourceModel, state: MultiState) -> dict[str, int]:
    order = topological_order(model.dag)
    tasks = model.dag.task_map()
    children = {item: [] for item in order}
    for task in tasks.values():
        for dep in task.deps:
            children[dep].append(task.task_id)
    tail: dict[str, int] = {}
    for task_id in reversed(order):
        runtime = state.tasks[model.index[task_id]]
        own = 0 if runtime.status == "completed" else (runtime.remaining or tasks[task_id].duration)
        tail[task_id] = own + max((tail[child] for child in children[task_id]), default=0)
    return tail


def _resource_load(model: PreemptiveMultiResourceModel, state: MultiState) -> dict[str, int]:
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
    actions: list[MultiAction] | tuple[MultiAction, ...],
) -> int:
    count = 0
    previous: set[str] = set()
    state = model.initial_state()
    for action in actions:
        current = set(action.communications)
        after = model.step(state, action)
        count += sum(
            after.tasks[model.index[task_id]].status != "completed"
            for task_id in previous - current
        )
        previous = current
        state = after
    return count
