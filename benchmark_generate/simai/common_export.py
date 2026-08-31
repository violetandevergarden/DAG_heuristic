"""Shared SimAI parsing and graph conversion, independent of scheduling semantics.

Semantic-specific modules provide an :class:`ExportContract` and expose the
public renderer/CLI.  Keeping that choice outside this module prevents a
conversion helper from silently selecting preemptive or non-preemptive rules.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

# The SimAI checkout exposes a package named ``src`` from its repository
# root.  Bootstrap must run before importing that package; importing it later
# lets this repository's own source directory win namespace resolution.
from benchmark_generate.simai.bootstrap import SIMAI_ROOT

from src.static_analysis.passes.pipeline_task_serializers import (
    BidirectionalPipelineSerializer,
    DualPipeSerializer,
    InterleavedOneFOneBSerializer,
    ZeroBubbleSerializer,
)
from src.static_analysis.passes.routing import BfsStrategy
from src.static_analysis.passes.task_serializer import ExecutionPlan, OneFOneBSerializer
from src.static_analysis.passes.topology_loader import TopologyLoader
from src.workload_format.schema import Job, P2PWorkload, ParallelismConfig
from src.workload_generator.aicb_parser import AicbHeader, AicbParser, AicbWorkItem
from src.workload_generator.builders.bidirectional_pipeline_builder import (
    BidirectionalPipelineWorkloadBuilder,
)
from src.workload_generator.builders.dualpipe_pipeline_builder import (
    DualPipePipelineWorkloadBuilder,
)
from src.workload_generator.builders.interleaved_pipeline_builder import (
    InterleavedPipelineWorkloadBuilder,
)
from src.workload_generator.builders.zero_bubble_pipeline_builder import (
    ZeroBubblePipelineWorkloadBuilder,
)
from src.workload_generator.rank_grouper import MegatronRankGrouper
from src.workload_generator.workload_builder import WorkloadBuilder

from benchmark import (
    Benchmark,
    Resource,
    SchedulingSemantics,
)
from benchmark import (
    Task as BenchmarkTask,
)
MODES = ("1f1b", "interleaved_1f1b", "zero_bubble", "bidirectional", "dualpipe")

PUBLIC_CATEGORIES = ("random", "adversarial", "real")

CONVERTER_VERSION = "1.2.0"


@dataclass(frozen=True)
class ExportContract:
    """Schema and scheduling semantics selected by a public renderer."""

    schema_version: str
    semantic_contract_version: str
    semantics: SchedulingSemantics
    converter_name: str
    converter_version: str


def content_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_commit(path: Path) -> str | None:
    """Return the current git commit of ``path`` when the checkout is cleanly available."""

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip() or None


def canonical_parameter_hash(parameters: dict) -> str:
    return hashlib.sha256(
        json.dumps(parameters, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class BuiltWorkload:
    mode: str
    workload: P2PWorkload
    plan: ExecutionPlan
    header: AicbHeader
    job: Job
    task_info: dict[int, object]


def make_job(header: AicbHeader) -> Job:
    dp = header.all_gpus // (header.tp * header.pp)
    return Job(
        job_id=0,
        name="benchmark-export",
        assigned_nodes=list(range(header.all_gpus)),
        parallelism=ParallelismConfig(tp=header.tp, dp=dp, pp=header.pp, ep=header.ep),
    )


def build_synthetic_input(
    *,
    pp: int = 2,
    tp: int = 1,
    dp: int = 1,
    ep: int = 1,
    ga: int = 4,
    layers: int = 2,
) -> tuple[AicbHeader, list[AicbWorkItem]]:
    """Create a small deterministic input for examples and integration tests."""
    header = AicbHeader(
        tp=tp,
        ep=ep,
        pp=pp,
        vpp=layers,
        ga=ga,
        all_gpus=pp * tp * dp,
        pp_comm_size=1_048_576,
    )

    def item(name: str, fwd: int, bwd: int, weight: int) -> AicbWorkItem:
        return AicbWorkItem(
            name=name,
            forward_compute_time=fwd,
            forward_comm="ALLREDUCE" if tp > 1 else "NONE",
            forward_comm_size=524_288 if tp > 1 else 0,
            backward_compute_time=bwd,
            backward_comm="ALLREDUCE" if tp > 1 else "NONE",
            backward_comm_size=524_288 if tp > 1 else 0,
            dp_compute_time=weight,
            dp_comm="NONE",
            dp_comm_size=0,
            process_time=100,
        )

    grad = item("grad_param_comm", 1_000, 1_000, 1_000)
    if dp > 1:
        grad.dp_comm = "ALLREDUCE"
        grad.dp_comm_size = 2_097_152
    items = [grad]
    for _microbatch in range(ga):
        for layer in range(layers):
            layer_item = item(
                f"layer{layer}",
                900_000 + layer * 100_000,
                1_500_000 + layer * 100_000,
                600_000 + layer * 50_000,
            )
            # Alternate TP and EP-bearing layers in the controlled mixed
            # probe.  AICB offers one collective field per phase, so this is
            # a structural interaction probe rather than a full MoE layer.
            if ep > 1 and layer % 2:
                layer_item.forward_comm = "ALLTOALL_EP"
                layer_item.forward_comm_size = 786_432
                layer_item.backward_comm = "ALLTOALL_EP"
                layer_item.backward_comm_size = 786_432
            items.append(layer_item)
    items.append(item("optimizer1", 0, 0, 0))
    return header, items


def _stage_map(job: Job) -> dict[int, int]:
    grouper = MegatronRankGrouper(job.assigned_nodes, job.parallelism)
    width = grouper.dp * grouper.tp
    return {
        node: stage
        for stage in range(grouper.pp)
        for node in grouper.nodes[stage * width:(stage + 1) * width]
    }


def build_workload(
    mode: str,
    header: AicbHeader,
    items: list[AicbWorkItem],
    *,
    vpp: int = 2,
    gradient_sync_bytes: int = 2_097_152,
    job: Job | None = None,
) -> BuiltWorkload:
    """Build the P2P workload and add serializer-owned compute resource order."""
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode}; choose one of {', '.join(MODES)}")
    job = make_job(header) if job is None else job
    sidecar: dict[int, object] = {}
    if mode == "1f1b":
        builder = WorkloadBuilder()
    elif mode == "interleaved_1f1b":
        builder = InterleavedPipelineWorkloadBuilder(vpp, sidecar)
    elif mode == "zero_bubble":
        builder = ZeroBubblePipelineWorkloadBuilder(sidecar)
    elif mode == "bidirectional":
        builder = BidirectionalPipelineWorkloadBuilder(
            sidecar, gradient_sync_bytes=gradient_sync_bytes,
        )
    else:
        builder = DualPipePipelineWorkloadBuilder(
            sidecar, gradient_sync_bytes=gradient_sync_bytes,
        )
    workload = builder.build_from_aicb(header, items, job, comm_algo="ring")
    errors = workload.validate()
    if errors:
        raise ValueError(f"invalid SimAI workload: {errors}")

    if mode == "1f1b":
        serializer = OneFOneBSerializer(pp=header.pp, node_to_stage=_stage_map(job))
    elif mode == "interleaved_1f1b":
        serializer = InterleavedOneFOneBSerializer(
            virtual_pipeline_size=vpp,
            expansion_task_info=sidecar,
        )
    elif mode == "zero_bubble":
        serializer = ZeroBubbleSerializer(expansion_task_info=sidecar)
    elif mode == "bidirectional":
        serializer = BidirectionalPipelineSerializer(expansion_task_info=sidecar)
    else:
        serializer = DualPipeSerializer(expansion_task_info=sidecar)
    plan = serializer.serialize(workload)
    validation = serializer.validate(workload, plan.compute_order)
    if validation:
        raise ValueError(f"invalid compute order: {validation}")
    return BuiltWorkload(mode, workload, plan, header, job, sidecar)


def _effective_dependencies(built: BuiltWorkload) -> dict[int, set[int]]:
    dependencies = {
        task.task_id: set(task.deps)
        for task in built.workload.tasks
    }
    for order in built.plan.compute_order.values():
        for source, target in pairwise(order):
            dependencies[target].add(source)
    return dependencies


def export_graph(
    built: BuiltWorkload,
    benchmark_id: str,
    *,
    bandwidth_gbps: float = 200.0,
    topology_path: Path | None = None,
    include_nic_resources: bool = True,
    category: str | None = None,
    projection_relation: str = "synthetic_motif",
    transform_log: tuple[str, ...] = (),
    provenance: dict | None = None,
    suite: str | None = None,
    workload_origin: str | None = None,
    topology_origin: str | None = None,
    source_world_size: int | None = None,
    source_dp: int | None = None,
    effective_world_size: int | None = None,
    dp_rewrite: bool = False,
    contract: ExportContract,
) -> Benchmark:
    """Project a built SimAI workload using an explicit semantic contract.

    ``category`` (one of :data:`PUBLIC_CATEGORIES`) is mandatory: the
    historical exporter silently produced non-preemptive ``category="real"``
    output, and that default must never decide semantics or data provenance
    again.  Synthetic bootstrap input must therefore never be labelled
    ``real``.
    """
    if bandwidth_gbps <= 0:
        raise ValueError("bandwidth_gbps must be positive")
    if category not in PUBLIC_CATEGORIES:
        raise ValueError(
            f"category must be one of {PUBLIC_CATEGORIES}; got {category!r}"
        )
    bytes_per_us = bandwidth_gbps * 125.0
    dependencies = _effective_dependencies(built)
    route_resources: dict[int, tuple[str, ...]] = {}
    resources: dict[str, Resource] = {}

    if topology_path is None:
        resources["channel:0"] = Resource("channel:0", "channel")
        for task in built.workload.tasks:
            if task.is_flow():
                route_resources[task.task_id] = ("channel:0",)
        scenario = "single_channel"
    else:
        topology = TopologyLoader().load(topology_path)
        routes = BfsStrategy().compute_routes(built.workload, topology)
        for task in built.workload.tasks:
            if not task.is_flow():
                continue
            path = routes.get_path(task)
            names = []
            for source, target in pairwise(path):
                name = f"link:{source}->{target}"
                names.append(name)
                resources[name] = Resource(name, "directed_link")
            if include_nic_resources:
                tx = f"nic_tx:{task.src}"
                rx = f"nic_rx:{task.dst}"
                names.extend((tx, rx))
                resources[tx] = Resource(tx, "nic_tx")
                resources[rx] = Resource(rx, "nic_rx")
            route_resources[task.task_id] = tuple(sorted(set(names)))
        scenario = "muti_channel"

    tasks = []
    parallelism = built.job.parallelism
    stage_width = parallelism.dp * parallelism.tp
    for task in built.workload.tasks:
        is_compute = task.is_compute()
        duration = int(task.duration_us or 0) if is_compute else max(
            1, math.ceil(int(task.size_bytes or 0) / bytes_per_us),
        )
        metadata = {
            "phase": task.phase.value,
            "iteration": task.iteration,
            "layer_id": task.layer_id,
            "item_id": task.item_id,
            # Preserve the native dependency layer separately from serializer
            # compute-order edges.  Multi-iteration expansion must identify
            # per-rank boundaries from SimAI's raw graph, exactly as SimAI's
            # own iteration utility does.
            "simai_raw_dependencies": [str(value) for value in sorted(task.deps)],
            "chunk_id": task.chunk_id,
            "num_chunks": task.num_chunks,
        }
        endpoint = task.node if is_compute else task.src
        if endpoint is not None:
            stage = endpoint // stage_width
            metadata["physical_stage_id"] = stage
            metadata["pipeline_stage"] = stage
        strategy_info = built.task_info.get(task.task_id)
        if strategy_info is not None:
            # Strategy-specific pipeline builders deliberately keep these
            # fields in a sidecar instead of changing SimAI's common Task IR.
            # Preserve primitive values so downstream, language-independent
            # repetition studies do not have to import SimAI.
            for name, value in vars(strategy_info).items():
                if name == "task_id" or value is None:
                    continue
                if isinstance(value, (str, int, float, bool)):
                    metadata[name] = value
        # Sidecars use the raw SimAI iteration field, where post/optimizer
        # items are encoded as ``ga``.  They are boundaries, not an extra
        # micro-batch, so normalize after merging sidecar values.
        metadata["microbatch_id"] = (
            task.iteration if 0 <= task.iteration < built.header.ga else -1
        )
        if is_compute:
            metadata["rank"] = task.node
            metadata["layer_or_block_id"] = task.layer_id
        else:
            metadata.update({
                "src": task.src,
                "dst": task.dst,
                "size_bytes": task.size_bytes,
                "comm_type": task.comm_type.value,
                "collective_type": task.comm_type.value,
                "parallelism_dimension": task.comm_type.value.split("_", 1)[0],
                "layer_or_block_id": task.layer_id,
            })
        if "task_role" not in metadata:
            if not is_compute:
                prefix = task.comm_type.value.split("_", 1)[0].upper()
                metadata["task_role"] = (
                    "PP_ACT"
                    if task.comm_type.value == "pp_send" and task.phase.value == "forward"
                    else "PP_GRAD" if task.comm_type.value == "pp_send"
                    else prefix
                )
            else:
                metadata["task_role"] = {
                    "forward": "F",
                    "backward_input": "B",
                    "backward_weight": "W",
                    "optimizer": "OPT",
                }.get(task.phase.value, "OTHER")
        metadata["task_role"] = {
            "compute_forward": "F",
            "compute_backward_input": "B",
            "compute_backward_weight": "W",
            "pp_activation": "PP_ACT",
            "pp_gradient": "PP_GRAD",
        }.get(str(metadata["task_role"]), str(metadata["task_role"]))
        tasks.append(BenchmarkTask(
            task_id=str(task.task_id),
            kind="compute" if is_compute else "communication",
            duration=duration,
            dependencies=tuple(str(value) for value in sorted(dependencies[task.task_id])),
            resources=() if is_compute else route_resources[task.task_id],
            metadata=metadata,
        ))
    provenance_record = dict(provenance or {})
    provenance_record.setdefault(
        "converter",
        {"name": contract.converter_name, "version": contract.converter_version},
    )
    provenance_record.setdefault(
        "parameters",
        {
            "bandwidth_gbps": bandwidth_gbps,
            "pipeline_mode": built.mode,
            "include_nic_resources": include_nic_resources,
        },
    )
    provenance_record["semantic_contract_version"] = contract.semantic_contract_version
    if suite is not None:
        provenance_record["suite"] = suite
    if workload_origin is not None:
        provenance_record["workload_origin"] = workload_origin
    if topology_origin is not None:
        provenance_record["topology_origin"] = topology_origin
    if source_world_size is not None:
        provenance_record["source_world_size"] = source_world_size
    if source_dp is not None:
        provenance_record["source_dp"] = source_dp
    if effective_world_size is not None:
        provenance_record["effective_world_size"] = effective_world_size
    provenance_record["dp_rewrite"] = bool(dp_rewrite)
    return Benchmark(
        benchmark_id=benchmark_id,
        scenario=scenario,
        family="complex_chain",
        category=category,
        tasks=tuple(tasks),
        resources=tuple(resources[name] for name in sorted(resources)),
        semantics=contract.semantics,
        schema_version=contract.schema_version,
        time_unit="us",
        metadata={
            "source": "simai-flow-scheduler",
            "pipeline_mode": built.mode,
            "bandwidth_gbps": bandwidth_gbps,
            "topology": topology_path.name if topology_path else None,
            "duration_model_version": "nominal_bandwidth_ceil_bytes_per_us-v1",
            "parallelism": {
                "tp": parallelism.tp,
                "dp": parallelism.dp,
                "pp": parallelism.pp,
                "ep": parallelism.ep,
            },
            "gradient_accumulation": built.header.ga,
            "semantic_contract_version": contract.semantic_contract_version,
            "projection_relation": projection_relation,
            "projection_relations": [projection_relation],
            "suite": suite,
            "workload_origin": workload_origin,
            "topology_origin": topology_origin,
            "source_world_size": source_world_size,
            "source_dp": source_dp,
            "effective_world_size": effective_world_size,
            "dp_rewrite": bool(dp_rewrite),
            "transform_log": list(transform_log),
            "provenance": provenance_record,
        },
    )


def _build_transform_log(
    built: BuiltWorkload,
    *,
    topology_path: Path | None,
    bandwidth_gbps: float,
    include_nic_resources: bool,
) -> tuple[str, ...]:
    log = [
        "workload compute/flow tasks mapped 1:1 to DAG compute/communication tasks",
        (
            f"communication duration = ceil(size_bytes / (bandwidth_gbps*125 us/byte)) "
            f"with bandwidth_gbps={bandwidth_gbps}"
        ),
        f"compute serializer order edges added by {type_name(built)}",
    ]
    if topology_path is not None:
        log.append(
            "routes frozen to directed link resources"
            + (" plus per-endpoint nic_tx/nic_rx" if include_nic_resources else "")
        )
    else:
        log.append("all communications share the unified bottleneck resource channel:0")
    return tuple(log)


def type_name(built: BuiltWorkload) -> str:
    return f"pipeline serializer ({built.mode})"


def raw_b_to_w_edges(built: BuiltWorkload) -> int:
    """Count data-DAG B -> W edges before compute-order serialization."""

    task_by_id = {task.task_id: task for task in built.workload.tasks}
    count = 0
    for task_id, info in built.task_info.items():
        if getattr(info, "task_role", None) != "W":
            continue
        task = task_by_id[task_id]
        if any(
            getattr(built.task_info.get(parent), "task_role", None) == "B"
            and getattr(built.task_info.get(parent), "b_task_id", None)
            == getattr(info, "b_task_id", None)
            for parent in task.deps
        ):
            count += 1
    return count


