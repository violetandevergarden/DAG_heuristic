from __future__ import annotations

from benchmark_generate.llm.barrier_motifs import multi_resource_motifs
from core.execution.multi_resource import MultiResourceAction, PreemptiveMultiResourceModel
from llm_structured.barrier import action_features, build_context, feature_snapshot
from muti_channel.preemptive.solver import (
    offline_best_of_lt_and_barrier,
    schedule_pack,
    schedule_selective_barrier_rollout,
    schedule_set_policy,
)


def test_multi_barrier_motif_uses_maximal_actions_and_union_features() -> None:
    motif = multi_resource_motifs()[0]
    model = PreemptiveMultiResourceModel(motif.dag, motif.resources or {})
    scripted = model.step(model.initial_state(), MultiResourceAction(("R", "side")))
    assert {"R", "N", "side"} <= set(model.eligible(scripted))
    actions = model.maximal_actions(scripted)
    assert actions
    context = build_context(model, scripted)
    assert feature_snapshot(context, "N").direct_last_missing_join_count == 1
    assert all(
        action_features(context, action.communications).shared_downstream_count >= 0
        for action in actions
    )
    assert schedule_set_policy(motif.dag, motif.resources or {}, "barrier_union").makespan >= 0


def test_multi_barrier_offline_upper_bound_is_explicitly_not_online() -> None:
    for motif in multi_resource_motifs():
        baseline = schedule_pack(motif.dag, motif.resources or {}, "longest_tail")
        candidate = schedule_set_policy(
            motif.dag, motif.resources or {}, "barrier_union"
        )
        offline = offline_best_of_lt_and_barrier(motif.dag, motif.resources or {})
        assert offline.online is False
        assert offline.full_schedule_runs == 2
        assert offline.baseline.makespan == baseline.makespan
        assert offline.candidate.makespan == candidate.makespan


def test_multi_selective_rollout_is_an_online_lt_enhancement() -> None:
    for motif in multi_resource_motifs():
        resources = motif.resources or {}
        baseline = schedule_pack(motif.dag, resources, "longest_tail")
        result = schedule_selective_barrier_rollout(
            motif.dag, resources, max_triggers=8, time_limit_s=None
        )
        assert result.makespan <= baseline.makespan
        assert result.completion_calls == result.planner_triggered * 2
        assert result.planner_improvements <= result.planner_triggered
