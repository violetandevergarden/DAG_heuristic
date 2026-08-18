import pytest

from core.dag import BenchmarkDAG, BenchTask
from core.execution.multi_resource import MultiResourceAction, PreemptiveMultiResourceModel
from muti_channel.preemptive.constructors import enumerate_bounded, greedy, multi_seed, one_exchange
from muti_channel.preemptive.packing import PackingBudget, build_conflict_graph, validate_maximal_action
from muti_channel.preemptive.solver import score_tasks


def _case():
    dag = BenchmarkDAG("packing", "test", (
        BenchTask("wide", "comm", 2),
        BenchTask("left", "comm", 3),
        BenchTask("right", "comm", 3),
    ))
    model = PreemptiveMultiResourceModel(dag, {
        "wide": frozenset({"r0", "r1"}),
        "left": frozenset({"r0"}),
        "right": frozenset({"r1"}),
    })
    return model, model.initial_state()


def test_conflict_graph_and_contract_reject_nonmaximal_or_conflicting_actions():
    model, state = _case()
    graph = build_conflict_graph(model, state)
    assert graph.conflict_edges == (("left", "wide"), ("right", "wide"))
    validate_maximal_action(model, state, MultiResourceAction(("left", "right")))
    with pytest.raises(ValueError, match="not inclusion-maximal"):
        validate_maximal_action(model, state, MultiResourceAction(("left",)))
    with pytest.raises(ValueError, match="resource conflict"):
        validate_maximal_action(model, state, MultiResourceAction(("left", "wide")))


def test_constructors_are_deterministic_read_only_and_return_only_legal_sets():
    model, state = _case()
    before = state
    scores = score_tasks(model, state, "longest_tail")
    budget = PackingBudget(k_seed=3, b_pack=100, max_sets=8)
    results = [greedy(model, state, scores), multi_seed(model, state, scores, budget), one_exchange(model, state, scores, budget), enumerate_bounded(model, state, scores, budget)]
    assert state == before
    for result in results:
        assert result == type(result)(result.selected, result.candidates, result.stats)
        for action in result.candidates:
            validate_maximal_action(model, state, action)
    assert set(results[-1].candidates) == set(model.maximal_actions(state))


def test_budget_exhaustion_keeps_legal_greedy_fallback():
    model, state = _case()
    scores = score_tasks(model, state, "longest_tail")
    result = multi_seed(model, state, scores, PackingBudget(k_seed=3, b_pack=0))
    validate_maximal_action(model, state, result.selected)
    assert result.stats.budget_exhausted
    assert result.stats.fallback_reason == "pack_budget"
