from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from benchmark import (
    Benchmark,
    Resource,
    SchedulingSemantics,
    Task,
    load_benchmark,
    write_benchmark,
)
from benchmark_generate.export import build_index
from benchmark_generate.llm.nonpreemptive.contention_audit import contention_audit
from benchmark_generate.llm.common.multi_job import compose_real_jobs
from benchmark_generate.llm.nonpreemptive.multi_job_suite import (
    assert_topology_pair,
    rebuild_manifest,
    static_cross_job_overlap,
)
from llm_structured.nonpreemptive.baseline import make_adapter, schedule_baseline

SEMANTICS = SchedulingSemantics(
    preemption="none",
    decision_epoch="task_completion",
    optional_idle=True,
    resource_model="exclusive",
)


def _parent(name: str = "parent") -> Benchmark:
    return Benchmark(
        name,
        "single_channel",
        "complex_chain",
        "real",
        (
            Task("c0", "compute", 2),
            Task(
                "f0",
                "communication",
                3,
                dependencies=("c0",),
                resources=("channel:0",),
            ),
            Task("c1", "compute", 1, dependencies=("f0",)),
        ),
        (Resource("channel:0", "channel"),),
        semantics=SEMANTICS,
        schema_version="3.0",
        time_unit="us",
        metadata={"provenance": {"source": {"content_hash": "source"}}},
    )


def test_composition_rejects_incompatible_time_and_semantics() -> None:
    parent = _parent()
    with pytest.raises(ValueError, match="time unit"):
        compose_real_jobs(
            [("a", parent, 0), ("b", replace(parent, time_unit="ms"), 0)],
            benchmark_id="bad-unit",
            source_paths=[],
        )
    changed = replace(parent, semantics=replace(SEMANTICS, optional_idle=False))
    with pytest.raises(ValueError, match="scheduling semantics"):
        compose_real_jobs(
            [("a", parent, 0), ("b", changed, 0)],
            benchmark_id="bad-semantics",
            source_paths=[],
        )


def test_arrival_namespace_shared_channel_and_cross_job_audit() -> None:
    parent = _parent()
    composed = compose_real_jobs(
        [("a", parent, 0), ("b", parent, 0)],
        benchmark_id="two-jobs",
        source_paths=[],
    )
    assert all(
        dependency.startswith(task.task_id.split("::", 1)[0] + "::")
        for task in composed.tasks
        for dependency in task.dependencies
    )
    overlap = static_cross_job_overlap(composed)
    assert overlap["cross_job_overlap"]
    report = contention_audit(composed, max_decisions=16)
    assert report["cross_job_ready_conflict_count"] >= 1


def test_job_aware_rules_remain_legal_in_both_idle_modes() -> None:
    parent = _parent()
    composed = compose_real_jobs(
        [("a", parent, 0), ("b", parent, 0)],
        benchmark_id="rules",
        source_paths=[],
    )
    metadata = dict(composed.metadata)
    metadata["multi_job"] = [
        {**item, "isolated_makespan": 6} for item in metadata["multi_job"]
    ]
    composed = replace(composed, metadata=metadata)
    for mode in ("optional_idle", "work_conserving"):
        for rule in (
            "job_fixed_order",
            "job_round_robin",
            "job_age",
            "shortest_remaining_job",
            "job_aware_longest_tail",
            "starvation_safeguard",
        ):
            result = schedule_baseline(composed, rule, mode)
            assert result["trace_valid"]
            assert len(result["jobs"]) == 2


def test_multi_decision_context_does_not_enumerate_subsets(monkeypatch) -> None:
    root = Path(__file__).resolve().parents[3]
    benchmark = load_benchmark(
        root / "benchmark/muti_channel/nonpreemptive/adversarial/nonmaximal_start_np.json"
    )
    adapter = make_adapter(benchmark)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("ordinary policy enumerated start subsets")

    monkeypatch.setattr(adapter.model, "start_subsets", forbidden)
    context = adapter.decision_context(adapter.initial_state(), "work_conserving")
    assert context.legal_actions


def test_topology_pair_allows_only_route_duration_differences() -> None:
    left = _parent()
    right_tasks = tuple(
        replace(task, duration=4) if task.kind == "communication" else task
        for task in left.tasks
    )
    assert_topology_pair(left, replace(left, benchmark_id="right", tasks=right_tasks))
    bad_tasks = (replace(left.tasks[0], duration=9), *left.tasks[1:])
    with pytest.raises(ValueError, match="compute duration"):
        assert_topology_pair(left, replace(left, tasks=bad_tasks))


def test_manifest_rebuild_is_deterministic_and_index_skips_staging(tmp_path) -> None:
    root = tmp_path
    source_path = root / "source.json"
    write_benchmark(_parent(), source_path)
    spec = {
        "benchmark_id": "rebuilt",
        "relative_path": "multi_job/rebuilt.json",
        "sources": [
            {
                "path": "source.json",
                "arrival": arrival,
                "arrival_ratio": float(arrival),
                "isolated_makespan": 6,
            }
            for arrival in (0, 1)
        ],
        "case_class": "test",
        "source_group": "test",
        "split": "development",
    }
    specs = root / "specs.jsonl"
    specs.write_text(json.dumps(spec) + "\n", encoding="utf-8")
    first = rebuild_manifest(root, specs, root / "stage-a")
    second = rebuild_manifest(root, specs, root / "stage-b")
    assert first[0]["content_hash"] == second[0]["content_hash"]

    benchmark_root = root / "benchmark"
    write_benchmark(_parent("public"), benchmark_root / "public.json")
    write_benchmark(_parent("hidden"), benchmark_root / ".staging/run/hidden.json")
    rows = build_index(benchmark_root)
    assert {row["id"] for row in rows} == {"nonpreemptive:complex_chain:public"}
