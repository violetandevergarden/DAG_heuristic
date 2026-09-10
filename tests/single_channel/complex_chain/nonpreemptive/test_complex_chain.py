from __future__ import annotations

import random

from core.trace.nonpree_single import assert_nonpreemptive_trace
from core.oracle import exact_oracle
from benchmark_generate.cases import combined_chain_probes, random_join_dag
from single_channel.complex_chain.nonpreemptive.solver import (
    ResidualGeneralDAG,
    beam_search,
    schedule_priority,
    schedule_rollout,
)


def test_complex_chain_methods_replay_as_nonpreemptive_traces() -> None:
    dag = random_join_dag(random.Random(17), 0)
    schedules = (
        schedule_priority(dag),
        schedule_priority(dag, "raw_join"),
        schedule_rollout(dag, top_k=2, allow_wait=True),
        schedule_rollout(
            dag,
            top_k=2,
            allow_wait=True,
            candidate_mode="hybrid",
            depth=2,
        ),
        beam_search(dag, width=8),
    )
    for schedule in schedules:
        assert_nonpreemptive_trace(dag, schedule.trace, mode="optional_idle")


def test_rollout_and_beam_keep_dynamic_incumbent() -> None:
    rng = random.Random(260817)
    for index in range(8):
        dag = random_join_dag(rng, index)
        dynamic = schedule_priority(dag).makespan
        assert schedule_rollout(
            dag, top_k=2, allow_wait=True, candidate_mode="hybrid"
        ).makespan <= dynamic
        assert beam_search(dag, width=8).makespan <= dynamic


def test_raw_join_bonus_can_hurt_under_whole_flow_execution() -> None:
    rng = random.Random(260817)
    random_join_dag(rng, 0)
    dag = random_join_dag(rng, 1)
    assert schedule_priority(dag).makespan == 37
    assert schedule_priority(dag, "raw_join").makespan == 38


def test_combined_probes_have_both_regrets_and_depth_two_improves() -> None:
    for dag in combined_chain_probes():
        optimum = exact_oracle(dag, mode="optional_idle").makespan
        work_conserving = exact_oracle(dag, mode="work_conserving").makespan
        dynamic = schedule_priority(dag).makespan
        enhanced = schedule_rollout(
            dag,
            top_k=2,
            allow_wait=True,
            candidate_mode="hybrid",
            depth=2,
        ).makespan
        assert dynamic > work_conserving > optimum
        assert enhanced < dynamic


def test_candidate_generation_separates_sources_from_evaluation() -> None:
    dag = random_join_dag(random.Random(260817), 0)
    graph = ResidualGeneralDAG(dag)
    state = graph.model.initial_state()
    dynamic = graph.candidates(
        state, top_k=1, mode="dynamic", allow_wait=False
    )
    hybrid = graph.candidates(
        state, top_k=1, mode="hybrid", allow_wait=True
    )
    assert dynamic[0] in hybrid
    assert set(hybrid).issubset(set(graph.model.legal_actions(state)))


def test_random_join_30_and_40_keep_revised_exact_values() -> None:
    rng = random.Random(260817)
    selected = {}
    for index in range(41):
        dag = random_join_dag(rng, index)
        if index in {30, 40}:
            selected[index] = dag
    assert exact_oracle(selected[30], mode="optional_idle").makespan == 22
    assert exact_oracle(selected[40], mode="optional_idle").makespan == 21
