from core.dag import BenchmarkDAG, BenchTask
from muti_channel.preemptive.solver import (
    PreemptiveMultiResourceModel,
    exact_oracle as multi_exact,
    rollout_sets,
    schedule_pack,
)
from single_channel.complex_chain.preemptive.solver import (
    beam_search,
    exact_oracle,
    monte_carlo,
    schedule_longest_tail,
    schedule_rollout,
)


def _parallel_counterexample() -> BenchmarkDAG:
    return BenchmarkDAG(
        "tail_counterexample",
        "test",
        (
            BenchTask("a1", "comm", 2),
            BenchTask("a_gap", "compute", 3, ("a1",)),
            BenchTask("a2", "comm", 1, ("a_gap",)),
            BenchTask("a_tail", "compute", 1, ("a2",)),
            BenchTask("b1", "comm", 1),
            BenchTask("b_gap", "compute", 2, ("b1",)),
            BenchTask("b2", "comm", 2, ("b_gap",)),
            BenchTask("b_tail", "compute", 1, ("b2",)),
        ),
    )


def test_single_channel_searches_are_feasible_and_bounded_by_incumbent() -> None:
    dag = _parallel_counterexample()
    optimum = exact_oracle(dag)
    baseline = schedule_longest_tail(dag)

    assert optimum.makespan == 8
    assert baseline.makespan == 9
    assert schedule_rollout(dag, top_k=2).makespan == 8
    assert beam_search(dag, width=8).makespan == 8
    assert monte_carlo(dag, samples=16, seed=7).makespan <= baseline.makespan


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
    optimum = multi_exact(dag, resources)
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
    assert multi_exact(dag, resources).makespan == 5
