"""Deterministic Stage 4f case specifications and staging reconstruction."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from benchmark import Benchmark, load_benchmark, write_benchmark
from benchmark_generate.io import sha256_file, write_jsonl_atomic

from benchmark_generate.llm.common.multi_job import compose_real_jobs

WORKFLOW_VERSION = "nonpreemptive-stage4f-multi-job-v1"


def sha256(path: Path) -> str:
    return sha256_file(path)


def read_specs(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _task_shape(task) -> tuple:
    return task.task_id, task.kind, task.dependencies


def assert_topology_pair(cassini: Benchmark, control: Benchmark) -> None:
    """Check that a topology pair differs only in route/resource/duration data."""
    if len(cassini.tasks) != len(control.tasks):
        raise ValueError("paired topologies have different task counts")
    for left, right in zip(cassini.tasks, control.tasks, strict=True):
        if _task_shape(left) != _task_shape(right):
            raise ValueError(f"paired topology DAG mismatch at {left.task_id}")
        if left.kind == "compute" and left.duration != right.duration:
            raise ValueError(f"paired topology compute duration mismatch at {left.task_id}")
    left_source = cassini.metadata.get("source_workload_hashes") or [
        cassini.metadata.get("provenance", {}).get("source", {}).get("content_hash")
    ]
    right_source = control.metadata.get("source_workload_hashes") or [
        control.metadata.get("provenance", {}).get("source", {}).get("content_hash")
    ]
    if not all(left_source) or left_source != right_source:
        raise ValueError("paired topologies do not share one source workload hash")


def static_cross_job_overlap(benchmark: Benchmark) -> dict:
    resource_jobs: dict[str, set[str]] = {}
    resource_tasks: dict[str, int] = {}
    communication_count = 0
    shared_communications = 0
    for task in benchmark.tasks:
        if task.kind != "communication":
            continue
        communication_count += 1
        job = str(task.metadata.get("job_id", "unknown"))
        task_resources = task.resources or (("channel:0",) if benchmark.scenario == "single_channel" else ())
        for resource in task_resources:
            resource_jobs.setdefault(resource, set()).add(job)
            resource_tasks[resource] = resource_tasks.get(resource, 0) + 1
    shared = {resource for resource, jobs in resource_jobs.items() if len(jobs) >= 2}
    for task in benchmark.tasks:
        task_resources = task.resources or (("channel:0",) if benchmark.scenario == "single_channel" else ())
        if task.kind == "communication" and shared.intersection(task_resources):
            shared_communications += 1
    return {
        "communication_count": communication_count,
        "shared_resource_count": len(shared),
        "shared_communication_count": shared_communications,
        "shared_communication_ratio": (
            shared_communications / communication_count if communication_count else 0.0
        ),
        "resource_job_counts": {
            resource: len(resource_jobs[resource]) for resource in sorted(resource_jobs)
        },
        "hot_resources": [
            {"resource": resource, "task_count": count, "job_count": len(resource_jobs[resource])}
            for resource, count in sorted(
                resource_tasks.items(), key=lambda item: (-item[1], item[0])
            )[:10]
        ],
        "cross_job_overlap": bool(shared),
    }


def build_case(root: Path, spec: dict) -> tuple[Benchmark, list[Path]]:
    source_paths = [root / source["path"] for source in spec["sources"]]
    sources = [load_benchmark(path) for path in source_paths]
    jobs = [
        (f"job{index}", source, int(source_spec["arrival"]))
        for index, (source, source_spec) in enumerate(zip(sources, spec["sources"], strict=True))
    ]
    benchmark = compose_real_jobs(
        jobs,
        benchmark_id=spec["benchmark_id"],
        source_paths=source_paths,
    )
    records = []
    for record, source_spec in zip(
        benchmark.metadata["multi_job"], spec["sources"], strict=True
    ):
        records.append(
            {
                **record,
                "source_path": source_spec["path"],
                "isolated_makespan": int(source_spec["isolated_makespan"]),
                "arrival_ratio": float(source_spec["arrival_ratio"]),
                "weight": float(source_spec.get("weight", 1.0)),
            }
        )
    metadata = {
        **benchmark.metadata,
        "multi_job": records,
        "workflow_version": WORKFLOW_VERSION,
        "case_class": spec["case_class"],
        "source_group": spec["source_group"],
        "split": spec["split"],
        "topology_role": spec.get("topology_role", "single_channel"),
        "paired_case_id": spec.get("paired_case_id"),
        "source_workload_hashes": [
            source.metadata.get("provenance", {}).get("source", {}).get("content_hash")
            for source in sources
        ],
    }
    return replace(benchmark, metadata=metadata), source_paths


def rebuild_manifest(root: Path, specs_path: Path, staging: Path) -> list[dict]:
    """Rebuild every frozen spec without touching the public benchmark index."""
    rows = []
    for spec in read_specs(specs_path):
        benchmark, source_paths = build_case(root, spec)
        source_benchmarks = [load_benchmark(path) for path in source_paths]
        relative = Path("nonpreemptive") / spec["relative_path"]
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        write_benchmark(benchmark, target)
        rows.append(
            {
                **spec,
                "path": relative.as_posix(),
                "content_hash": sha256(target),
                "parent_content_hashes": [sha256(path) for path in source_paths],
                "source_workload_hashes": [
                    source.metadata.get("provenance", {}).get("source", {}).get("content_hash")
                    for source in source_benchmarks
                ],
                "topology_names": [
                    source.metadata.get("provenance", {}).get("topology", {}).get("name")
                    for source in source_benchmarks
                ],
                "topology_hashes": [
                    source.metadata.get("provenance", {}).get("topology", {}).get("content_hash")
                    for source in source_benchmarks
                ],
                "duration_model_versions": [
                    source.metadata.get("duration_model_version")
                    for source in source_benchmarks
                ],
                "task_count": len(benchmark.tasks),
                "communication_count": sum(
                    task.kind == "communication" for task in benchmark.tasks
                ),
                "resource_count": len(benchmark.resources),
                "scenario": benchmark.scenario,
                "static_overlap": static_cross_job_overlap(benchmark),
                "workflow_version": WORKFLOW_VERSION,
                "publication_status": "staged",
            }
        )
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl_atomic(path, rows)
