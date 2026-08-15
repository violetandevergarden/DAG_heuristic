"""Public interface for parallel-chain scheduling algorithms."""

from __future__ import annotations

from typing import Protocol

from single_channel.parallel_chain.nonpreemptive.solver import ParallelChain


class Result(Protocol):
    makespan: int


class Algorithm(Protocol):
    def __call__(self, chains: tuple[ParallelChain, ...]) -> Result: ...
