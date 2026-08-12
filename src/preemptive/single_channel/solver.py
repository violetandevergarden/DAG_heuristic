"""Initial baselines for single-channel communication-preemptive DAGs."""

from __future__ import annotations

from core.dag import BenchmarkDAG, topological_order
from preemptive.core.model import (
    Action,
    PreemptiveDAGModel,
    PreemptiveScheduleResult,
    ScheduleState,
    assert_preemptive_trace,
    result_from_trace,
)


def schedule_longest_tail(dag: BenchmarkDAG) -> PreemptiveScheduleResult:
    """Recompute residual critical tails at every task event.

    This is a work-conserving baseline.  It supports arbitrary fork/join DAGs
    but does not claim optimality or a constant approximation ratio.
    """

    model = PreemptiveDAGModel(dag)
    state = model.initial_state()
    actions: list[Action] = []
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        if eligible:
            tail = residual_tail(model, state)
            chosen = min(eligible, key=lambda task_id: (-tail[task_id], task_id))
            action = Action.run(chosen)
        else:
            action = Action.wait()
        actions.append(action)
        state = model.step(state, action).after
    trace = model.run(actions)
    assert_preemptive_trace(model, trace)
    return result_from_trace(trace)


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

