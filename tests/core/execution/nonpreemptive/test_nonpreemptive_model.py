"""Semantic regressions for the revised non-preemptive research model."""

import pytest

from core.dag import DAG, Task
from core.execution.nonpreemptive import (
    Action,
    NonPreeSingleModel,
)
from core.trace.nonpree_single import assert_nonpreemptive_trace


def _overlap_dag() -> DAG:
    return DAG('flow_atomicity', (Task('release', 'compute', 2), Task('long_flow', 'comm', 5), Task('new_flow', 'comm', 1, ('release',)), Task('compute_tail', 'compute', 3, ('new_flow',))), context=(('category', 'r0_semantics'),))


def _waiting_counterexample(magnitude: int = 10) -> DAG:
    return DAG('waiting_is_necessary', (Task('release_b', 'compute', 1), Task('A', 'comm', magnitude), Task('B', 'comm', 1, ('release_b',)), Task('tail_b', 'compute', magnitude, ('B',))), context=(('category', 'r0_semantics'),))


def test_flow_is_atomic_while_compute_completion_releases_a_new_flow() -> None:
    model = NonPreeSingleModel(_overlap_dag())
    transition = model.step(model.initial_state(), Action.flow("long_flow"))

    assert transition.before.time == 0
    assert transition.after.time == 5
    assert model.task_runtime(transition.after, "release").completed_at == 2
    assert model.task_runtime(transition.after, "new_flow").status == "pending"
    assert model.ready_flows(transition.after) == ("new_flow",)
    assert [(span.task_id, span.start, span.end) for span in transition.intervals] == [
        ("long_flow", 0, 5),
        ("release", 0, 2),
    ]
    assert not any(
        event.kind == "flow_started" and event.task_id == "new_flow"
        for event in transition.events
    )


def test_compute_is_nonpreemptive_and_can_overlap_communication() -> None:
    model = NonPreeSingleModel(_overlap_dag())
    state = model.initial_state()

    assert model.task_runtime(state, "release").remaining == 2
    after_flow = model.step(state, Action.flow("long_flow")).after
    assert model.task_runtime(after_flow, "release").started_at == 0
    assert model.task_runtime(after_flow, "release").completed_at == 2


def test_wait_can_be_voluntary_and_repeated_until_distinct_releases() -> None:
    dag = DAG('repeated_wait', (Task('release_1', 'compute', 1), Task('release_2', 'compute', 3), Task('ready_now', 'comm', 4), Task('flow_1', 'comm', 1, ('release_1',)), Task('flow_2', 'comm', 1, ('release_2',))), context=(('category', 'r0_semantics'),))
    model = NonPreeSingleModel(dag)
    state = model.initial_state()

    assert Action.wait() in model.legal_actions(state)
    first = model.step(state, Action.wait())
    assert first.after.time == 1
    assert set(model.ready_flows(first.after)) == {"ready_now", "flow_1"}
    assert Action.wait() in model.legal_actions(first.after)

    second = model.step(first.after, Action.wait())
    assert second.after.time == 3
    assert set(model.ready_flows(second.after)) == {
        "ready_now",
        "flow_1",
        "flow_2",
    }
    assert Action.wait() not in model.legal_actions(second.after)
    with pytest.raises(ValueError, match="illegal action"):
        model.step(second.after, Action.wait())

    trace = model.run(
        [
            Action.wait(),
            Action.wait(),
            Action.flow("flow_1"),
            Action.flow("flow_2"),
            Action.flow("ready_now"),
        ]
    )
    assert trace.makespan == 9
    assert model.is_finished(trace.final_state)
    assert_nonpreemptive_trace(model.dag, trace, mode="optional_idle")


def test_optional_wait_beats_every_work_conserving_first_action() -> None:
    model = NonPreeSingleModel(_waiting_counterexample(10))

    work_conserving = model.run(
        [Action.flow("A"), Action.flow("B"), Action.wait()]
    )
    optional_idle = model.run(
        [Action.wait(), Action.flow("B"), Action.flow("A")]
    )

    assert work_conserving.makespan == 21
    assert optional_idle.makespan == 12
    assert model.is_finished(work_conserving.final_state)
    assert model.is_finished(optional_idle.final_state)
    assert_nonpreemptive_trace(model.dag, work_conserving, mode="work_conserving")
    assert_nonpreemptive_trace(model.dag, optional_idle, mode="optional_idle")


def test_task_ids_dependencies_and_dag_are_not_mutated() -> None:
    dag = _overlap_dag()
    original = tuple((task.task_id, task.deps) for task in dag.tasks)
    model = NonPreeSingleModel(dag)
    trace = model.run(
        [Action.flow("long_flow"), Action.flow("new_flow"), Action.wait()]
    )

    assert model.is_finished(trace.final_state)
    assert trace.makespan == 9
    assert dag.validate() == []
    assert tuple((task.task_id, task.deps) for task in dag.tasks) == original
    assert_nonpreemptive_trace(dag, trace, mode="optional_idle")


def test_invalid_dag_and_zero_duration_flow_are_rejected() -> None:
    cyclic = DAG('cycle', (Task('a', 'comm', 1, ('b',)), Task('b', 'compute', 1, ('a',))), context=(('category', 'r0_semantics'),))
    with pytest.raises(ValueError, match="cycle"):
        NonPreeSingleModel(cyclic)

    zero_flow = DAG('zero_flow', (Task('a', 'comm', 0),), context=(('category', 'r0_semantics'),))
    with pytest.raises(ValueError, match="positive flow"):
        NonPreeSingleModel(zero_flow)


def test_zero_duration_compute_is_an_instantaneous_closure() -> None:
    dag = DAG('zero_compute', (Task('zero', 'compute', 0), Task('flow', 'comm', 1, ('zero',))), context=(('category', 'r0_semantics'),))
    model = NonPreeSingleModel(dag)
    initial = model.initial_state()

    assert model.task_runtime(initial, "zero").completed_at == 0
    trace = model.run([Action.flow("flow")])
    assert trace.makespan == 1
    assert model.is_finished(trace.final_state)
    assert_nonpreemptive_trace(model.dag, trace, mode="optional_idle")


def test_zero_duration_compute_chain_closes_in_topological_order() -> None:
    dag = DAG(
        "zero_compute_chain",
        (
            Task("first", "compute", 0),
            Task("second", "compute", 0, ("first",)),
            Task("third", "compute", 0, ("second",)),
            Task("flow", "comm", 1, ("third",)),
        ),
        context=(("category", "r0_semantics"),),
    )
    model = NonPreeSingleModel(dag)

    state = model.initial_state()

    assert all(model.task_runtime(state, task_id).completed_at == 0 for task_id in ("first", "second", "third"))
    assert model.ready_flows(state) == ("flow",)
