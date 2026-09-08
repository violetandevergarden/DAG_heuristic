"""Exact-oracle regressions for the revised non-preemptive model."""

import random

from core.dag import (
    DAG,
    Task,
)
from benchmark_generate.cases import complex_adversarial_cases, llm_motif_cases
from core.trace.nonpreemptive import assert_nonpreemptive_trace
from core.oracle import (
    branch_and_bound_oracle,
    compare_oracles,
    exact_oracle,
)
from benchmark_generate.cases import random_join_dag


def _waiting_counterexample(magnitude: int = 10) -> DAG:
    return DAG('waiting_is_necessary', (Task('release_b', 'compute', 1), Task('A', 'comm', magnitude), Task('B', 'comm', 1, ('release_b',)), Task('tail_b', 'compute', magnitude, ('B',))), context=(('category', 'r1_oracle'),))


def test_optional_idle_and_work_conserving_values_are_separated() -> None:
    dag = _waiting_counterexample(10)
    comparison = compare_oracles(dag)

    assert comparison.optional_idle.makespan == 12
    assert comparison.work_conserving.makespan == 21
    assert comparison.idle_regret == 9
    assert comparison.optional_idle.voluntary_waits == 1
    assert comparison.optional_idle.voluntary_wait_time == 1
    assert comparison.work_conserving.voluntary_waits == 0
    assert comparison.optional_idle.actions[0].kind == "wait"
    assert_nonpreemptive_trace(dag, comparison.optional_idle.trace, mode="optional_idle")
    assert_nonpreemptive_trace(dag, comparison.work_conserving.trace, mode="work_conserving")


def test_memoized_dp_and_branch_and_bound_agree_on_catalog() -> None:
    catalog = [*complex_adversarial_cases(), *llm_motif_cases()]

    for dag in catalog:
        for mode in ("optional_idle", "work_conserving"):
            dynamic_programming = exact_oracle(dag, mode=mode)
            branch_and_bound = branch_and_bound_oracle(dag, mode=mode)
            assert branch_and_bound.makespan == dynamic_programming.makespan
            assert dynamic_programming.lower_bounds["combined"] <= (
                dynamic_programming.makespan
            )
            assert_nonpreemptive_trace(dag, dynamic_programming.trace, mode=mode)
            assert_nonpreemptive_trace(dag, branch_and_bound.trace, mode=mode)


def test_group_meeting_counterexample_remains_eight_nonpreemptively() -> None:
    dag = next(
        item
        for item in complex_adversarial_cases()
        if item.name == "longest_tail_counterexample"
    )

    assert exact_oracle(dag).makespan == 8
    assert branch_and_bound_oracle(dag).makespan == 8


def test_fixed_seed_random_fork_join_cross_validation() -> None:
    rng = random.Random(260817)
    for index in range(12):
        dag = random_join_dag(rng, index)
        dynamic_programming = exact_oracle(dag, max_states=500_000)
        branch_and_bound = branch_and_bound_oracle(dag, max_states=500_000)
        assert dynamic_programming.makespan == branch_and_bound.makespan


def test_oracle_key_must_distinguish_active_compute_remaining_time() -> None:
    dag = DAG('remaining_time_matters', (Task('trigger', 'comm', 1), Task('tail', 'compute', 5, ('trigger',)), Task('side', 'comm', 3)), context=(('category', 'r1_oracle'),))

    result = exact_oracle(dag)
    assert result.makespan == 6
    assert result.forced_waits == 1
    assert result.trace.final_state.time == 6


def test_state_and_time_limits_fail_explicitly() -> None:
    dag = _waiting_counterexample()

    try:
        exact_oracle(dag, max_states=1)
    except RuntimeError as error:
        assert "max_states" in str(error)
    else:
        raise AssertionError("max_states limit was not enforced")

    try:
        branch_and_bound_oracle(dag, time_limit_s=-1)
    except TimeoutError as error:
        assert "time_limit_s" in str(error)
    else:
        raise AssertionError("time limit was not enforced")
