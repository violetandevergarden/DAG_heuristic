"""Convert current research instances into the neutral benchmark model."""

from __future__ import annotations

import json
from typing import Hashable, Iterable

from benchmark import Benchmark, Resource, Task


def parallel_chains_to_benchmark(
    benchmark_id: str,
    category: str,
    chains: Iterable[object],
    *,
    metadata: dict | None = None,
) -> Benchmark:
    tasks: list[Task] = []
    for chain_index, chain in enumerate(chains):
        previous = f"chain{chain_index}_release"
        tasks.append(Task(previous, "compute", int(chain.initial_delay)))
        for operation, (comm, compute) in enumerate(zip(chain.comm, chain.compute, strict=True)):
            flow = f"chain{chain_index}_flow{operation}"
            tasks.append(Task(flow, "communication", int(comm), (previous,), ("channel:0",)))
            previous = f"chain{chain_index}_compute{operation}"
            tasks.append(Task(previous, "compute", int(compute), (flow,)))
    return Benchmark(
        benchmark_id=benchmark_id,
        scenario="single_channel",
        family="parallel_chain",
        category=_category(category),
        tasks=tuple(tasks),
        resources=(Resource("channel:0", "channel"),),
        metadata=metadata or {},
    )


def dag_to_benchmark(
    dag: object,
    category: str,
    *,
    metadata: dict | None = None,
) -> Benchmark:
    tasks = tuple(
        Task(
            task_id=task.task_id,
            kind="communication" if task.kind == "comm" else "compute",
            duration=int(task.duration),
            dependencies=tuple(task.deps),
            resources=("channel:0",) if task.kind == "comm" else (),
            metadata={key: value for key, value in {"role": task.label_map().get("task_role", ""), "cut": task.label_map().get("cut", "")}.items() if value},
        )
        for task in dag.tasks
    )
    combined_metadata = {
        "description": getattr(dag, "description", ""),
        "parameters": dict(getattr(dag, "parameters", ())),
        **(metadata or {}),
    }
    return Benchmark(
        benchmark_id=dag.name,
        scenario="single_channel",
        family="complex_chain",
        category=_category(category),
        tasks=tasks,
        resources=(Resource("channel:0", "channel"),),
        metadata=combined_metadata,
    )


def multi_resource_to_benchmark(
    dag: object,
    category: str,
    *,
    metadata: dict | None = None,
) -> Benchmark:
    resource_names = {
        value: _resource_id(value)
        for values in dag.resources.values()
        for value in values
    }
    resources = tuple(
        Resource(resource_id, _resource_kind(value), {"source_repr": repr(value)})
        for value, resource_id in sorted(resource_names.items(), key=lambda item: item[1])
    )
    tasks = tuple(
        Task(
            task_id=task.task_id,
            kind="communication" if task.kind == "comm" else "compute",
            duration=int(task.duration),
            dependencies=tuple(task.deps),
            resources=tuple(
                sorted(resource_names[value] for value in dag.resources.get(task.task_id, ()))
            ),
            metadata={key: value for key, value in {"role": task.label_map().get("task_role", ""), "cut": task.label_map().get("cut", "")}.items() if value},
        )
        for task in dag.tasks
    )
    return Benchmark(
        benchmark_id=dag.name,
        scenario="muti_channel",
        family="complex_chain",
        category=_category(category),
        tasks=tasks,
        resources=resources,
        metadata={
            "description": dag.context_map().get("description", ""),
            "parameters": dict(dag.parameters),
            **(metadata or {}),
        },
    )


def _category(value: str) -> str:
    if value in {"real", "real_derived", "real_export", "llm_motif"}:
        return "real"
    if value in {"random", "search"}:
        return "random"
    return "adversarial"


def _resource_id(value: Hashable) -> str:
    if isinstance(value, str):
        return f"resource:{value}"
    if isinstance(value, tuple) and len(value) == 2:
        left, right = value
        if left in {"nic_tx", "nic_rx"}:
            return f"{left}:{right}"
        if isinstance(left, int) and isinstance(right, int):
            return f"link:{left}->{right}"
    return "opaque:" + json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=repr)


def _resource_kind(value: Hashable) -> str:
    if isinstance(value, tuple) and len(value) == 2:
        if value[0] in {"nic_tx", "nic_rx"}:
            return str(value[0])
        if isinstance(value[0], int) and isinstance(value[1], int):
            return "directed_link"
    return "exclusive"
