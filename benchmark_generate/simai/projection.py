"""Post-export projections of SimAI-derived benchmarks.

Projections rewrite resource sets or re-label a parsed workload into the
neutral benchmark model without changing scheduling semantics.  SimAI-dependent,
hence inside ``benchmark_generate/simai/``.
"""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

from benchmark import Benchmark, Resource, Task
from benchmark_generate.simai.bootstrap import SIMAI_ROOT
from benchmark_generate.simai.common_export import (
    content_sha256,
    git_commit,
)
from benchmark_generate.simai.preemptive_export import (
    SEMANTIC_CONTRACT_VERSION,
    preemptive_semantics,
)


def project_resources(benchmark: Benchmark, placement: str) -> Benchmark:
    """Relabel communication resource sets for a placement probe.

    ``placement`` is one of ``global_channel`` (all communications share one
    bottleneck), ``isolated_dimensions`` (one fabric per parallelism
    dimension) or ``pp_dp_shared_uplink`` (PP and DP share an uplink plus
    their own fabric).  The projected benchmark keeps the original tasks and
    dependencies and only rewrites resource sets and the resource declaration
    list, so it remains validator-clean.
    """

    def resource_for(task: Task) -> tuple[str, ...]:
        if task.kind != "communication":
            return ()
        comm_type = str(task.metadata.get("comm_type", "unknown"))
        dimension = comm_type.split("_", 1)[0]
        if placement == "isolated_dimensions":
            return (f"fabric:{dimension}",)
        if placement == "pp_dp_shared_uplink":
            if dimension in {"pp", "dp"}:
                return ("uplink:shared", f"fabric:{dimension}")
            return (f"fabric:{dimension}",)
        return ("channel:global",)

    tasks = tuple(replace(task, resources=resource_for(task)) for task in benchmark.tasks)
    used = sorted(
        {
            resource_id
            for task in tasks
            for resource_id in task.resources
        }
    )
    declared = tuple(
        Resource(resource_id, "fabric" if resource_id.startswith("fabric:") else "uplink")
        for resource_id in used
    )
    return replace(
        benchmark,
        benchmark_id=f"{benchmark.benchmark_id}_{placement}",
        scenario="muti_channel",
        tasks=tasks,
        resources=declared,
        metadata={**benchmark.metadata, "placement_probe": placement},
    )


def workload_to_preemptive_benchmark(
    workload,
    *,
    benchmark_id: str,
    scenario: str,
    bandwidth_gbps: float,
    source_name: str,
    source_hash: str,
    projection_relation: str,
    transform_log: tuple[str, ...],
) -> Benchmark:
    """Project a parsed SimAI P2P workload 1:1 into a preemptive benchmark.

    Used for the frozen SimAI example workloads (single_job / multi_job
    sample files shipped with the checkout).  Jobs are merged into one DAG
    with prefixed task ids and per-task job labels; the projection relation
    documents the resource relaxation.
    """

    if scenario not in {"single_channel", "muti_channel"}:
        raise ValueError(f"unsupported scenario {scenario}")
    bytes_per_us = bandwidth_gbps * 125.0
    jobs = {job.job_id: job for job in workload.jobs}
    stage_width = {
        job_id: job.parallelism.dp * job.parallelism.tp
        for job_id, job in jobs.items()
    }
    multi_job = len(jobs) > 1

    def project_id(task) -> str:
        raw = str(task.task_id)
        return f"j{task.job_id}:{raw}" if multi_job else raw

    id_map = {task.task_id: project_id(task) for task in workload.tasks}
    tasks = []
    for task in workload.tasks:
        is_flow = task.type.value == "flow"
        duration = (
            max(1, math.ceil(int(task.size_bytes or 0) / bytes_per_us))
            if is_flow
            else int(task.duration_us or 0)
        )
        metadata = {
            "phase": str(task.phase.value),
            "iteration": int(task.iteration),
            "microbatch_id": int(task.iteration),
            "layer_id": int(task.layer_id or -1),
            "item_id": int(task.item_id or -1),
        }
        if is_flow:
            dimension = str(task.comm_type.value).split("_", 1)[0]
            flow_resources = (
                ("channel:0",)
                if scenario == "single_channel"
                else (f"fabric:{dimension}",)
            )
            metadata.update({
                "comm_type": str(task.comm_type.value),
                "collective_type": str(task.comm_type.value),
                "parallelism_dimension": dimension,
                "task_role": dimension.upper() if dimension else "COMM",
            })
        else:
            metadata.update({
                "rank": int(task.node or 0),
                "task_role": {
                    "forward": "F",
                    "backward_input": "B",
                    "backward_weight": "W",
                    "optimizer": "OPT",
                }.get(str(task.phase.value), "OTHER"),
            })
        width = stage_width.get(task.job_id)
        if width and task.node is not None:
            metadata["physical_stage_id"] = int(task.node) // width
            metadata["pipeline_stage"] = int(task.node) // width
        metadata["job_id"] = int(task.job_id)
        tasks.append(Task(
            task_id=project_id(task),
            kind="communication" if is_flow else "compute",
            duration=duration,
            dependencies=tuple(id_map[parent] for parent in (task.deps or ())),
            resources=flow_resources if is_flow else (),
            metadata=metadata,
        ))
    if scenario == "single_channel":
        resources = (Resource("channel:0", "channel"),)
    else:
        used = sorted(
            {
                resource_id
                for task in tasks
                for resource_id in task.resources
            }
        )
        resources = tuple(Resource(resource_id, "fabric") for resource_id in used)
    return Benchmark(
        benchmark_id=benchmark_id,
        scenario=scenario,
        family="complex_chain",
        category="real",
        tasks=tuple(tasks),
        resources=resources,
        semantics=preemptive_semantics(),
        schema_version="2.0",
        time_unit="us",
        metadata={
            "source": "simai-flow-scheduler example workload",
            "semantic_contract_version": SEMANTIC_CONTRACT_VERSION,
            "projection_relation": projection_relation,
            "transform_log": list(transform_log),
            "provenance": {
                "source": {
                    "kind": "simai_example_workload",
                    "name": source_name,
                    "content_hash": source_hash,
                },
                "tool_version_or_commit": git_commit(SIMAI_ROOT),
                "converter": {
                    "name": "benchmark_generate.simai.projection",
                    "version": "1.0.0",
                },
                "semantic_contract_version": SEMANTIC_CONTRACT_VERSION,
            },
        },
    )


def example_cases() -> dict[str, Benchmark]:
    """Frozen 1:1 projections of the SimAI example workload files."""

    from src.workload_format.writer import WorkloadReader

    reader = WorkloadReader()
    single_path = SIMAI_ROOT / "examples/single_job/single_job_workload.json"
    multi_path = SIMAI_ROOT / "examples/multi_job/multi_job_workload.json"
    single = workload_to_preemptive_benchmark(
        reader.read(single_path),
        benchmark_id="simai_example_single_job_1to1",
        scenario="single_channel",
        bandwidth_gbps=200.0,
        source_name=single_path.name,
        source_hash=content_sha256(single_path),
        projection_relation="relaxation_unified_channel",
        transform_log=(
            "1:1 workload projection; no compute serializer edges added",
            "flows converted to communication with duration = "
            "ceil(size_bytes / (bandwidth_gbps * 125)) us",
            "all flows share the unified bottleneck resource channel:0",
        ),
    )
    multi = workload_to_preemptive_benchmark(
        reader.read(multi_path),
        benchmark_id="simai_example_multi_job_1to1",
        scenario="muti_channel",
        bandwidth_gbps=200.0,
        source_name=multi_path.name,
        source_hash=content_sha256(multi_path),
        projection_relation="relaxation_isolated_dimensions",
        transform_log=(
            "1:1 workload projection; jobs merged into one DAG with prefixed "
            "task ids and per-task job_id labels",
            "each communication assigned one fabric per parallelism dimension",
        ),
    )
    return {"single_job_1to1": single, "multi_job_1to1": multi}


__all__ = ["example_cases", "project_resources", "workload_to_preemptive_benchmark"]


