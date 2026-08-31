"""Render SimAI-derived DAGs under the preemptive Stage 4 contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark import Benchmark, SchedulingSemantics, write_benchmark
from benchmark_generate.simai.common_export import (
    MODES,
    PUBLIC_CATEGORIES,
    AicbParser,
    BuiltWorkload,
    ExportContract,
    _build_transform_log,
    _effective_dependencies,
    build_synthetic_input,
    build_workload,
    content_sha256,
    export_graph,
    git_commit,
    raw_b_to_w_edges,
)

SEMANTIC_CONTRACT_VERSION = "llm-v1"
PREEMPTIVE_CONTRACT = ExportContract(
    schema_version="2.0",
    semantic_contract_version=SEMANTIC_CONTRACT_VERSION,
    semantics=SchedulingSemantics(
        preemption="communication_resume",
        decision_epoch="task_event",
        optional_idle=False,
        compute_model="unbounded_parallel",
        resource_model="exclusive_fixed_set",
        preemption_cost=0,
        minimum_quantum=0,
    ),
    converter_name="benchmark_generate.simai.preemptive_export",
    converter_version="1.0.0",
)


def preemptive_semantics() -> SchedulingSemantics:
    return PREEMPTIVE_CONTRACT.semantics


def to_preemptive_benchmark(
    built: BuiltWorkload,
    benchmark_id: str,
    *,
    bandwidth_gbps: float = 200.0,
    topology_path: Path | None = None,
    include_nic_resources: bool = True,
    category: str,
    projection_relation: str = "synthetic_motif",
    transform_log: tuple[str, ...] = (),
    provenance: dict | None = None,
    **metadata: object,
) -> Benchmark:
    return export_graph(
        built,
        benchmark_id,
        contract=PREEMPTIVE_CONTRACT,
        bandwidth_gbps=bandwidth_gbps,
        topology_path=topology_path,
        include_nic_resources=include_nic_resources,
        category=category,
        projection_relation=projection_relation,
        transform_log=transform_log,
        provenance=provenance,
        **metadata,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aicb", type=Path)
    parser.add_argument("--mode", choices=MODES, default="1f1b")
    parser.add_argument("--id", dest="benchmark_id", default="simai_pipeline")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--topology", type=Path)
    parser.add_argument("--bandwidth-gbps", type=float, default=200.0)
    parser.add_argument("--vpp", type=int, default=2)
    parser.add_argument("--category", choices=PUBLIC_CATEGORIES)
    parser.add_argument("--projection-relation")
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()

    category = args.category or ("real" if args.aicb else "random")
    relation = args.projection_relation or (
        "synthetic_motif"
        if not args.aicb
        else ("route_frozen_projection" if args.topology else "relaxation_unified_channel")
    )
    source = {"kind": "aicb" if args.aicb else "synthetic_bootstrap"}
    if args.aicb:
        source.update(name=args.aicb.name, content_hash=content_sha256(args.aicb))
        header, items = AicbParser().parse(args.aicb)
    else:
        source["name"] = "synthetic_bootstrap"
        header, items = build_synthetic_input()
    built = build_workload(args.mode, header, items, vpp=args.vpp)
    topology = None
    if args.topology:
        topology = {"name": args.topology.name, "content_hash": content_sha256(args.topology)}
    provenance = {
        "source": source,
        "tool_version_or_commit": git_commit(Path(__file__).resolve().parents[2]),
        "parameters": {"mode": args.mode, "vpp": args.vpp, "bandwidth_gbps": args.bandwidth_gbps},
    }
    if topology:
        provenance["topology"] = topology
    benchmark = to_preemptive_benchmark(
        built,
        args.benchmark_id,
        bandwidth_gbps=args.bandwidth_gbps,
        topology_path=args.topology,
        category=category,
        projection_relation=relation,
        transform_log=_build_transform_log(
            built,
            topology_path=args.topology,
            bandwidth_gbps=args.bandwidth_gbps,
            include_nic_resources=True,
        ),
        provenance=provenance,
    )
    write_benchmark(benchmark, args.output)
    print(f"wrote {benchmark.benchmark_id} with {len(benchmark.tasks)} tasks to {args.output}")
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "path": str(args.output.resolve()),
            "benchmark_id": benchmark.benchmark_id,
            "category": category,
            "scenario": benchmark.scenario,
            "semantic_contract_version": SEMANTIC_CONTRACT_VERSION,
            "projection_relation": relation,
            "benchmark_content_hash": content_sha256(args.output),
            "source": source,
            "topology": topology,
        }
        with args.manifest.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
