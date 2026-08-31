from __future__ import annotations

from pathlib import Path

from benchmark import load_benchmark
from llm_structured.nonpreemptive.selective_rollout import RolloutConfig, schedule
from llm_structured.nonpreemptive.selective_rollout.contracts import ActionSignature
from llm_structured.nonpreemptive.selective_rollout.adapters import make_adapter
from llm_structured.nonpreemptive.selective_rollout.baseline import longest_tail_action
from llm_structured.nonpreemptive.selective_rollout.candidates import generate
from llm_structured.nonpreemptive.selective_rollout.exact import cost_to_go


ROOT = Path(__file__).resolve().parents[3]


def _single():
    return load_benchmark(ROOT / "benchmark/single_channel/complex_chain/nonpreemptive/adversarial/longest_tail_counterexample.json")


def _multi(name="active_reservation_np.json"):
    return load_benchmark(ROOT / f"benchmark/muti_channel/nonpreemptive/adversarial/{name}")


def test_depth_zero_is_frozen_longest_tail_and_replays() -> None:
    result = schedule(_single(), RolloutConfig(search_depth=0, trigger="none"))
    assert result.status == "completed"
    assert result.trace_valid
    assert result.metrics["completion_calls"] == 0
    assert all(item["fallback_reason"] == "rollout_disabled" for item in result.decisions)


def test_width_and_budget_are_real_limits() -> None:
    result = schedule(
        _single(),
        RolloutConfig(trigger="full", max_candidates_per_decision=2, max_completion_calls=1),
    )
    assert result.trace_valid
    assert result.metrics["completion_calls"] <= 1
    assert result.metrics["fallback_decisions"] >= 1
    assert all(len(item["evaluated"]) <= 2 for item in result.decisions)


def test_work_conserving_never_selects_wait_when_start_exists() -> None:
    result = schedule(_single(), RolloutConfig(mode="work_conserving", trigger="full"))
    for decision in result.decisions:
        if any(item["kind"] == "flow" for item in decision["generated"]):
            assert decision["selected"]["kind"] != "wait"


def test_multi_resource_candidates_keep_active_reservation() -> None:
    adapter = make_adapter(_multi())
    state = adapter.initial_state()
    first = next(action for action in adapter.legal_actions(state, "optional_idle") if len(action.starts) > 1)
    state = adapter.step(state, first).after
    active_before = set(adapter.model.active_flows(state))
    candidates, _count, _truncated = generate(adapter, state, "optional_idle", 4)
    assert active_before
    for action in candidates:
        if action.kind == "start":
            assert not active_before.intersection(action.starts)
            assert adapter.model.compatible(state, action.starts)


def test_ties_keep_longest_tail_action() -> None:
    adapter = make_adapter(_multi("nonmaximal_start_np.json"))
    state = adapter.initial_state()
    baseline = longest_tail_action(adapter, state, "optional_idle")
    result = schedule(
        _multi("nonmaximal_start_np.json"),
        RolloutConfig(mode="optional_idle", trigger="full", search_depth=2, max_candidates_per_decision=4),
    )
    # The motif has a strict optional-idle improvement, so depth two may
    # deliberately differ from LT; the baseline is nevertheless evaluated.
    assert adapter.signature(state, baseline) in tuple(
        ActionSignature(**item) for item in result.decisions[0]["evaluated"]
    )
    assert result.metrics["expanded_decision_states"] > 0


def test_random_trigger_is_reproducible() -> None:
    config = RolloutConfig(trigger="random", random_seed=17, random_probability=0.5)
    left, right = schedule(_single(), config), schedule(_single(), config)
    assert left.actions == right.actions
    assert [x["trigger"] for x in left.decisions] == [x["trigger"] for x in right.decisions]


def test_cost_to_go_accepts_simulator_residual_state() -> None:
    adapter = make_adapter(_multi("nonmaximal_start_np.json"))
    initial = adapter.initial_state()
    result = cost_to_go(adapter, initial, "optional_idle")
    assert result.status == "optimal"
    assert result.cost == 8
    transition = adapter.step(initial, result.optimal_actions[0])
    suffix = cost_to_go(adapter, transition.after, "optional_idle")
    assert suffix.status == "optimal"
    assert transition.after.time - initial.time + suffix.cost == result.cost
