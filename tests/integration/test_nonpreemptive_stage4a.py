from __future__ import annotations

import time
from pathlib import Path

import pytest

from benchmark import Benchmark, Resource, SchedulingSemantics, Task, validate_benchmark
from benchmark_generate.llm.nonpreemptive.contention_audit import (
    bounded_choice_search,
    contention_audit,
)
from benchmark_generate.llm.common.multi_job import compose_real_jobs
from benchmark_generate.llm.nonpreemptive.corpus_selection import selected_specs
from benchmark_generate.llm.nonpreemptive.slice import causal_closure_slice
from benchmark_generate.simai.common_export import build_synthetic_input, build_workload
from benchmark_generate.simai.nonpreemptive_export import to_nonpreemptive_benchmark

pytestmark = [pytest.mark.integration, pytest.mark.simai]
from experiments.llm_structure.nonpreemptive.foundation.process_budget import run_with_budget
from llm_structured.nonpreemptive.baseline import replay


def _case(*, routed: bool = False):
    header, items = build_synthetic_input(pp=2, tp=1, dp=1, ga=2, layers=1)
    built = build_workload("1f1b", header, items)
    topology = Path(__file__).parent / "fixtures/two_gpu_topology.txt" if routed else None
    return to_nonpreemptive_benchmark(
        built,
        f"np_stage4a_{'routed' if routed else 'single'}",
        topology_path=topology,
        category="random",
        projection_relation="route_frozen_projection" if routed else "controlled_projection",
    )


def _blocking_worker(seconds: float, output) -> None:
    time.sleep(seconds)
    output.put({"status": "completed"})


def test_single_channel_audit_replay_and_causal_slice() -> None:
    benchmark = _case()
    report = contention_audit(benchmark, max_decisions=8)
    assert report["evidence_level"] in {"sampled_prefix", "completed_replay"}
    assert report["decisions"]
    assert set(report["conflict_counts"]) == {"action", "policy", "state", "quality"}
    assert {"spt", "lpt", "random_seed_0"} <= set(report["decisions"][0]["policy_actions"])

    for mode in ("optional_idle", "work_conserving"):
        result = replay(benchmark, "longest_tail", mode)
        assert result["status"] == "completed"
        assert result["trace_valid"]

    anchors = next(
        tuple(item["ready_communications"][:1])
        for item in report["decisions"]
        if item["ready_communications"]
    )
    sliced = causal_closure_slice(
        benchmark,
        anchors=anchors,
        max_tasks=len(benchmark.tasks),
        successor_depth=1,
    )
    validate_benchmark(sliced)
    kept = {task.task_id for task in sliced.tasks}
    assert all(set(task.dependencies) <= kept for task in sliced.tasks)
    assert sliced.metadata["slice_relation"]["dependencies_cut"] == 0


def test_multi_resource_audit_preserves_nonpreemptive_reservations() -> None:
    benchmark = _case(routed=True)
    report = contention_audit(benchmark, max_decisions=8)
    assert report["decisions"]
    result = replay(benchmark, "longest_tail", "work_conserving")
    assert result["status"] == "completed"
    assert result["trace_valid"]
    bounded = bounded_choice_search(benchmark, max_states=50, time_limit_s=1.0)
    assert bounded["evidence_level"] in {
        "bounded_search",
        "certified_choice_exists",
        "certified_no_choice",
    }


def test_multi_job_has_no_cross_job_edges_and_shared_resources(tmp_path) -> None:
    benchmark = _case()
    composed = compose_real_jobs(
        [("a", benchmark, 0), ("b", benchmark, 3)],
        benchmark_id="np_real_multi_job",
        source_paths=[],
    )
    validate_benchmark(composed)
    for task in composed.tasks:
        if "::" not in task.task_id:
            continue
        job = task.task_id.split("::", 1)[0]
        assert all(parent.startswith(f"{job}::") for parent in task.dependencies)
    assert composed.resources == benchmark.resources
    result = replay(composed, "fifo", "work_conserving")
    assert len(result["jobs"]) == 2


def test_strict_process_budget_terminates_blocked_step() -> None:
    result = run_with_budget(_blocking_worker, (2.0,), time_limit_s=0.2)
    assert result["status"] == "timeout"
    assert result["termination_reason"] == "process_wall_timeout"


def test_stratified_selection_keeps_ga_negative_control_and_overlap_layers() -> None:
    rows = []
    for ga in (1, 4, 8):
        for pp in (1, 2, 4):
            rows.append(
                {
                    "status": "available",
                    "path": f"gpt-ga{ga}-pp{pp}.txt",
                    "model": "gpt",
                    "world_size": 8,
                    "tp": 2,
                    "pp": pp,
                    "ep": 1,
                    "gbs": ga,
                    "mbs": 1,
                }
            )
    specs = selected_specs(rows, max_sources=9)
    assert {item["gbs"] // item["mbs"] for item in specs} == {1, 4, 8}
    assert {item["pp"] for item in specs} == {1, 2, 4}


def test_large_multi_resource_census_never_enumerates_subsets(monkeypatch) -> None:
    from muti_channel.nonpreemptive.solver import NonPreeMultiModel

    resources = tuple(Resource(f"r{i}", "link") for i in range(11))
    benchmark = Benchmark(
        "many_startable",
        "muti_channel",
        "complex_chain",
        "adversarial",
        tuple(Task(f"f{i}", "communication", 1, resources=(f"r{i}",)) for i in range(11)),
        resources,
        semantics=SchedulingSemantics(
            preemption="none",
            decision_epoch="task_completion",
            optional_idle=True,
            resource_model="exclusive_fixed_set",
        ),
        schema_version="3.0",
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("large census enumerated start subsets")

    monkeypatch.setattr(NonPreeMultiModel, "start_subsets", forbidden)
    report = contention_audit(benchmark, max_decisions=1, mode="work_conserving")
    assert report["decisions"][0]["enumeration_skipped"] is True
    assert len(report["decisions"][0]["policy_actions"]) == 8
