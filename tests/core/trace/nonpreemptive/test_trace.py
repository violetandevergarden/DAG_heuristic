from dataclasses import replace

import pytest

from core.dag import DAG, Task
from core.execution.nonpreemptive import Action, NonPreeSingleModel
from core.trace.nonpreemptive import assert_nonpreemptive_trace


def test_nonpreemptive_trace_has_one_interval_per_completed_task() -> None:
    dag = DAG('trace_smoke', (Task('communication', 'comm', 2), Task('compute', 'compute', 1, ('communication',))), context=(('category', 'test'),))
    model = NonPreeSingleModel(dag)
    trace = model.run((Action.flow("communication"), Action.wait()))

    assert_nonpreemptive_trace(dag, trace, mode="optional_idle")
    assert trace.final_state.time == 3


def test_nonpreemptive_replay_rejects_unknown_task_and_duration_corruption() -> None:
    dag = DAG(
        "corruption",
        (Task("flow", "comm", 2),),
        context=(("category", "test"),),
    )
    model = NonPreeSingleModel(dag)
    trace = model.run((Action.flow("flow"),))

    with pytest.raises(AssertionError, match="unknown task"):
        assert_nonpreemptive_trace(
            dag,
            replace(
                trace,
                intervals=(replace(trace.intervals[0], task_id="missing"),),
            ),
        )
    with pytest.raises(AssertionError, match="duration mismatch"):
        assert_nonpreemptive_trace(
            dag,
            replace(
                trace,
                intervals=(replace(trace.intervals[0], end=3),),
            ),
        )


def test_nonpreemptive_replay_rejects_delayed_compute_and_event_corruption() -> None:
    dag = DAG(
        "compute_release",
        (
            Task("flow", "comm", 2),
            Task("compute", "compute", 1, ("flow",)),
        ),
        context=(("category", "test"),),
    )
    model = NonPreeSingleModel(dag)
    trace = model.run((Action.flow("flow"), Action.wait()))
    compute = next(item for item in trace.intervals if item.task_id == "compute")

    with pytest.raises(AssertionError, match="immediately at release"):
        assert_nonpreemptive_trace(
            dag,
            replace(
                trace,
                intervals=tuple(
                    replace(item, start=3, end=4) if item == compute else item
                    for item in trace.intervals
                ),
            ),
        )
    with pytest.raises(AssertionError, match="events"):
        assert_nonpreemptive_trace(dag, replace(trace, events=()))


def test_nonpreemptive_replay_distinguishes_work_conserving_wait() -> None:
    dag = DAG(
        "mode",
        (
            Task("compute", "compute", 2),
            Task("flow", "comm", 1),
        ),
        context=(("category", "test"),),
    )
    trace = NonPreeSingleModel(dag).run((Action.wait(), Action.flow("flow")))

    assert_nonpreemptive_trace(dag, trace, mode="optional_idle")
    with pytest.raises(AssertionError, match="work-conserving WAIT"):
        assert_nonpreemptive_trace(dag, trace, mode="work_conserving")
