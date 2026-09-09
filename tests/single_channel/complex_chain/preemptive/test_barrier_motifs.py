from __future__ import annotations

from benchmark_generate.llm.preemptive.barrier_motifs import single_channel_motifs
from core.execution.preemptive import Action, PreeSingleModel
from core.oracle.pree_single import exact_oracle
from core.trace.pree_single import assert_preemptive_trace
from llm_structured.barrier import build_context, feature_snapshot
from llm_structured.preemptive.barrier import (
    offline_best_of_lt_and_barrier,
    schedule_barrier_margin_tiebreak,
    schedule_barrier_policy,
    schedule_barrier_prescreen,
    schedule_selective_barrier_rollout,
)
from single_channel.complex_chain.preemptive.solver import schedule_longest_tail


def test_controlled_barrier_motifs_have_scripted_competition_and_exact_labels() -> None:
    for motif in single_channel_motifs():
        model = PreeSingleModel(motif.dag)
        scripted = model.step(model.initial_state(), Action.run("R")).after
        assert {"R", "N"} <= set(model.eligible_communications(scripted))
        assert feature_snapshot(build_context(model, scripted), "N").task_id == "N"
        result = exact_oracle(motif.dag, max_states=100_000, time_limit_s=2.0)
        assert result.status == "optimal"
        assert_preemptive_trace(motif.dag, result.trace)


def test_offline_barrier_upper_bound_is_explicitly_not_online() -> None:
    for motif in single_channel_motifs():
        baseline = schedule_longest_tail(motif.dag)
        candidate = schedule_barrier_policy(
            motif.dag, "tail_barrier", trigger="barrier_or_unlock"
        )
        offline = offline_best_of_lt_and_barrier(motif.dag)
        assert offline.online is False
        assert offline.full_schedule_runs == 2
        assert offline.baseline.makespan == baseline.makespan
        assert offline.candidate.makespan == candidate.makespan


def test_margin_tiebreak_remains_an_online_trace_when_barrier_candidate_loses() -> None:
    motif = next(
        item
        for item in single_channel_motifs()
        if item.name == "barrier_B5_R_longer_tail"
    )
    baseline = schedule_longest_tail(motif.dag)
    result = schedule_barrier_margin_tiebreak(motif.dag)
    assert result.makespan == baseline.makespan
    assert tuple(item.action for item in result.trace.transitions) == tuple(
        item.action for item in baseline.trace.transitions
    )
    assert_preemptive_trace(motif.dag, result.trace)


def test_direct_only_prescreen_is_a_safe_lt_equivalent() -> None:
    for motif in single_channel_motifs():
        baseline = schedule_longest_tail(motif.dag)
        result = schedule_barrier_prescreen(motif.dag)
        assert tuple(item.action for item in result.trace.transitions) == tuple(
            item.action for item in baseline.trace.transitions
        )


def test_selective_rollout_is_an_online_lt_enhancement_on_motifs() -> None:
    for motif in single_channel_motifs():
        baseline = schedule_longest_tail(motif.dag)
        result = schedule_selective_barrier_rollout(
            motif.dag, max_triggers=8, time_limit_s=None
        )
        assert result.makespan <= baseline.makespan
        assert result.completion_calls == result.planner_triggered * 2
        assert result.planner_improvements <= result.planner_triggered
        assert_preemptive_trace(motif.dag, result.trace)
