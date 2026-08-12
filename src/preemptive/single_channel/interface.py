"""Public interface for single-channel preemptive algorithms."""

from __future__ import annotations

from typing import Protocol

from core.dag import BenchmarkDAG
from preemptive.core.model import PreemptiveScheduleResult


class Algorithm(Protocol):
    def __call__(self, dag: BenchmarkDAG) -> PreemptiveScheduleResult: ...

