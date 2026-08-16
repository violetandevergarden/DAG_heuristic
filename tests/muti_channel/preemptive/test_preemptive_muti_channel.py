from core.dag import BenchmarkDAG, BenchTask
from muti_channel.preemptive.solver import (
    PreemptiveMultiResourceModel,
    exact_oracle,
    rollout_sets,
    schedule_pack,
)


def test_preemptive_multi_channel_has_an_explicit_family_entry() -> None:
    dag = BenchmarkDAG(
        "multi_preemptive_smoke",
        "test",
        (BenchTask("left", "comm", 2), BenchTask("right", "comm", 3)),
    )
    resources = {
        "left": frozenset({"left"}),
        "right": frozenset({"right"}),
    }

    assert exact_oracle(dag, resources).makespan == 3


def _multi_instance():
    dag = BenchmarkDAG(
        "multi_overlap",
        "test",
        (
            BenchTask("a", "comm", 4),
            BenchTask("a_tail", "compute", 3, ("a",)),
            BenchTask("b", "comm", 4),
            BenchTask("b_tail", "compute", 3, ("b",)),
            BenchTask("c", "comm", 2),
        ),
    )
    resources = {
        "a": frozenset({"left"}),
        "b": frozenset({"right"}),
        "c": frozenset({"left", "right"}),
    }
    return dag, resources


def test_multi_resource_model_runs_disjoint_flows_concurrently() -> None:
    dag, resources = _multi_instance()
    model = PreemptiveMultiResourceModel(dag, resources)
    actions = model.maximal_actions(model.initial_state())

    assert {action.communications for action in actions} == {("a", "b"), ("c",)}
    optimum = exact_oracle(dag, resources)
    assert optimum.makespan == 7
    assert schedule_pack(dag, resources).makespan >= optimum.makespan
    assert rollout_sets(dag, resources).makespan >= optimum.makespan


def test_maximal_set_oracle_matches_single_resource_serial_work() -> None:
    dag = BenchmarkDAG(
        "shared",
        "test",
        (BenchTask("a", "comm", 2), BenchTask("b", "comm", 3)),
    )
    resources = {"a": frozenset({"r"}), "b": frozenset({"r"})}
    assert exact_oracle(dag, resources).makespan == 5
