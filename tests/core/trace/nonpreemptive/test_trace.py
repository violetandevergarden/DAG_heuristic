from core.dag import BenchmarkDAG, BenchTask
from core.execution.nonpreemptive import Action, NonPreemptiveDAGModel
from core.trace.nonpreemptive import assert_nonpreemptive_trace


def test_nonpreemptive_trace_has_one_interval_per_completed_task() -> None:
    dag = BenchmarkDAG(
        "trace_smoke",
        "test",
        (
            BenchTask("communication", "comm", 2),
            BenchTask("compute", "compute", 1, ("communication",)),
        ),
    )
    model = NonPreemptiveDAGModel(dag)
    trace = model.run((Action.flow("communication"), Action.wait()))

    assert_nonpreemptive_trace(trace)
    assert trace.final_state.time == 3
