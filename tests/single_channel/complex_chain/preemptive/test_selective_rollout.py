from core.dag import BenchTask, BenchmarkDAG
from core.execution.preemptive import PreemptiveDAGModel
from core.trace.preemptive import assert_preemptive_trace
from llm_structured.selective_rollout import RolloutBudget
from single_channel.complex_chain.preemptive.selective_rollout import (
    cheap_features,
    schedule_selective_rollout,
    summarize_choice,
)
from single_channel.complex_chain.preemptive.solver import schedule_longest_tail


def _dag():
    return BenchmarkDAG(
        "selective", "adversarial",
        (
            BenchTask("a", "comm", 4),
            BenchTask("a_tail", "compute", 7, ("a",)),
            BenchTask("b", "comm", 1),
            BenchTask("b_tail", "compute", 2, ("b",)),
        ),
    )


def test_choice_gate_and_features_use_residual_state():
    model = PreemptiveDAGModel(_dag())
    state = model.initial_state()
    assert summarize_choice(model, state).kind == "candidate_choice"
    features = cheap_features(model, state)
    assert features.eligible_count == 2
    assert features.feature_version == "single-channel-selective-v1"


def test_zero_trigger_and_zero_completion_budget_are_exact_lt_fallbacks():
    baseline = schedule_longest_tail(_dag())
    for budget in (
        RolloutBudget(max_triggers=0),
        RolloutBudget(max_completion_calls=0),
    ):
        result = schedule_selective_rollout(_dag(), budget=budget)
        assert result.makespan == baseline.makespan
        assert [t.action for t in result.trace.transitions] == [
            t.action for t in baseline.trace.transitions
        ]
        assert_preemptive_trace(PreemptiveDAGModel(_dag()), result.trace)


def test_cache_does_not_change_actions_or_makespan():
    cached = schedule_selective_rollout(_dag(), use_cache=True)
    uncached = schedule_selective_rollout(_dag(), use_cache=False)
    assert cached.makespan == uncached.makespan
    assert [t.action for t in cached.trace.transitions] == [
        t.action for t in uncached.trace.transitions
    ]


def test_depth_two_rollout_uses_extra_prefix_budget_and_is_legal():
    depth1 = schedule_selective_rollout(
        _dag(), budget=RolloutBudget(rollout_depth=1, max_triggers=1,
                                     max_completion_calls=2, total_time_limit_s=None,
                                     per_decision_time_limit_s=None)
    )
    depth2 = schedule_selective_rollout(
        _dag(), budget=RolloutBudget(rollout_depth=2, max_triggers=1,
                                     max_completion_calls=2, total_time_limit_s=None,
                                     per_decision_time_limit_s=None)
    )
    assert depth2.completion_calls == depth1.completion_calls == 2
    assert depth2.expanded_nodes >= depth1.expanded_nodes
    assert_preemptive_trace(PreemptiveDAGModel(_dag()), depth2.trace)


def test_depth_two_respects_completion_budget_and_falls_back_to_lt():
    baseline = schedule_longest_tail(_dag())
    result = schedule_selective_rollout(
        _dag(), budget=RolloutBudget(rollout_depth=2, max_triggers=1,
                                     max_completion_calls=1, total_time_limit_s=None,
                                     per_decision_time_limit_s=None)
    )
    assert result.makespan == baseline.makespan
    assert result.fallback_count >= 1
    assert "completion_call_limit" in result.fallback_reasons
    assert_preemptive_trace(PreemptiveDAGModel(_dag()), result.trace)
