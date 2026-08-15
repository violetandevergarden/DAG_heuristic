from __future__ import annotations

from llm_structured.repetition import (
    build_exchangeable_replicas,
    build_pp_dp_repetition,
    exact_oracle_component_symmetry,
    schedule_coupling_aware,
    schedule_role_copy,
)
from single_channel.complex_chain.preemptive.solver import exact_oracle


def test_independent_local_optimum_does_not_safely_copy() -> None:
    one = build_pp_dp_repetition(1)
    many = build_pp_dp_repetition(8)

    # DP first is strictly better in the isolated period.
    assert schedule_role_copy(one, "DP").makespan < schedule_role_copy(one, "PP").makespan
    exact = exact_oracle(many)
    copied = schedule_role_copy(many, "DP")
    aware = schedule_coupling_aware(many)

    assert copied.makespan > exact.makespan
    assert aware.makespan == exact.makespan


def test_component_symmetry_is_exact_and_reduces_states() -> None:
    dag, components = build_exchangeable_replicas(5)
    generic = exact_oracle(dag, max_states=100_000)
    compressed = exact_oracle_component_symmetry(dag, components, max_states=100_000)

    assert compressed.makespan == generic.makespan
    assert compressed.explored_states < generic.explored_states / 10
