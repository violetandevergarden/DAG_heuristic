"""Parallel-chain boundary for the shared preemptive event engine."""

from __future__ import annotations

from core.dag import DAG
from core.execution.preemptive import PreemptiveScheduleResult
from single_channel.parallel_chain.model import parse_parallel_chain
from single_channel.parallel_chain.preemptive import solver


def validate_parallel_chain(dag: DAG) -> None:
    parse_parallel_chain(dag)


def solve(
    dag: DAG,
    algorithm: str = "longest_tail",
    **options: object,
) -> PreemptiveScheduleResult:
    validate_parallel_chain(dag)
    if algorithm == "exact":
        return solver.exact_oracle(dag, **options)
    if options:
        raise ValueError(f"algorithm {algorithm} does not accept options: {sorted(options)}")
    algorithms = {
        "fifo": lambda item: solver.schedule_priority(item, "fifo"),
        "spt": lambda item: solver.schedule_priority(item, "spt"),
        "lpt": lambda item: solver.schedule_priority(item, "lpt"),
        "longest_delay": lambda item: solver.schedule_priority(item, "longest_delay"),
        "lrpt": lambda item: solver.schedule_priority(item, "lrpt"),
        "longest_tail": solver.schedule_longest_tail,
        "rollout2": solver.schedule_rollout,
        "rollout4": lambda item: solver.schedule_rollout(item, top_k=4),
        "rollout2_depth2": lambda item: solver.schedule_rollout(item, top_k=2, depth=2),
        "beam8": lambda item: solver.beam_search(item, width=8),
        "beam32": lambda item: solver.beam_search(item, width=32),
    }
    try:
        implementation = algorithms[algorithm]
    except KeyError as error:
        raise ValueError(f"unknown preemptive parallel-chain algorithm: {algorithm}") from error
    return implementation(dag)
