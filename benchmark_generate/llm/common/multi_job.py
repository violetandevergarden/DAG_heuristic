"""Compose real AICB-derived benchmarks into a real multi-job benchmark.

Each job keeps its own namespace (``{job_id}::`` prefix), its own DAG edges and
its source provenance.  Jobs never gain cross-job precedence edges; they
interact only through the shared fixed resource universe.  Arrival is encoded
as a release compute node exactly like ``llm_structured.preemptive.multi_job.compose_jobs``.
"""

from __future__ import annotations

from pathlib import Path

from benchmark import Benchmark, Resource, Task, validate_benchmark
from benchmark_generate.io import FileHashCache


def compose_real_jobs(
    jobs: list[tuple[str, Benchmark, int]],
    *,
    benchmark_id: str,
    source_paths: list[Path],
    source_hashes: list[str | None] | None = None,
) -> Benchmark:
    """Merge ``(job_id, benchmark, arrival)`` entries into one multi-job DAG."""
    if not jobs:
        raise ValueError("at least one job is required")
    if len(source_paths) not in {0, len(jobs)}:
        raise ValueError("source_paths must be empty or contain one path per job")
    if source_hashes is not None and len(source_hashes) != len(jobs):
        raise ValueError("source_hashes must contain one entry per job")
    hash_cache = FileHashCache()

    def source_hash(index: int) -> str | None:
        if source_hashes is not None:
            return source_hashes[index]
        return hash_cache.get(source_paths[index]) if index < len(source_paths) else None
    scenario = jobs[0][1].scenario
    semantics = jobs[0][1].semantics
    categories = {job.scenario for _job_id, job, _arrival in jobs}
    if len(categories) != 1:
        raise ValueError("all jobs must share the same scenario")
    if scenario not in {"single_channel", "muti_channel"}:
        raise ValueError(f"unsupported scenario: {scenario}")
    if any(job.semantics != semantics for _job_id, job, _arrival in jobs):
        raise ValueError("all jobs must share identical scheduling semantics")
    time_unit = jobs[0][1].time_unit
    if any(job.time_unit != time_unit for _job_id, job, _arrival in jobs):
        raise ValueError("all jobs must share the same time unit")
    schema_version = jobs[0][1].schema_version
    if any(job.schema_version != schema_version for _job_id, job, _arrival in jobs):
        raise ValueError("all jobs must share the same schema version")
    if any(arrival < 0 for _job_id, _job, arrival in jobs):
        raise ValueError("job arrivals must be non-negative")

    tasks: list[Task] = []
    resources: dict[str, Resource] = {}
    job_records: list[dict] = []
    job_ids = {job_id for job_id, _benchmark, _arrival in jobs}
    if len(job_ids) != len(jobs):
        raise ValueError("job ids must be unique")
    for index, (job_id, benchmark, arrival) in enumerate(jobs):
        validate_benchmark(benchmark)
        release = f"{job_id}::__arrival__"
        tasks.append(Task(
            task_id=release,
            kind="compute",
            duration=max(0, int(arrival)),
            dependencies=(),
            resources=(),
            metadata={"job_id": job_id, "task_role": "JOB_ARRIVAL", "multi_job_index": index},
        ))
        id_map = {task.task_id: f"{job_id}::{task.task_id}" for task in benchmark.tasks}
        for task in benchmark.tasks:
            dependencies = tuple(id_map[parent] for parent in task.dependencies)
            if not dependencies:
                dependencies = (release,)
            metadata = dict(task.metadata)
            metadata["job_id"] = job_id
            metadata["multi_job_index"] = index
            tasks.append(Task(
                task_id=id_map[task.task_id],
                kind=task.kind,
                duration=task.duration,
                dependencies=dependencies,
                resources=task.resources,
                metadata=metadata,
            ))
        for resource in benchmark.resources:
            resources.setdefault(resource.resource_id, resource)
        job_records.append({
            "job_id": job_id,
            "arrival": int(arrival),
            "source_benchmark_id": benchmark.benchmark_id,
            "source_content_hash": (
                source_hash(index)
            ),
        })

    metadata = {
        "source": "real AICB multi-job composition",
        "semantic_contract_version": jobs[0][1].metadata.get("semantic_contract_version"),
        "projection_relation": "real_multi_job_composition",
        "multi_job": job_records,
        "transform_log": [
            "jobs merged into one DAG with {job_id}:: prefixed task ids and per-task job_id labels",
            "no cross-job precedence edges; jobs share only the fixed resource universe",
            "arrival encoded as a release compute node per job",
        ],
        "provenance": {
            "converter": {"name": "benchmark_generate.llm.common.multi_job", "version": "1.0.0"},
            "jobs": [
                {
                    "job_id": job_id,
                    "arrival": int(arrival),
                    "source_benchmark_id": benchmark.benchmark_id,
                    "source_content_hash": (
                        source_hash(index)
                    ),
                    "source": benchmark.metadata.get("provenance", {}).get("source"),
                }
                for index, (job_id, benchmark, arrival) in enumerate(jobs)
            ],
        },
    }
    composed = Benchmark(
        benchmark_id=benchmark_id,
        scenario=scenario,
        family="complex_chain",
        category="real",
        tasks=tuple(tasks),
        resources=tuple(sorted(resources.values(), key=lambda item: item.resource_id)),
        semantics=semantics,
        schema_version=schema_version,
        time_unit=time_unit,
        metadata=metadata,
    )
    validate_benchmark(composed)
    return composed
