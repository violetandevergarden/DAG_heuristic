"""Interface placeholder for future fixed-resource preemptive algorithms.

The v2 data format can describe fixed resource sets, but the first executable
core intentionally supports only a single channel.  Multi-resource state
transitions must preserve all-or-nothing acquisition and release all resources
when a communication is paused.
"""

from __future__ import annotations

from typing import Protocol

from benchmark import Benchmark


class Result(Protocol):
    makespan: int


class Algorithm(Protocol):
    def __call__(self, benchmark: Benchmark) -> Result: ...

