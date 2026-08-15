"""Public interface for single-channel complex-DAG algorithms."""

from __future__ import annotations

from typing import Protocol

from core.dag import BenchmarkDAG


class Result(Protocol):
    makespan: int


class Algorithm(Protocol):
    def __call__(self, dag: BenchmarkDAG) -> Result: ...
