"""Residual quantities shared by Stage 4 baselines and research policies."""

from __future__ import annotations


def single_residual_tail(model, state) -> dict[str, int]:
    children = [[] for _ in model.tasks]
    for child, parents in enumerate(model.deps):
        for parent in parents:
            children[parent].append(child)
    values = [0] * len(model.tasks)
    for index in reversed(range(len(model.tasks))):
        runtime = state.tasks[index]
        duration = (
            0
            if runtime.status == "completed"
            else (runtime.remaining if runtime.status == "running" else model.tasks[index].duration)
        )
        values[index] = duration + max((values[child] for child in children[index]), default=0)
    return {task.task_id: values[index] for index, task in enumerate(model.tasks)}
