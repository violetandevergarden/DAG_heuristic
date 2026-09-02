"""Complete a residual state with one frozen shared baseline."""

from .policies import baseline_action, longest_tail_action


def complete(adapter, state, mode, policy="longest_tail"):
    actions = []
    start = state.time
    while not adapter.is_finished(state):
        action = baseline_action(adapter, state, mode, policy)
        actions.append(action)
        state = adapter.step(state, action).after
    return state.time - start, tuple(actions)


__all__ = ["complete", "longest_tail_action"]
