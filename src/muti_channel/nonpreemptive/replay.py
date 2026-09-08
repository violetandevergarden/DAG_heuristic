"""Schedule replay and validation for the non-preemptive multi-resource model."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from .solver import (
    NonPreeMultiModel,
    ResourceAction,
    ResourceInterval,
    ResourceSchedule,
)


def assert_route_reservations(
    model: NonPreeMultiModel,
    intervals: Iterable[ResourceInterval],
) -> None:
    communications = [interval for interval in intervals if interval.kind == "comm"]
    intervals_by_task: dict[str, int] = defaultdict(int)
    for interval in communications:
        if interval.end <= interval.start:
            raise AssertionError(f"invalid communication interval: {interval}")
        intervals_by_task[interval.task_id] += 1
    if any(count != 1 for count in intervals_by_task.values()):
        raise AssertionError("a flow was split into multiple intervals")
    for left, first in enumerate(communications):
        for second in communications[left + 1 :]:
            overlap = first.start < second.end and second.start < first.end
            if not overlap:
                continue
            first_resources = model.resources[model.index[first.task_id]]
            second_resources = model.resources[model.index[second.task_id]]
            if first_resources & second_resources:
                raise AssertionError(f"overlapping flows share route resources: {first}, {second}")


def replay_actions(
    model: NonPreeMultiModel,
    actions: Iterable[ResourceAction],
    *,
    runtime_ms: float,
    explored_states: int = 0,
    candidate_actions: int = 0,
    lower: dict[str, int] | None = None,
    fallback: bool = False,
    validate: bool = True,
) -> ResourceSchedule:
    state = model.initial_state()
    path = tuple(actions)
    intervals: list[ResourceInterval] = []
    voluntary_waits = voluntary_wait_time = 0
    forced_waits = forced_wait_time = 0
    conflict_events = 0
    for action in path:
        ready = model.ready_flows(state)
        if len(ready) >= 2:
            resources = [model.resources[model.index[task_id]] for task_id in ready]
            conflict_events += any(
                resources[left] & resources[right]
                for left in range(len(resources))
                for right in range(left + 1, len(resources))
            )
        had_compatible = bool(model.start_subsets(state, maximal_only=False))
        transition = model.step(state, action)
        duration = transition.after.time - transition.before.time
        if action.kind == "wait":
            if had_compatible:
                voluntary_waits += 1
                voluntary_wait_time += duration
            else:
                forced_waits += 1
                forced_wait_time += duration
        intervals.extend(transition.intervals)
        state = transition.after
    if not model.is_finished(state):
        raise AssertionError("schedule did not finish")
    if validate:
        assert_route_reservations(model, intervals)
    return ResourceSchedule(
        state.time,
        path,
        tuple(intervals),
        runtime_ms,
        explored_states,
        voluntary_waits,
        voluntary_wait_time,
        forced_waits,
        forced_wait_time,
        sum(action.kind == "start" for action in path),
        sum(len(action.starts) for action in path),
        candidate_actions,
        conflict_events,
        lower,
        fallback,
    )


__all__ = ["assert_route_reservations", "replay_actions"]
