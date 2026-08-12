"""Adapters from the public file model to internal scheduling structures."""

from __future__ import annotations

from collections import defaultdict

from benchmark import Benchmark
from core.dag import BenchmarkDAG, BenchTask


def to_internal_dag(benchmark: Benchmark) -> BenchmarkDAG:
    """Convert a neutral benchmark without changing its scheduling semantics."""

    return BenchmarkDAG(
        name=benchmark.benchmark_id,
        category=benchmark.category,
        tasks=tuple(
            BenchTask(
                task_id=task.task_id,
                kind="comm" if task.kind == "communication" else "compute",
                duration=task.duration,
                deps=task.dependencies,
                role=str(
                    task.metadata.get("task_role", task.metadata.get("role", ""))
                ),
                cut=str(task.metadata.get("cut", "")),
            )
            for task in benchmark.tasks
        ),
        description=str(benchmark.metadata.get("description", "")),
        parameters=tuple(
            sorted(
                (str(key), str(value))
                for key, value in benchmark.metadata.get("parameters", {}).items()
            )
        ),
    )


def to_parallel_chains(benchmark: Benchmark):
    """Recognize parallel-chain components and build the compact solver input."""

    from single_channel.parallel_chain.solver import ParallelChain

    if benchmark.family != "parallel_chain":
        raise ValueError(f"expected parallel_chain, got {benchmark.family}")
    tasks = benchmark.task_map()
    children: dict[str, list[str]] = defaultdict(list)
    for task in benchmark.tasks:
        for dependency in task.dependencies:
            children[dependency].append(task.task_id)
    roots = sorted(task.task_id for task in benchmark.tasks if not task.dependencies)
    chains = []
    visited: set[str] = set()
    for root in roots:
        sequence = []
        current = root
        while True:
            if current in visited:
                raise ValueError(f"parallel-chain component merges at {current}")
            visited.add(current)
            sequence.append(tasks[current])
            next_items = children[current]
            if not next_items:
                break
            if len(next_items) != 1:
                raise ValueError(f"parallel-chain component forks at {current}")
            current = next_items[0]
        initial_delay = 0
        position = 0
        if sequence[0].kind == "compute":
            initial_delay = sequence[0].duration
            position = 1
        comm: list[int] = []
        compute: list[int] = []
        while position < len(sequence):
            if sequence[position].kind != "communication":
                raise ValueError(f"expected communication at {sequence[position].task_id}")
            comm.append(sequence[position].duration)
            position += 1
            if position >= len(sequence) or sequence[position].kind != "compute":
                raise ValueError("each parallel-chain communication must have a compute tail")
            compute.append(sequence[position].duration)
            position += 1
        if not comm:
            raise ValueError(f"parallel-chain component rooted at {root} has no communication")
        chains.append(ParallelChain(tuple(comm), tuple(compute), initial_delay))
    if visited != set(tasks):
        raise ValueError("parallel-chain graph contains a component without a root")
    return tuple(chains)


def to_multi_resource_instance(benchmark: Benchmark):
    from core.resource import MultiResourceInstance

    if benchmark.scenario != "muti_channel":
        raise ValueError(f"expected muti_channel, got {benchmark.scenario}")
    resources = {
        task.task_id: frozenset(task.resources)
        for task in benchmark.tasks
        if task.kind == "communication"
    }
    return MultiResourceInstance(to_internal_dag(benchmark), resources)
