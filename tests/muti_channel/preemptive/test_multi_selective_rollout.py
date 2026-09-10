from benchmark_generate.llm.preemptive.packing_motifs import packing_motifs
from core.execution.preemptive import PreeMultiModel
from llm_structured.preemptive.selective_rollout.contracts import RolloutBudget
from llm_structured.preemptive.selective_rollout.multi import (
    generate_candidates, schedule_selective_rollout,
)
from muti_channel.preemptive.solver import schedule_pack
from core.trace.pree_multi import assert_multi_resource_trace


def _motif(name="star_wide_vs_pair"):
    return next(item for item in packing_motifs() if item.name == name)


def test_multi_resource_candidates_are_legal_maximal_sets():
    motif = _motif()
    model = PreeMultiModel(motif.dag, motif.resources)
    state, _ = model.normalize_decision_state(model.initial_state())
    candidates = generate_candidates(model, state, 4)
    assert candidates
    for action in candidates:
        assert action in model.legal_actions(state)


def test_multi_resource_depth_zero_is_lt_and_uses_no_completion():
    motif = _motif()
    baseline = schedule_pack(motif.dag, motif.resources, "longest_tail")
    result = schedule_selective_rollout(
        motif.dag, motif.resources,
        budget=RolloutBudget(search_depth=0),
    )
    assert result.completion_calls == 0
    assert result.actions == baseline.actions


def test_multi_resource_budgeted_search_is_legal_and_bounded():
    motif = _motif("path_future_value")
    budget = RolloutBudget(
        max_candidates=2, max_triggers=1, max_completion_calls=2,
        max_expansions=100, search_depth=1,
        per_decision_time_limit_s=None, total_time_limit_s=None,
    )
    result = schedule_selective_rollout(motif.dag, motif.resources, budget=budget)
    assert result.completion_calls <= budget.max_completion_calls
    assert result.expanded_nodes <= budget.max_expansions
    assert result.trace is not None
    assert_multi_resource_trace(motif.dag, motif.resources, result.trace)


def test_multi_resource_incomplete_evaluation_falls_back_to_lt():
    motif = _motif("path_future_value")
    baseline = schedule_pack(motif.dag, motif.resources, "longest_tail")
    result = schedule_selective_rollout(
        motif.dag, motif.resources,
        budget=RolloutBudget(
            max_candidates=2, max_triggers=1, max_completion_calls=1,
            max_expansions=100, search_depth=1,
            per_decision_time_limit_s=None, total_time_limit_s=None,
        ),
    )
    assert result.actions == baseline.actions
    assert result.fallback_count >= 1
