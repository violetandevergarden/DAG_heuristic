from time import perf_counter

from llm_structured.preemptive.selective_rollout.contracts import (
    BudgetAccount, RolloutBudget, TriggerFeatures, choice_only,
    last_missing_and_small_margin, small_lt_margin,
)


def _features(**changes):
    values = dict(
        feature_version="v2", eligible_count=2, action_count=2,
        lt_action="a", challenger_action="b", lrpt_action="b", fifo_action="a",
        lt_tail=10, second_tail=9, tail_margin=1,
        normalized_tail_margin=0.1, heuristic_disagreement=True,
        active_communication_remaining=0, eligible_comm_delta=1,
        baseline_compute_release=0, challenger_compute_release=3,
        compute_release_delta=3, baseline_last_missing_join=False,
        challenger_last_missing_join=True, last_missing_join_difference=True,
    )
    values.update(changes)
    return TriggerFeatures(**values)


def test_budget_rejects_negative_limits():
    try:
        RolloutBudget(max_triggers=-1)
    except ValueError as error:
        assert "max_triggers" in str(error)
    else:
        raise AssertionError("negative budget accepted")


def test_registered_triggers_are_pure_and_stable():
    features = _features()
    assert choice_only(features).reason == "choice_state"
    assert small_lt_margin(0.1)(features).triggered
    assert not small_lt_margin(0.09)(features).triggered
    assert last_missing_and_small_margin(0.1)(features).triggered
    assert not last_missing_and_small_margin(0.1)(
        _features(last_missing_join_difference=False)
    ).triggered


def test_budget_reservations_never_cross_hard_counts():
    started = perf_counter()
    account = BudgetAccount(RolloutBudget(
        max_completion_calls=1, max_expansions=2,
        per_decision_time_limit_s=None, total_time_limit_s=None,
    ))
    assert account.try_reserve_completion(started) is None
    assert account.try_reserve_completion(started) == "completion_call_limit"
    assert account.completion_calls == 1
    assert account.try_expand(started, 2) is None
    assert account.try_expand(started) == "expansion_limit"
    assert account.expansions == 2
