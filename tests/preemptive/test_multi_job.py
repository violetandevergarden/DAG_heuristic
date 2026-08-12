from __future__ import annotations

from core.dag import BenchmarkDAG, BenchTask
from preemptive.multi_job import (
    JobSpec,
    build_multi_resource_top1_counterexample,
    build_top1_counterexample,
    compose_jobs,
    evaluate_schedule,
    exact_hierarchical,
    exact_makespan,
    schedule_multi_resource_hierarchical,
    schedule_hierarchical,
    solo_optimal_jct,
    teacher_candidate_recall,
)
from preemptive.single_channel.solver import exact_oracle


def _one_flow_job(name: str, duration: int, tail: int) -> BenchmarkDAG:
    return BenchmarkDAG(
        name,
        "test",
        (
            BenchTask("flow", "comm", duration, role="PP"),
            BenchTask("tail", "compute", tail, ("flow",), role="OPT"),
        ),
    )


def test_composition_encodes_arrival_without_cross_job_dependencies() -> None:
    instance = compose_jobs((
        JobSpec("early", _one_flow_job("a", 2, 1), arrival=0),
        JobSpec("late", _one_flow_job("b", 1, 1), arrival=5),
    ))
    task_map = instance.dag.task_map()

    assert task_map["early::flow"].deps == ("early::__arrival__",)
    assert task_map["late::flow"].deps == ("late::__arrival__",)
    assert all(
        instance.task_job[parent] == instance.task_job[task.task_id]
        for task in instance.dag.tasks
        for parent in task.deps
    )


def test_per_job_completion_and_slowdown_are_reported() -> None:
    instance = compose_jobs((
        JobSpec("a", _one_flow_job("a", 2, 3)),
        JobSpec("b", _one_flow_job("b", 1, 1)),
    ))
    schedule = exact_oracle(instance.dag)
    result = evaluate_schedule(
        instance,
        schedule,
        solo_completion=solo_optimal_jct(instance),
    )

    assert result.makespan == 5
    assert {job.job_id for job in result.jobs} == {"a", "b"}
    assert all(job.jct == job.completion - job.arrival for job in result.jobs)
    assert result.max_slowdown is not None
    assert result.max_slowdown >= 1.0


def test_top1_candidate_truncation_has_a_strict_exact_gap() -> None:
    instance = build_top1_counterexample()
    full = exact_makespan(instance)
    top1 = exact_hierarchical(instance, candidate_width=1)
    top2 = exact_hierarchical(instance, candidate_width=2)
    rollout1 = schedule_hierarchical(instance, candidate_width=1)
    rollout2 = schedule_hierarchical(instance, candidate_width=2)

    assert full.makespan == 18
    assert top1.makespan == rollout1.makespan == 19
    assert top2.makespan == rollout2.makespan == full.makespan
    assert teacher_candidate_recall(instance, full.schedule) == {
        1: 5 / 6,
        2: 1.0,
        4: 1.0,
    }


def test_multi_resource_top1_can_hide_a_compatible_flow() -> None:
    instance, resources = build_multi_resource_top1_counterexample()
    top1 = schedule_multi_resource_hierarchical(
        instance,
        resources,
        candidate_width=1,
    )
    top2 = schedule_multi_resource_hierarchical(
        instance,
        resources,
        candidate_width=2,
    )

    assert top1.makespan == 25
    assert top2.makespan == 18
    assert top2.actions[0].communications == ("A::private", "B::shared")


def test_weighted_jct_exact_can_choose_a_different_order() -> None:
    long_job = BenchmarkDAG("long", "test", (BenchTask("flow", "comm", 10),))
    short_job = BenchmarkDAG("short", "test", (BenchTask("flow", "comm", 1),))
    instance = compose_jobs((JobSpec("A", long_job), JobSpec("B", short_job)))

    makespan = exact_hierarchical(
        instance,
        candidate_width=None,
        objective="makespan",
    )
    weighted_jct = exact_hierarchical(
        instance,
        candidate_width=None,
        objective="weighted_jct",
    )

    assert makespan.makespan == weighted_jct.makespan == 11
    assert makespan.weighted_jct == 10.5
    assert weighted_jct.weighted_jct == 6.0
