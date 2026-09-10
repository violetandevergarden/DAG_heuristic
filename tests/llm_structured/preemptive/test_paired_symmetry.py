"""Certificate guards and paired-exact checks for Stage 4b symmetry claims."""

from __future__ import annotations

from dataclasses import replace

import pytest

from core.dag import DAG
from llm_structured.preemptive.repetition.solver import build_exchangeable_replicas, exact_oracle_paired


def _cross_edge_dag(replicas: int) -> tuple[DAG, tuple[tuple[str, ...], ...]]:
    """Same replicas fixture with one cross-component edge injected."""

    dag, components = build_exchangeable_replicas(replicas)
    tasks = list(dag.tasks)
    first = components[0]
    second = components[1]
    target = next(task for task in tasks if task.task_id == second[0])
    parent = first[2]  # compute of component 0
    assert target.task_id not in target.deps
    tasks[tasks.index(target)] = replace(target, deps=(*target.deps, parent))
    return (
        replace(dag, name=f"{dag.name}_cross_edge", tasks=tuple(tasks)),
        components,
    )


def test_paired_quotient_refuses_cross_component_edges() -> None:
    dag, components = _cross_edge_dag(2)
    with pytest.raises(ValueError, match="cross-component"):
        exact_oracle_paired(dag, components, quotient=True, max_states=10_000)


def test_paired_quotient_refuses_different_durations() -> None:
    dag, components = build_exchangeable_replicas(2)
    tasks = list(dag.tasks)
    target = next(task for task in tasks if task.task_id == "rep1_reduce")
    tasks[tasks.index(target)] = replace(target, duration=target.duration + 1)
    dag = replace(dag, tasks=tuple(tasks))
    with pytest.raises(ValueError, match="labels are not identical"):
        exact_oracle_paired(dag, components, quotient=True, max_states=10_000)


def test_paired_quotient_refuses_different_resource_sets() -> None:
    dag, components = build_exchangeable_replicas(2)
    resources = {
        task.task_id: frozenset({"channel:0"})
        for task in dag.tasks
        if task.kind == "comm"
    }
    resources["rep1_reduce"] = frozenset({"fabric:b"})
    with pytest.raises(ValueError, match="resource sets are not identical"):
        exact_oracle_paired(
            dag, components, quotient=True, resources=resources, max_states=10_000
        )


def test_paired_quotient_accepts_identical_resource_sets() -> None:
    dag, components = build_exchangeable_replicas(3)
    resources = {
        task.task_id: frozenset({"channel:0"})
        for task in dag.tasks
        if task.kind == "comm"
    }
    plain = exact_oracle_paired(dag, components, quotient=True, max_states=100_000)
    with_resources = exact_oracle_paired(
        dag, components, quotient=True, resources=resources, max_states=100_000
    )
    assert with_resources.makespan == plain.makespan


def test_identity_key_is_finer_than_quotient_key() -> None:
    # Both modes must produce the same optimum across the replica range, and
    # the quotient must never explore more states than identity.
    for replicas in (2, 3, 4):
        dag, components = build_exchangeable_replicas(replicas)
        identity = exact_oracle_paired(
            dag, components, quotient=False, max_states=200_000
        )
        quotient = exact_oracle_paired(
            dag, components, quotient=True, max_states=200_000
        )
        assert identity.status == quotient.status == "optimal"
        assert identity.makespan == quotient.makespan
        assert quotient.explored_states <= identity.explored_states
