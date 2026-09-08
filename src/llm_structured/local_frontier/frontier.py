"""Frontier stopping and state comparison helpers."""

from __future__ import annotations

from core.execution.preemptive import ScheduleState
from core.oracle.preemptive import normalized_state_key


def states_merged(left: ScheduleState, right: ScheduleState) -> bool:
    """True only for future-equivalent normalized public states."""

    return normalized_state_key(left) == normalized_state_key(right)


def local_work_remaining(state: ScheduleState, indices: tuple[int, ...]) -> int:
    return sum(state.tasks[index].remaining for index in indices)
