"""Parallel-chain boundary for the shared preemptive event engine."""

from __future__ import annotations

from core.dag import BenchmarkDAG
from core.execution.preemptive import PreemptiveScheduleResult
from single_channel.parallel_chain.preemptive import solver


def validate_parallel_chain(dag: BenchmarkDAG) -> None:
    errors = dag.validate()
    if errors:
        raise ValueError(f"invalid benchmark DAG {dag.name}: {errors}")
    indegree = {task.task_id: len(task.deps) for task in dag.tasks}
    outdegree = {task.task_id: 0 for task in dag.tasks}
    for task in dag.tasks:
        for parent in task.deps:
            outdegree[parent] += 1
    offenders = sorted(
        task_id
        for task_id in indegree
        if indegree[task_id] > 1 or outdegree[task_id] > 1
    )
    if offenders:
        raise ValueError(f"parallel-chain DAG contains fork/join nodes: {offenders}")


def solve(dag: BenchmarkDAG, algorithm: str = "longest_tail") -> PreemptiveScheduleResult:
    validate_parallel_chain(dag)
    algorithms = {
        "longest_tail": solver.schedule_longest_tail,
        "rollout2": solver.schedule_rollout,
        "beam8": lambda item: solver.beam_search(item, width=8),
        "exact": solver.exact_oracle,
    }
    try:
        implementation = algorithms[algorithm]
    except KeyError as error:
        raise ValueError(f"unknown preemptive parallel-chain algorithm: {algorithm}") from error
    return implementation(dag)
