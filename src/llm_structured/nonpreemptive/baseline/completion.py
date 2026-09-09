"""Complete a residual state with one frozen shared baseline."""

from __future__ import annotations

from time import perf_counter

from .solver import baseline_action, longest_tail_action


class CompletionDeadlineExceeded(TimeoutError):
    """The caller's absolute monotonic deadline expired during completion."""


def complete(adapter, state, mode, policy="longest_tail", *, deadline=None):
    actions = []
    start = state.time
    while not adapter.is_finished(state):
        if deadline is not None and perf_counter() >= deadline:
            raise CompletionDeadlineExceeded("completion_deadline")
        action = baseline_action(adapter, state, mode, policy)
        actions.append(action)
        state = adapter.step(state, action).after
    return state.time - start, tuple(actions)


__all__ = ["CompletionDeadlineExceeded", "complete", "longest_tail_action"]

