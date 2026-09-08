"""R2 non-preemptive parallel-chain regression tests."""

import random

from core.oracle import exact_oracle
from single_channel.parallel_chain.nonpreemptive.compact_exact_reference import (
    advance as compact_advance,
    binary_search_exact,
    exact_dp,
    legal_actions as compact_legal_actions,
)
from single_channel.parallel_chain.nonpreemptive.solver import (
    ParallelChain,
    _chain_action_from_public,
    _public_action,
    _public_projection,
    beam_search,
    monte_carlo_best,
    schedule_priority,
    schedule_rollout,
    to_benchmark_dag,
    verify_schedule,
)
from core.execution.nonpreemptive import NonPreeSingleModel
from benchmark_generate.cases import (
    fixed_beam_counterexample,
    random_parallel_chains,
    scaled_five_four_family,
    tight_optional_wait_family,
)


def test_compact_dp_matches_r1_dag_oracle_in_both_idle_modes() -> None:
    rng = random.Random(260813)
    for _ in range(12):
        chains = random_parallel_chains(rng)
        dag, _flow_ids = to_benchmark_dag(chains)
        for optional_idle, mode in (
            (True, "optional_idle"),
            (False, "work_conserving"),
        ):
            compact = exact_dp(chains, optional_idle=optional_idle)
            general = exact_oracle(dag, mode=mode)
            assert compact.makespan == general.makespan


def test_compact_exact_transition_matches_public_model_at_every_reachable_state() -> None:
    chains = (
        ParallelChain((2, 1), (3, 2), initial_delay=1),
        ParallelChain((1, 3), (2, 1)),
    )
    dag, flow_ids = to_benchmark_dag(chains)
    model = NonPreeSingleModel(dag)

    for optional_idle in (False, True):
        stack = [model.initial_state()]
        seen = set()
        while stack:
            public_state = stack.pop()
            if public_state in seen:
                continue
            seen.add(public_state)
            compact_state = _public_projection(
                chains, model, public_state, flow_ids
            )
            compact_actions = set(
                compact_legal_actions(
                    chains, compact_state, optional_idle=optional_idle
                )
            )
            public_actions = model.legal_actions(public_state)
            if not optional_idle and model.ready_flows(public_state):
                public_actions = tuple(
                    action for action in public_actions if action.kind != "wait"
                )
            projected_actions = {
                _chain_action_from_public(
                    chains, model, public_state, action, flow_ids
                )
                for action in public_actions
            }
            assert compact_actions == projected_actions

            for action in compact_actions:
                compact_successor, compact_duration = compact_advance(
                    chains, compact_state, action
                )
                transition = model.step(
                    public_state,
                    _public_action(action, chains, model, public_state, flow_ids),
                )
                assert transition.after.time - public_state.time == compact_duration
                assert _public_projection(
                    chains, model, transition.after, flow_ids
                ) == compact_successor
                stack.append(transition.after)


def test_binary_feasibility_matches_direct_operation_dp() -> None:
    rng = random.Random(19)
    for _ in range(8):
        chains = random_parallel_chains(rng, max_chains=4)
        for optional_idle in (False, True):
            direct = exact_dp(chains, optional_idle=optional_idle)
            binary = binary_search_exact(chains, optional_idle=optional_idle)
            assert binary.makespan == direct.makespan


def test_optional_wait_family_makes_dynamic_tail_tight_at_two() -> None:
    for magnitude in (10, 100):
        chains = tight_optional_wait_family(magnitude)
        optimum = exact_dp(chains, optional_idle=True)
        work_conserving = schedule_priority(chains, "dynamic_tail")
        rollout = schedule_rollout(chains, top_k=2, allow_wait=True)

        assert optimum.makespan == magnitude + 2
        assert work_conserving.makespan == 2 * magnitude + 1
        assert rollout.makespan == optimum.makespan
        verify_schedule(chains, work_conserving)
        verify_schedule(chains, rollout)


def test_scaled_five_four_ordering_counterexample_survives() -> None:
    for scale in (2, 4, 8):
        chains = scaled_five_four_family(scale)
        optimum = exact_dp(chains, optional_idle=True)
        dynamic = schedule_priority(chains, "dynamic_tail")

        assert optimum.makespan == 8 * scale + 1
        assert dynamic.makespan == 10 * scale
        verify_schedule(chains, dynamic)


def test_wait_rollout_never_worsens_flow_only_rollout_on_fixed_sample() -> None:
    rng = random.Random(260813)
    for _ in range(30):
        chains = random_parallel_chains(rng)
        flow_only = schedule_rollout(chains, top_k=2, allow_wait=False)
        wait_aware = schedule_rollout(chains, top_k=2, allow_wait=True)
        assert wait_aware.makespan <= flow_only.makespan
        verify_schedule(chains, wait_aware)


def test_bounded_monte_carlo_keeps_dynamic_incumbent_and_is_atomic() -> None:
    chains = (
        ParallelChain((2, 1), (3, 1)),
        ParallelChain((1, 2), (2, 1)),
    )
    dynamic = schedule_priority(chains, "dynamic_tail")
    sampled = monte_carlo_best(chains, samples=32, seed=7, allow_wait=True)

    assert sampled.makespan <= dynamic.makespan
    verify_schedule(chains, sampled)


def test_fixed_width_beams_are_not_exact_under_whole_flow_actions() -> None:
    chains = fixed_beam_counterexample()
    optimum = exact_dp(chains, optional_idle=True)
    beam8 = beam_search(chains, width=8, allow_wait=True)
    beam32 = beam_search(chains, width=32, allow_wait=True)

    assert optimum.makespan == 46
    assert beam8.makespan == 47
    assert beam32.makespan == 47
    verify_schedule(chains, beam8)
    verify_schedule(chains, beam32)


def test_one_flow_initially_ready_dynamic_tail_is_optimal() -> None:
    rng = random.Random(23)
    for _ in range(20):
        chains = tuple(
            ParallelChain((rng.randint(1, 8),), (rng.randint(0, 12),))
            for _ in range(rng.randint(2, 7))
        )
        optimum = exact_dp(chains, optional_idle=True)
        dynamic = schedule_priority(chains, "dynamic_tail")
        assert dynamic.makespan == optimum.makespan


def test_every_work_conserving_priority_respects_p_plus_q_bound() -> None:
    rng = random.Random(29)
    for _ in range(30):
        chains = random_parallel_chains(rng)
        total_communication = sum(sum(chain.comm) for chain in chains)
        max_compute = max(sum(chain.compute) for chain in chains)
        optimum = exact_dp(chains, optional_idle=True).makespan
        for policy in ("fifo", "spt", "lpt", "dynamic_tail", "tictac"):
            schedule = schedule_priority(chains, policy)
            assert schedule.makespan <= total_communication + max_compute
            assert schedule.makespan <= 2 * optimum
            assert schedule.preemptions == 0


def test_bounded_searches_fall_back_to_dynamic_incumbent() -> None:
    chains = fixed_beam_counterexample()
    dynamic = schedule_priority(chains, "dynamic_tail")
    rollout = schedule_rollout(
        chains, top_k=2, allow_wait=True, time_limit_s=-1
    )
    beam = beam_search(
        chains, width=8, allow_wait=True, state_budget=0
    )

    assert rollout.fallback is True
    assert beam.fallback is True
    assert rollout.makespan == dynamic.makespan
    assert beam.makespan == dynamic.makespan
    verify_schedule(chains, rollout)
    verify_schedule(chains, beam)
