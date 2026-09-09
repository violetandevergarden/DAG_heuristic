from benchmark.model import Benchmark, Resource, SchedulingSemantics, Task
from llm_structured.nonpreemptive.barrier import BarrierConfig, BarrierGraph, schedule
from llm_structured.nonpreemptive.barrier.contracts import BarrierBudget
from llm_structured.nonpreemptive.barrier.features import action_features
from llm_structured.nonpreemptive.baseline.adapters import make_adapter


def _single(names=("a", "b", "join")):
    a, b, join = names
    return Benchmark(
        "barrier", "single_channel", "complex_chain", "adversarial",
        (Task(a, "communication", 4), Task(b, "communication", 2),
         Task(join, "compute", 1, (a, b)), Task("tail", "compute", 3, (join,))),
        (Resource("channel:0", "channel"),),
        SchedulingSemantics(resource_model="exclusive"),
    )


def _multi():
    return Benchmark(
        "barrier_multi", "muti_channel", "muti_channel", "adversarial",
        (Task("a", "communication", 4, resources=("r0",)),
         Task("b", "communication", 2, resources=("r1",)),
         Task("join", "compute", 1, ("a", "b"))),
        (Resource("r0", "link"), Resource("r1", "link")),
        SchedulingSemantics(resource_model="exclusive_fixed_set"),
    )


def test_graph_is_dependency_only_under_renaming():
    first = BarrierGraph.build(_single())
    second = BarrierGraph.build(_single(("renamed-a", "renamed-b", "renamed-join")))
    assert len(first.barriers) == len(second.barriers) == 1
    assert sorted(map(len, first.parents.values())) == sorted(map(len, second.parents.values()))


def test_direct_last_missing_and_transition_release_are_distinct():
    benchmark = _single(); adapter = make_adapter(benchmark); state = adapter.initial_state()
    state = adapter.step(state, next(a for a in adapter.legal_actions(state, "work_conserving") if a.task_id == "a")).after
    action = next(a for a in adapter.legal_actions(state, "work_conserving") if a.task_id == "b")
    features = action_features(adapter, BarrierGraph.build(benchmark), state, action, BarrierConfig(mode="work_conserving"), BarrierBudget())
    assert features.direct_last_missing == ("join",)
    assert "join" in features.immediate_release
    assert features.quantity_modes["direct_last_missing"] == "structural_exact"
    assert features.quantity_modes["immediate_release"] == "transition_exact"


def test_schedule_reuses_whole_flow_transition_and_has_valid_trace():
    result = schedule(_single(), BarrierConfig(method="margin", mode="optional_idle"))
    assert result.status == "completed"
    assert result.trace_valid
    assert result.makespan is not None


def test_multi_resource_set_uses_union_and_preserves_legality():
    benchmark = _multi(); adapter = make_adapter(benchmark); state = adapter.initial_state()
    action = max(adapter.legal_actions(state, "work_conserving"), key=lambda item: len(item.starts))
    features = action_features(adapter, BarrierGraph.build(benchmark), state, action,
                               BarrierConfig(mode="work_conserving"), BarrierBudget())
    assert set(features.resource_union) == {"r0", "r1"}
    result = schedule(benchmark, BarrierConfig(method="last_missing_tie", mode="work_conserving"))
    assert result.status == "completed" and result.trace_valid


def test_zero_feature_budget_falls_back_without_illegal_action():
    result = schedule(_single(), BarrierConfig(method="counterfactual", max_feature_transitions=0))
    assert result.status == "completed"
    assert result.metrics["budget_rejections"] > 0
    assert result.metrics["divergences_from_lt"] == 0
