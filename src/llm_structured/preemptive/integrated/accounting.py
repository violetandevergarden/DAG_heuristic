"""Shared cooperative budget used by experimental integrated components."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter


@dataclass
class SharedBudget:
    max_operations: int
    max_completion_calls: int
    max_expansions: int
    per_decision_time_limit_s: float
    total_deadline: float | None
    started: float = field(default_factory=perf_counter)
    operations: int = 0
    completion_calls: int = 0
    expansions: int = 0
    fallback_reason: str | None = None

    def _time_available(self) -> bool:
        now = perf_counter()
        if self.total_deadline is not None and now >= self.total_deadline:
            self.fallback_reason = "total_time_limit"
            return False
        if self.per_decision_time_limit_s and now - self.started >= self.per_decision_time_limit_s:
            self.fallback_reason = "decision_time_limit"
            return False
        return True

    def reserve(self, kind: str, count: int = 1) -> bool:
        """Atomically reserve work before it is performed."""

        if count < 0:
            raise ValueError("reservation count must be non-negative")
        if not self._time_available():
            return False
        field_name, limit = {
            "operation": ("operations", self.max_operations),
            "completion": ("completion_calls", self.max_completion_calls),
            "expansion": ("expansions", self.max_expansions),
        }.get(kind, (None, None))
        if field_name is None:
            raise ValueError(f"unknown budget kind: {kind}")
        current = getattr(self, field_name)
        if current + count > limit:
            self.fallback_reason = f"{kind}_limit"
            return False
        setattr(self, field_name, current + count)
        return True
