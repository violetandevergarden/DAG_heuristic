"""Public interface for preemptive general-DAG scheduling."""

from __future__ import annotations

from core.dag import DAG
from core.execution.preemptive import PreemptiveScheduleResult
from core.oracle.preemptive import exact_oracle, exact_oracle_uncompressed
from single_channel.complex_chain.preemptive import solver


def validate_complex_chain(dag: DAG) -> None:
    """Validate the Stage 2 internal family contract.

    Stage 2 deliberately accepts raw general DAGs, including same-kind edges
    and multiple weak components.  Components are concurrent parts of one
    makespan instance, not separate jobs.  No canonicalization or silent
    chainification is performed.
    """
    errors = dag.validate()
    if not dag.tasks:
        errors.append("complex_chain requires at least one task")
    if errors:
        raise ValueError(f"invalid complex_chain DAG {dag.name}: {errors}")


def solve(
    dag: DAG,
    algorithm: str = "longest_tail",
    **options: object,
) -> PreemptiveScheduleResult:
    validate_complex_chain(dag)
    algorithms = {
        "fifo": lambda item: solver.schedule_priority(item, "fifo"),
        "spt": lambda item: solver.schedule_priority(item, "spt"),
        "lpt": lambda item: solver.schedule_priority(item, "lpt"),
        "longest_delay": lambda item: solver.schedule_priority(item, "longest_delay"),
        "release_gain": lambda item: solver.schedule_priority(item, "release_gain"),
        "lrpt": lambda item: solver.schedule_priority(item, "lrpt"),
        "join_aware": lambda item: solver.schedule_priority(item, "join_aware"),
        "shared_downstream": lambda item: solver.schedule_priority(
            item, "shared_downstream"
        ),
        "downstream_demand": lambda item: solver.schedule_priority(
            item, "downstream_demand"
        ),
        "longest_tail": solver.schedule_longest_tail,
        "rollout2": solver.schedule_rollout,
        "beam8": lambda item: solver.beam_search(item, width=8),
        "exact": exact_oracle,
        "exact_uncompressed": exact_oracle_uncompressed,
    }
    try:
        implementation = algorithms[algorithm]
    except KeyError as error:
        raise ValueError(f"unknown preemptive complex-chain algorithm: {algorithm}") from error
    if options:
        if algorithm == "rollout2":
            return solver.schedule_rollout(dag, **options)  # type: ignore[arg-type]
        if algorithm == "beam8":
            return solver.beam_search(dag, width=8, **options)  # type: ignore[arg-type]
        if algorithm == "exact":
            return exact_oracle(dag, **options)  # type: ignore[arg-type]
        if algorithm == "exact_uncompressed":
            return exact_oracle_uncompressed(dag, **options)  # type: ignore[arg-type]
        raise ValueError(f"algorithm {algorithm} does not accept options")
    return implementation(dag)
