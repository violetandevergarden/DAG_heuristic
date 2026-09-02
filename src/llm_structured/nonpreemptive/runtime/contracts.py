"""Shared contracts for non-preemptive Stage 4 runtime code."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Mode = Literal["optional_idle", "work_conserving"]
PolicyName = Literal["fifo", "fixed_order", "longest_tail", "spt", "lpt"]


@dataclass(frozen=True, order=True)
class ActionSignature:
    kind: Literal["flow", "start", "wait"]
    task_ids: tuple[str, ...] = ()
    next_event_time: int | None = None


@dataclass(frozen=True)
class ReplaySummary:
    makespan: int
    trace_valid: bool
    voluntary_waits: int
    voluntary_wait_time: int
    forced_waits: int
    forced_wait_time: int
