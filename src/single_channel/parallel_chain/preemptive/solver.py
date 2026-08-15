"""Parallel-chain preemptive algorithms with explicit shape validation."""

from __future__ import annotations

from core.dag import BenchmarkDAG
from single_channel.complex_chain.preemptive import solver as _general


def _validate(dag: BenchmarkDAG) -> None:
    # Local import avoids the package interface/solver import cycle.
    from single_channel.parallel_chain.preemptive.interface import validate_parallel_chain

    validate_parallel_chain(dag)


def schedule_longest_tail(dag: BenchmarkDAG):
    _validate(dag)
    return _general.schedule_longest_tail(dag)


def schedule_priority(dag: BenchmarkDAG, priority: str = "longest_tail"):
    _validate(dag)
    return _general.schedule_priority(dag, priority)


def schedule_rollout(dag: BenchmarkDAG, *, top_k: int = 2, candidate_mode: str = "tail"):
    _validate(dag)
    return _general.schedule_rollout(dag, top_k=top_k, candidate_mode=candidate_mode)


def beam_search(dag: BenchmarkDAG, *, width: int = 8):
    _validate(dag)
    return _general.beam_search(dag, width=width)


def monte_carlo(dag: BenchmarkDAG, *, samples: int = 64, seed: int = 0):
    _validate(dag)
    return _general.monte_carlo(dag, samples=samples, seed=seed)


def exact_oracle(dag: BenchmarkDAG, **kwargs):
    _validate(dag)
    return _general.exact_oracle(dag, **kwargs)


residual_tail = _general.residual_tail
