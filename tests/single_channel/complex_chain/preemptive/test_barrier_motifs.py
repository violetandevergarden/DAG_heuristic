from __future__ import annotations

from benchmark_generate.llm.barrier_motifs import single_channel_motifs
from core.execution.preemptive import Action, PreemptiveDAGModel
from core.trace.preemptive import assert_preemptive_trace
from llm_structured.barrier import build_context, feature_snapshot
from single_channel.complex_chain.preemptive.solver import (
    exact_oracle,
    schedule_barrier_policy,
    schedule_barrier_safeguarded,
    schedule_longest_tail,
    schedule_selective_barrier_rollout,
)


def test_controlled_barrier_motifs_have_scripted_competition_and_exact_labels() -> None:
    for motif in single_channel_motifs():
        model = PreemptiveDAGModel(motif.dag)
        scripted = model.step(model.initial_state(), Action.run("R")).after
        assert {"R", "N"} <= set(model.eligible_communications(scripted))
        assert feature_snapshot(build_context(model, scripted), "N").task_id == "N"
        result = exact_oracle(motif.dag, max_states=100_000, time_limit_s=2.0)
        assert result.status == "optimal"
        assert_preemptive_trace(motif.dag, result.trace)


def test_barrier_safeguard_never_worsens_longest_tail_on_all_controlled_motifs() -> None:
    for motif in single_channel_motifs():
        baseline = schedule_longest_tail(motif.dag)
        candidate = schedule_barrier_policy(
            motif.dag, "tail_barrier", trigger="barrier_or_unlock"
        )
        safeguarded = schedule_barrier_safeguarded(motif.dag)
        assert safeguarded.makespan <= baseline.makespan
        assert safeguarded.makespan == min(baseline.makespan, candidate.makespan)
        assert_preemptive_trace(motif.dag, safeguarded.trace)


def test_barrier_safeguard_preserves_the_lt_incumbent_when_candidate_loses() -> None:
    motif = next(
        item
        for item in single_channel_motifs()
        if item.name == "barrier_B5_R_longer_tail"
    )
    baseline = schedule_longest_tail(motif.dag)
    safeguarded = schedule_barrier_safeguarded(motif.dag)
    assert safeguarded.makespan == baseline.makespan
    assert safeguarded.fallback_count == 1
    assert "complete_candidate_not_better_than_longest_tail" in safeguarded.fallback_reasons


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
