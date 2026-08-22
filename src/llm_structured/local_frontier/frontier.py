"""Frontier stopping and state comparison helpers."""

from __future__ import annotations

from core.execution.preemptive import ScheduleState
from single_channel.complex_chain.preemptive import solver


def states_merged(left: ScheduleState, right: ScheduleState) -> bool:
    """True only for future-equivalent normalized public states."""

    return solver.normalized_state_key(left) == solver.normalized_state_key(right)


def local_work_remaining(state: ScheduleState, indices: tuple[int, ...]) -> int:
    return sum(state.tasks[index].remaining for index in indices)
