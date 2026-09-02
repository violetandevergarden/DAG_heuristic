"""One whole legal action followed by the same frozen LT completion."""

from __future__ import annotations

from llm_structured.nonpreemptive.runtime import complete


def compare(adapter, state, actions, mode, budget, config):
    values = {}
    for action in actions:
        if not budget.reserve("completion_calls", config.max_completion_calls):
            return None
        transition = adapter.step(state, action)
        remainder, _ = complete(adapter, transition.after, mode)
        values[str(adapter.signature(state, action))] = transition.after.time - state.time + remainder
    return values
