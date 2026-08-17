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
