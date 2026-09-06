"""Shared contracts for non-preemptive Stage 4 runtime code."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Mode = Literal["optional_idle", "work_conserving"]
PolicyName = Literal[
    "fifo",
    "fixed_order",
    "longest_tail",
    "spt",
    "lpt",
    "job_fixed_order",
    "job_round_robin",
    "job_age",
    "shortest_remaining_job",
    "job_aware_longest_tail",
    "starvation_safeguard",
]


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


@dataclass(frozen=True)
class DecisionContext:
    """Read-only observations for one immutable simulator decision state."""

    state: object
    mode: Mode
    ready: tuple[str, ...]
    active_computes: tuple[str, ...]
    active_communications: tuple[str, ...]
    legal_actions: tuple[object, ...]
    tails: dict[str, int]
    next_event_distance: int | None
    occupied_resources: tuple[str, ...]
    free_resources: tuple[str, ...]
