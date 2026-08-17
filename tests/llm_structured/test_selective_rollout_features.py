from llm_structured.selective_rollout import (
    RolloutBudget,
    TriggerFeatures,
    choice_only,
    last_missing_and_small_margin,
    small_lt_margin,
)


def _features(**changes):
    values = dict(
        feature_version="v1", eligible_count=2, action_count=2, lt_action="a",
        challenger_action="b", lt_tail=10, second_tail=9, tail_margin=1,
        normalized_tail_margin=0.1, heuristic_disagreement=True,
        active_communication_remaining=0, ready_set_delta=1,
        immediate_compute_release=True, last_missing_join=True,
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
        _features(last_missing_join=False)
    ).triggered
