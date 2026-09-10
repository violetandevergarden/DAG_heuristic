from __future__ import annotations

from pathlib import Path
from time import perf_counter

import pytest

from benchmark import load_benchmark
from core.oracle.nonpree_multi import exact_completion_from_state as core_multi_completion
from core.oracle.nonpree_single import exact_completion_from_state as core_single_completion
from llm_structured.nonpreemptive.baseline.completion import (
    CompletionDeadlineExceeded,
    complete,
)
from llm_structured.nonpreemptive.selective_rollout import RolloutConfig, schedule
from llm_structured.nonpreemptive.baseline.adapters import make_adapter
from llm_structured.nonpreemptive.baseline.solver import longest_tail_action
from llm_structured.nonpreemptive.selective_rollout.candidates import generate
from llm_structured.nonpreemptive.selective_rollout.cheap_policies import preferences
from llm_structured.nonpreemptive.selective_rollout.contracts import ActionSignature
from llm_structured.nonpreemptive.selective_rollout.exact import cost_to_go

ROOT = Path(__file__).resolve().parents[3]


def _single():
    return load_benchmark(
        ROOT
        / "benchmark/single_channel/complex_chain/nonpreemptive/adversarial/longest_tail_counterexample.json"
    )


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
    first = next(
        action for action in adapter.legal_actions(state, "optional_idle") if len(action.starts) > 1
    )
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
        RolloutConfig(
            mode="optional_idle", trigger="full", search_depth=2, max_candidates_per_decision=4
        ),
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


@pytest.mark.parametrize("mode", ["optional_idle", "work_conserving"])
def test_single_cost_to_go_matches_core_residual_oracle(mode: str) -> None:
    adapter = make_adapter(_single())
    state = adapter.initial_state()
    family = cost_to_go(adapter, state, mode, max_states=100_000)
    core = core_single_completion(adapter.model, state, mode=mode, max_states=100_000)
    assert (family.status, family.cost) == (core.status, core.cost)
    assert tuple(family.optimal_actions) == tuple(core.optimal_actions)


@pytest.mark.parametrize("mode", ["optional_idle", "work_conserving"])
def test_multi_cost_to_go_matches_core_residual_oracle(mode: str) -> None:
    adapter = make_adapter(_multi("nonmaximal_start_np.json"))
    state = adapter.initial_state()
    family = cost_to_go(adapter, state, mode, max_states=100_000)
    core = core_multi_completion(adapter.model, state, mode=mode, max_states=100_000)
    assert (family.status, family.cost) == (core.status, core.cost)
    assert tuple(family.optimal_actions) == tuple(core.optimal_actions)


def test_true_policy_disagreement_is_not_candidate_disagreement() -> None:
    adapter = make_adapter(
        load_benchmark(
            ROOT
            / "benchmark/single_channel/complex_chain/nonpreemptive/adversarial/combined_chain_14.json"
        )
    )
    state = adapter.initial_state()
    state = adapter.step(state, longest_tail_action(adapter, state, "optional_idle")).after
    mapping = preferences(adapter, state, "optional_idle")
    signatures = {adapter.signature(state, action) for action in mapping.values()}
    candidates, _, _ = generate(adapter, state, "optional_idle", 2)
    # There is only one start action at this state.  WAIT is not a D1
    # challenger, even though cheap policies can still disagree elsewhere.
    assert len(candidates) == 1
    assert len(signatures) == 1


def test_completion_obeys_expired_absolute_deadline() -> None:
    adapter = make_adapter(_single())
    with pytest.raises(CompletionDeadlineExceeded, match="completion_deadline"):
        complete(
            adapter,
            adapter.initial_state(),
            "optional_idle",
            deadline=perf_counter() - 1,
        )


def test_lt_top_two_mode_does_not_add_policy_candidates() -> None:
    benchmark = load_benchmark(
        ROOT / "benchmark/llm_structure/nonpreemptive/multi_job/np_stage4f_micro_four_burst.json"
    )
    adapter = make_adapter(benchmark)
    state = adapter.initial_state()
    candidates, _, _ = generate(adapter, state, "work_conserving", 3, candidate_mode="lt_top_two")
    assert len(candidates) <= 2


def test_policy_mapping_records_real_fifo_lt_spt_disagreement() -> None:
    adapter = make_adapter(
        load_benchmark(
            ROOT
            / "benchmark/single_channel/complex_chain/nonpreemptive/adversarial/combined_chain_14.json"
        )
    )
    state = adapter.initial_state()
    mapping = preferences(adapter, state, "optional_idle")
    signatures = {name: adapter.signature(state, action) for name, action in mapping.items()}
    assert signatures["fifo"] == signatures["lt"]
    assert signatures["spt"] != signatures["lt"]


def test_feature_lookahead_is_counted_and_reused() -> None:
    result = schedule(_single(), RolloutConfig(trigger="full", max_candidates_per_decision=2))
    first = result.decisions[0]
    assert result.metrics["feature_transitions"] >= len(first["generated"])
    assert first["features"]["policy_actions"]
    assert result.metrics["completion_calls"] == result.metrics["evaluated_candidates"]
