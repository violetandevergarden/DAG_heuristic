from __future__ import annotations

from pathlib import Path

from benchmark import validate_benchmark
from benchmark_generate.simai.preemptive_export import (
    MODES,
    build_synthetic_input,
    build_workload,
    to_preemptive_benchmark,
)
from benchmark_generate.simai.nonpreemptive_export import to_nonpreemptive_benchmark


def _assert_preemptive_contract(case) -> None:
    """The exported file must carry the explicit preemptive semantics, not defaults."""

    assert case.schema_version == "2.0"
    semantics = case.semantics
    assert semantics.preemption == "communication_resume"
    assert semantics.decision_epoch == "task_event"
    assert not semantics.optional_idle
    assert semantics.resource_model == "exclusive_fixed_set"
    assert case.metadata["semantic_contract_version"] == "llm-v1"


def test_all_pipeline_modes_export_valid_single_channel_benchmarks() -> None:
    header, items = build_synthetic_input()
    for mode in MODES:
        built = build_workload(mode, header, items)
        case = to_preemptive_benchmark(built, f"synthetic_{mode}", category="random")

        validate_benchmark(case)
        _assert_preemptive_contract(case)
        assert case.scenario == "single_channel"
        assert len(case.tasks) == len(built.workload.tasks)
        assert all(
            task.resources == ("channel:0",) for task in case.tasks if task.kind == "communication"
        )


def test_topology_export_records_fixed_route_resources() -> None:
    header, items = build_synthetic_input()
    built = build_workload("1f1b", header, items)
    topology = Path(__file__).parent / "fixtures/two_gpu_topology.txt"
    case = to_preemptive_benchmark(
        built,
        "synthetic_routes",
        topology_path=topology,
        category="random",
        projection_relation="route_frozen_projection",
    )

    validate_benchmark(case)
    _assert_preemptive_contract(case)
    assert case.scenario == "muti_channel"
    assert any(resource.kind == "directed_link" for resource in case.resources)
    assert all(task.resources for task in case.tasks if task.kind == "communication")


def test_paired_semantic_exports_share_the_same_graph() -> None:
    header, items = build_synthetic_input()
    built = build_workload("1f1b", header, items)
    topology = Path(__file__).parent / "fixtures/two_gpu_topology.txt"
    preemptive = to_preemptive_benchmark(
        built,
        "paired_preemptive",
        topology_path=topology,
        category="random",
        projection_relation="route_frozen_projection",
    )
    nonpreemptive = to_nonpreemptive_benchmark(
        built,
        "paired_nonpreemptive",
        topology_path=topology,
        category="random",
        projection_relation="route_frozen_projection",
    )

    validate_benchmark(nonpreemptive)
    assert nonpreemptive.schema_version == "3.0"
    assert nonpreemptive.semantics.preemption == "none"
    assert nonpreemptive.semantics.optional_idle
    assert nonpreemptive.tasks == preemptive.tasks
    assert nonpreemptive.resources == preemptive.resources
    assert nonpreemptive.scenario == preemptive.scenario
