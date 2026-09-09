"""Atomic work accounting for local-frontier evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter


@dataclass
class FrontierBudget:
    max_expansions: int
    decision_deadline: float
    total_deadline: float
    expansions: int = 0
    simulator_steps: int = 0

    def reserve_step(self) -> str | None:
        now = perf_counter()
        if now >= self.total_deadline:
            return "total_time_limit"
        if now >= self.decision_deadline:
            return "decision_time_limit"
        if self.expansions >= self.max_expansions:
            return "expansion_limit"
        self.expansions += 1
        self.simulator_steps += 1
        return None
