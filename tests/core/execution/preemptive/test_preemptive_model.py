"""Regressions for communication pause/resume semantics."""

from benchmark import benchmark_from_dict, benchmark_to_dict
from core.conversion import to_dag
from core.dag import DAG, Task
from core.execution.preemptive import Action, PreeSingleModel
from core.trace.preemptive import assert_preemptive_trace
from registry import algorithms_for, solve
from single_channel.complex_chain.preemptive.solver import schedule_longest_tail


def _release_dag() -> DAG:
    return DAG('preemption_unlock', (Task('release_b', 'compute', 3), Task('A', 'comm', 10), Task('B', 'comm', 2, ('release_b',)), Task('tail_b', 'compute', 10, ('B',))), context=(('category', 'test'),))


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
            "optional_idle": False,
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
    model = PreeSingleModel(_release_dag())
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
    model = PreeSingleModel(_release_dag())
    trace = model.run(
        [Action.run("A"), Action.run("B"), Action.run("A"), Action.wait()]
    )
    assert_preemptive_trace(model, trace)
    assert [
        (span.task_id, span.start, span.end)
        for span in trace.intervals
        if span.kind == "comm"
    ] == [("A", 0, 3), ("B", 3, 5), ("A", 5, 12)]


def test_zero_duration_compute_chain_closes_in_topological_order() -> None:
    dag = DAG(
        "zero_compute_chain",
        (
            Task("first", "compute", 0),
            Task("second", "compute", 0, ("first",)),
            Task("third", "compute", 0, ("second",)),
            Task("flow", "comm", 1, ("third",)),
        ),
        context=(("category", "test"),),
    )
    model = PreeSingleModel(dag)

    state = model.initial_state()

    assert all(model.task_runtime(state, task_id).completed_at == 0 for task_id in ("first", "second", "third"))
    assert model.eligible_communications(state) == ("flow",)


def test_v2_loader_registry_and_longest_tail_form_a_runnable_loop() -> None:
    benchmark = benchmark_from_dict(_payload())

    assert benchmark.semantics.is_preemptive
    assert benchmark_from_dict(benchmark_to_dict(benchmark)) == benchmark
    algorithms = algorithms_for(benchmark)
    assert {"longest_tail", "rollout2", "beam8", "exact"} <= set(algorithms)
    assert all(item.semantics == "communication_resume" for item in algorithms.values())
    assert algorithms["beam8"].development_status == "experimental"
    assert all(
        item.development_status == "active"
        for name, item in algorithms.items()
        if name not in {"beam8", "beam32"}
    )
    assert not any(item.supports_wait for item in algorithms.values())
    result = solve(benchmark, "longest_tail")
    assert result.makespan == 15
    assert result.preemptions == 1
    assert_preemptive_trace(PreeSingleModel(to_dag(benchmark)), result.trace)


def test_longest_tail_accepts_parallel_chain_shape_too() -> None:
    dag = DAG('two_chains', (Task('release', 'compute', 1), Task('a', 'comm', 4), Task('a_tail', 'compute', 2, ('a',)), Task('b', 'comm', 1, ('release',)), Task('b_tail', 'compute', 5, ('b',))), context=(('category', 'test'),))
    result = schedule_longest_tail(dag)
    assert result.makespan == 7
    assert_preemptive_trace(PreeSingleModel(dag), result.trace)
