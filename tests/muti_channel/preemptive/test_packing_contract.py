import pytest

from core.dag import BenchmarkDAG, BenchTask
from core.execution.multi_resource import MultiResourceAction, PreemptiveMultiResourceModel
from benchmark_generate.llm.preemptive.packing_motifs import packing_motifs
from muti_channel.preemptive.constructors import enumerate_bounded, greedy, multi_seed, one_exchange
from muti_channel.preemptive.packing import PackingBudget, build_conflict_graph, validate_maximal_action
from muti_channel.preemptive.solver import (
    exact_completion_from_state_uncompressed, exact_oracle_uncompressed,
    schedule_bounded_packing, score_tasks,
)


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
        assert result.selected == result.baseline
        assert result.selector == "unselected"
        for action in result.candidates:
            validate_maximal_action(model, state, action)
    assert set((*results[-1].candidates, results[-1].baseline)) == set(model.maximal_actions(state))


def test_budget_exhaustion_keeps_legal_greedy_fallback():
    model, state = _case()
    scores = score_tasks(model, state, "longest_tail")
    result = multi_seed(model, state, scores, PackingBudget(k_seed=3, b_pack=0))
    validate_maximal_action(model, state, result.selected)
    assert result.stats.budget_exhausted
    assert result.stats.fallback_reason == "pack_budget"


def test_streaming_enumeration_obeys_set_and_operation_budgets_without_full_actions():
    model, state = _case()
    scores = score_tasks(model, state, "longest_tail")
    result = enumerate_bounded(model, state, scores, PackingBudget(b_pack=8, max_sets=2))
    assert len(result.candidates) <= 2
    assert result.stats.operations <= 8
    assert result.truncated


def test_explicit_selector_executes_selected_nonbaseline_action_and_eval_budget_is_hard():
    motif = next(item for item in packing_motifs() if item.name == "star_wide_vs_pair")
    model = PreemptiveMultiResourceModel(motif.dag, motif.resources)
    state = model.initial_state()
    result = schedule_bounded_packing(
        model.dag, model.resources, constructor="enumeration", selector="set_score",
        budget=PackingBudget(b_pack=100, max_sets=2),
    )
    assert result.actions[0] != result.actions[0].__class__(("x0",))
    assert result.selector == "set_score"
    for limit in (0, 1, 2):
        evaluated = schedule_bounded_packing(
            model.dag, model.resources, constructor="enumeration", selector="depth1_completion",
            budget=PackingBudget(b_pack=100, max_sets=2, b_eval=limit),
        )
        assert evaluated.completion_calls <= limit
        assert evaluated.max_completion_calls_per_decision <= limit


def test_every_maximal_first_action_has_an_uncompressed_exact_suffix_value():
    model, state = _case()
    values = []
    for action in model.maximal_actions(state):
        suffix = exact_completion_from_state_uncompressed(model, model.step(state, action))
        assert suffix.status == "optimal"
        values.append(suffix.makespan)
    whole = exact_oracle_uncompressed(model.dag, model.resources)
    assert min(values) == whole.makespan
