"""Public interface for preemptive general-DAG scheduling."""

from __future__ import annotations

from core.dag import BenchmarkDAG
from core.execution.preemptive import PreemptiveScheduleResult
from single_channel.complex_chain.preemptive import solver


def solve(dag: BenchmarkDAG, algorithm: str = "longest_tail") -> PreemptiveScheduleResult:
    algorithms = {
        "longest_tail": solver.schedule_longest_tail,
        "rollout2": solver.schedule_rollout,
        "beam8": lambda item: solver.beam_search(item, width=8),
        "exact": solver.exact_oracle,
    }
    try:
        implementation = algorithms[algorithm]
    except KeyError as error:
        raise ValueError(f"unknown preemptive complex-chain algorithm: {algorithm}") from error
    return implementation(dag)
