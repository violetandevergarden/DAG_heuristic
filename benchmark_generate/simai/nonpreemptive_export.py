"""Render SimAI-derived DAGs under the non-preemptive Stage 4 contract."""

from __future__ import annotations

from pathlib import Path

from benchmark import Benchmark, SchedulingSemantics
from benchmark_generate.simai.common_export import BuiltWorkload, ExportContract, export_graph

SEMANTIC_CONTRACT_VERSION = "llm-nonpreemptive-v1"
NONPREEMPTIVE_CONTRACT = ExportContract(
    schema_version="3.0",
    semantic_contract_version=SEMANTIC_CONTRACT_VERSION,
    semantics=SchedulingSemantics(
        preemption="none",
        decision_epoch="task_completion",
        optional_idle=True,
        compute_model="unbounded_parallel",
        resource_model="exclusive_fixed_set",
        preemption_cost=0,
        minimum_quantum=0,
    ),
    converter_name="benchmark_generate.simai.nonpreemptive_export",
    converter_version="1.0.0",
)


def to_nonpreemptive_benchmark(
    built: BuiltWorkload,
    benchmark_id: str,
    *,
    bandwidth_gbps: float = 200.0,
    topology_path: Path | None = None,
    include_nic_resources: bool = True,
    category: str,
    projection_relation: str,
    transform_log: tuple[str, ...] = (),
    provenance: dict | None = None,
    suite: str | None = None,
    workload_origin: str | None = None,
    topology_origin: str | None = None,
    source_world_size: int | None = None,
    source_dp: int | None = None,
    effective_world_size: int | None = None,
    dp_rewrite: bool = False,
) -> Benchmark:
    contract = NONPREEMPTIVE_CONTRACT
    if topology_path is None:
        contract = ExportContract(
            contract.schema_version,
            contract.semantic_contract_version,
            SchedulingSemantics(
                preemption="none",
                decision_epoch="task_completion",
                optional_idle=True,
                compute_model="unbounded_parallel",
                resource_model="exclusive",
                preemption_cost=0,
                minimum_quantum=0,
            ),
            contract.converter_name,
            contract.converter_version,
        )
    provenance_record = dict(provenance or {})
    provenance_record.setdefault(
        "converter",
        {"name": "benchmark_generate.simai.nonpreemptive_export", "version": "1.0.0"},
    )
    return export_graph(
        built,
        benchmark_id,
        contract=contract,
        bandwidth_gbps=bandwidth_gbps,
        topology_path=topology_path,
        include_nic_resources=include_nic_resources,
        category=category,
        projection_relation=projection_relation,
        transform_log=transform_log,
        provenance=provenance_record,
        suite=suite,
        workload_origin=workload_origin,
        topology_origin=topology_origin,
        source_world_size=source_world_size,
        source_dp=source_dp,
        effective_world_size=effective_world_size,
        dp_rewrite=dp_rewrite,
    )
