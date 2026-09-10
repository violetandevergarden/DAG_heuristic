from __future__ import annotations

from llm_structured.preemptive.repetition.solver import (
    build_exchangeable_replicas,
    build_pp_dp_repetition,
    exact_oracle_paired,
    schedule_coupling_aware,
    schedule_role_copy,
)
from core.oracle.pree_single import exact_oracle


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


def test_component_symmetry_is_a_paired_controlled_quotient() -> None:
    # The review found the historical comparison of two different exact
    # implementations uncontrolled.  The paired solver differs ONLY in the
    # memo key: identity versus certified component permutation quotient.
    dag, components = build_exchangeable_replicas(5)
    identity = exact_oracle_paired(dag, components, quotient=False, max_states=100_000)
    quotient = exact_oracle_paired(dag, components, quotient=True, max_states=100_000)

    assert identity.makespan == quotient.makespan
    assert quotient.explored_states < identity.explored_states
    assert quotient.generated_transitions < identity.generated_transitions

    # The identity mode must agree with the independent generic oracle.
    generic = exact_oracle(dag, max_states=100_000)
    assert identity.makespan == generic.makespan
