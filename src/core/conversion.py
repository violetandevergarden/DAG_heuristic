"""Adapters from the public file model to internal scheduling structures."""

from __future__ import annotations

from benchmark import Benchmark
from core.dag import DAG, Task


def to_dag(benchmark: Benchmark) -> DAG:
    """Convert a neutral benchmark without changing its scheduling semantics.

    Stage 4 structural labels (phase, micro-batch, pipeline stage,
    parallelism dimension, collective type, layer/block and repetition group)
    are carried into the read-only ``Task.labels`` field of the formal
    algorithm input.  Algorithms must read these labels from the formal input;
    they may not read answer-hinting ``metadata``.
    """

    def extract_labels(metadata: dict) -> tuple[tuple[str, str], ...]:
        return tuple(
            sorted(
                (str(key), str(value))
                for key, value in metadata.items()
                if value is not None
            )
        )

    return DAG(
        name=benchmark.benchmark_id,
        tasks=tuple(
            Task(
                task_id=task.task_id,
                kind="comm" if task.kind == "communication" else "compute",
                duration=task.duration,
                deps=task.dependencies,
                labels=extract_labels(task.metadata),
                resources=frozenset(task.resources),
            )
            for task in benchmark.tasks
        ),
        context=tuple(
            (key, value)
            for key, value in (
                ("category", benchmark.category),
                ("description", str(benchmark.metadata.get("description", ""))),
            )
            if value
        ),
        parameters=tuple(
            sorted(
                (str(key), str(value))
                for key, value in benchmark.metadata.get("parameters", {}).items()
            )
        ),
    )


def to_muti_resourse(benchmark: Benchmark):
    if benchmark.scenario != "muti_channel":
        raise ValueError(f"expected muti_channel, got {benchmark.scenario}")
    resources = {
        task.task_id: frozenset(task.resources)
        for task in benchmark.tasks
        if task.kind == "communication"
    }
    return to_dag(benchmark).with_resources(resources)
