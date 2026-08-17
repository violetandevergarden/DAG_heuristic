"""Public interface for preemptive general-DAG scheduling."""

from __future__ import annotations

from core.dag import BenchmarkDAG
from core.execution.preemptive import PreemptiveScheduleResult
from single_channel.complex_chain.preemptive import solver


def validate_complex_chain(dag: BenchmarkDAG) -> None:
    """Apply the raw-general-DAG Stage 2 family contract."""

    solver.validate_complex_chain(dag)


def solve(
    dag: BenchmarkDAG,
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
        "barrier_aware": lambda item: solver.schedule_priority(item, "barrier_aware"),
        "shared_downstream": lambda item: solver.schedule_priority(
            item, "shared_downstream"
        ),
        "downstream_demand": lambda item: solver.schedule_priority(
            item, "downstream_demand"
        ),
        "structure_aware": lambda item: solver.schedule_priority(item, "structure_aware"),
        "longest_tail": solver.schedule_longest_tail,
        "barrier_only": lambda item: solver.schedule_barrier_policy(
            item, "barrier_only"
        ),
        "tail_barrier": lambda item: solver.schedule_barrier_policy(
            item, "tail_barrier"
        ),
        "barrier_safeguarded": solver.schedule_barrier_safeguarded,
        "barrier_selective_rollout": solver.schedule_selective_barrier_rollout,
        "rollout2": solver.schedule_rollout,
        "beam8": lambda item: solver.beam_search(item, width=8),
        "exact": solver.exact_oracle,
        "exact_uncompressed": solver.exact_oracle_uncompressed,
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
            return solver.exact_oracle(dag, **options)  # type: ignore[arg-type]
        if algorithm == "exact_uncompressed":
            return solver.exact_oracle_uncompressed(dag, **options)  # type: ignore[arg-type]
        raise ValueError(f"algorithm {algorithm} does not accept options")
    return implementation(dag)
