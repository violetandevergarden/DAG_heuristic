"""Regressions for communication pause/resume semantics."""

from benchmark import benchmark_from_dict, benchmark_to_dict
from core.conversion import to_internal_dag
from core.dag import BenchmarkDAG, BenchTask
from preemptive.core.model import Action, PreemptiveDAGModel, assert_preemptive_trace
from preemptive.single_channel.solver import schedule_longest_tail
from registry import algorithms_for, solve


def _release_dag() -> BenchmarkDAG:
    return BenchmarkDAG(
        "preemption_unlock",
        "test",
        (
            BenchTask("release_b", "compute", 3),
            BenchTask("A", "comm", 10),
            BenchTask("B", "comm", 2, ("release_b",)),
            BenchTask("tail_b", "compute", 10, ("B",)),
        ),
    )


def _payload() -> dict:
    return {
        "schema_version": "2.0",
        "id": "preemption_unlock",
        "scenario": "single_channel",
        "family": "complex_chain",
        "category": "adversarial",
        "objective": "makespan",
        "time_unit": "tick",
        "semantics": {
            "preemption": "communication_resume",
            "decision_epoch": "task_event",
            "optional_idle": True,
            "compute_model": "unbounded_parallel",
            "resource_model": "exclusive_fixed_set",
            "preemption_cost": 0,
            "minimum_quantum": 0,
        },
        "resources": [{"id": "channel:0", "kind": "channel"}],
        "tasks": [
            {"id": "release_b", "kind": "compute", "duration": 3, "dependencies": [], "resources": []},
            {"id": "A", "kind": "communication", "duration": 10, "dependencies": [], "resources": ["channel:0"]},
            {"id": "B", "kind": "communication", "duration": 2, "dependencies": ["release_b"], "resources": ["channel:0"]},
            {"id": "tail_b", "kind": "compute", "duration": 10, "dependencies": ["B"], "resources": []},
        ],
    }


def test_dispatch_stops_at_compute_event_and_preserves_progress() -> None:
    model = PreemptiveDAGModel(_release_dag())
    first = model.step(model.initial_state(), Action.run("A"))

    assert first.after.time == 3
    assert model.task_runtime(first.after, "A").status == "suspended"
    assert model.task_runtime(first.after, "A").remaining == 7
    assert set(model.eligible_communications(first.after)) == {"A", "B"}

    second = model.step(first.after, Action.run("B"))
    third = model.step(second.after, Action.run("A"))
    final = model.step(third.after, Action.wait())
    assert final.after.time == 15
    assert model.is_finished(final.after)


def test_trace_allows_multiple_segments_but_conserves_work() -> None:
    model = PreemptiveDAGModel(_release_dag())
    trace = model.run(
        [Action.run("A"), Action.run("B"), Action.run("A"), Action.wait()]
    )
    assert_preemptive_trace(model, trace)
    assert [
        (span.task_id, span.start, span.end)
        for span in trace.intervals
        if span.kind == "comm"
    ] == [("A", 0, 3), ("B", 3, 5), ("A", 5, 12)]


def test_v2_loader_registry_and_longest_tail_form_a_runnable_loop() -> None:
    benchmark = benchmark_from_dict(_payload())

    assert benchmark.semantics.is_preemptive
    assert benchmark_from_dict(benchmark_to_dict(benchmark)) == benchmark
    assert set(algorithms_for(benchmark)) == {"longest_tail"}
    result = solve(benchmark, "longest_tail")
    assert result.makespan == 15
    assert result.preemptions == 1
    assert_preemptive_trace(PreemptiveDAGModel(to_internal_dag(benchmark)), result.trace)


def test_longest_tail_accepts_parallel_chain_shape_too() -> None:
    dag = BenchmarkDAG(
        "two_chains",
        "test",
        (
            BenchTask("release", "compute", 1),
            BenchTask("a", "comm", 4),
            BenchTask("a_tail", "compute", 2, ("a",)),
            BenchTask("b", "comm", 1, ("release",)),
            BenchTask("b_tail", "compute", 5, ("b",)),
        ),
    )
    result = schedule_longest_tail(dag)
    assert result.makespan == 7
    assert_preemptive_trace(PreemptiveDAGModel(dag), result.trace)
