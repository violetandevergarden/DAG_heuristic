from time import perf_counter

from core.dag import Task, DAG
from core.execution.preemptive import Action, PreeSingleModel
from core.oracle.pree_single import exact_completion_from_state_uncompressed
from core.trace.pree_single import assert_preemptive_trace
from llm_structured.selective_rollout import (
    BudgetAccount, CandidateSummary, RolloutBudget,
)
from llm_structured.preemptive.selective_rollout import (
    cheap_features, evaluate_rollout, feature_cache_key, generate_candidates,
    schedule_selective_rollout, summarize_choice,
)
from single_channel.complex_chain.preemptive.solver import schedule_longest_tail


def _dag():
    return DAG('selective', (Task('a', 'comm', 4), Task('a_tail', 'compute', 7, ('a',)), Task('b', 'comm', 1), Task('b_tail', 'compute', 2, ('b',))), context=(('category', 'adversarial'),))


def _actions(result):
    return [transition.action for transition in result.trace.transitions]


def test_choice_gate_and_features_use_residual_state():
    model = PreeSingleModel(_dag())
    state = model.initial_state()
    assert summarize_choice(model, state).kind == "candidate_choice"
    features = cheap_features(model, state)
    assert features.eligible_count == 2
    assert features.feature_version == "single-channel-selective-v2"
    assert not features.heuristic_disagreement  # LT and LRPT really choose a.


def test_candidate_width_zero_one_two_and_four_is_real():
    dag = DAG('width', tuple((Task(name, 'comm', duration) for name, duration in (('a', 4), ('b', 3), ('c', 2), ('d', 1)))), context=(('category', 'adversarial'),))
    model = PreeSingleModel(dag)
    state = model.initial_state()
    assert generate_candidates(model, state, 0).retained_count == 0
    assert generate_candidates(model, state, 1).retained_count == 1
    assert generate_candidates(model, state, 2).retained_count == 2
    assert generate_candidates(model, state, 4).retained_count == 4


def test_depth_zero_and_width_one_are_exact_lt_without_completion():
    baseline = schedule_longest_tail(_dag())
    for budget in (
        RolloutBudget(search_depth=0),
        RolloutBudget(max_candidates=1),
        RolloutBudget(max_candidates=0),
    ):
        result = schedule_selective_rollout(_dag(), budget=budget)
        assert result.completion_calls == 0
        assert _actions(result) == _actions(baseline)


def test_zero_trigger_and_zero_completion_budget_are_exact_lt_fallbacks():
    baseline = schedule_longest_tail(_dag())
    for budget in (
        RolloutBudget(max_triggers=0),
        RolloutBudget(max_completion_calls=0),
    ):
        result = schedule_selective_rollout(_dag(), budget=budget)
        assert result.makespan == baseline.makespan
        assert _actions(result) == _actions(baseline)
        assert_preemptive_trace(PreeSingleModel(_dag()), result.trace)


def test_depth_two_branches_and_records_real_depth():
    depth1 = schedule_selective_rollout(
        _dag(), budget=RolloutBudget(
            search_depth=1, max_triggers=1, max_completion_calls=8,
            max_expansions=100, total_time_limit_s=None,
            per_decision_time_limit_s=None,
        )
    )
    depth2 = schedule_selective_rollout(
        _dag(), budget=RolloutBudget(
            search_depth=2, max_triggers=1, max_completion_calls=8,
            max_expansions=100, total_time_limit_s=None,
            per_decision_time_limit_s=None,
        )
    )
    assert depth1.max_actual_depth == 1
    assert depth2.max_actual_depth == 2
    assert depth2.expanded_nodes >= depth1.expanded_nodes
    assert_preemptive_trace(PreeSingleModel(_dag()), depth2.trace)


def test_expansion_limit_never_overruns_and_fallback_trace_matches_lt():
    baseline = schedule_longest_tail(_dag())
    result = schedule_selective_rollout(
        _dag(), budget=RolloutBudget(
            search_depth=2, max_triggers=1, max_completion_calls=20,
            max_expansions=1, total_time_limit_s=None,
            per_decision_time_limit_s=None,
        )
    )
    assert result.expanded_nodes <= 1
    assert "expansion_limit" in result.fallback_reasons
    assert _actions(result) == _actions(baseline)


def test_third_candidate_cannot_pollute_compared_release_features():
    dag = DAG('pollution', (Task('a', 'comm', 3), Task('b', 'comm', 2), Task('c', 'comm', 1), Task('c_tail', 'compute', 5, ('c',))), context=(('category', 'adversarial'),))
    model = PreeSingleModel(dag)
    state = model.initial_state()
    candidates = CandidateSummary(
        "a", ("a", "b"), (("a", ("test",)), ("b", ("test",))),
        3, 2, True, "candidate_limit",
    )
    features = cheap_features(model, state, candidates=candidates)
    assert features.baseline_compute_release == 0
    assert features.challenger_compute_release == 0
    assert features.compute_release_delta == 0


def test_cache_key_isolates_previous_eligible_history():
    state = PreeSingleModel(_dag()).initial_state()
    assert feature_cache_key(state, {"a"}) != feature_cache_key(state, {"b"})


def test_equal_candidate_values_keep_lt_stably():
    dag = DAG('tie', (Task('a', 'comm', 1), Task('b', 'comm', 1)), context=(('category', 'adversarial'),))
    model = PreeSingleModel(dag)
    state = model.initial_state()
    candidates = CandidateSummary(
        "a", ("a", "b"), (("a", ("lt",)), ("b", ("fifo",))),
        2, 2, False, None,
    )
    account = BudgetAccount(RolloutBudget(
        max_candidates=2, max_completion_calls=2, max_expansions=20,
        per_decision_time_limit_s=None, total_time_limit_s=None,
    ))
    outcome = evaluate_rollout(
        model, state, candidates, account, decision_started=perf_counter()
    )
    assert outcome.complete
    assert outcome.selected_action == "a"
    assert not outcome.improved


def test_forced_idle_wait_is_never_selected_when_communication_is_eligible():
    result = schedule_selective_rollout(_dag())
    for transition in result.trace.transitions:
        if transition.action == Action.wait():
            assert not PreeSingleModel(_dag()).eligible_communications(transition.before)


def test_every_first_action_gets_an_uncompressed_exact_suffix_value():
    model = PreeSingleModel(_dag())
    state = model.initial_state()
    values = {}
    for action in model.legal_actions(state):
        result = exact_completion_from_state_uncompressed(
            model, model.step(state, action).after,
            max_states=100_000, time_limit_s=2,
        )
        assert result.status == "optimal"
        values[action.task_id] = result.makespan
    assert set(values) == {"a", "b"}
