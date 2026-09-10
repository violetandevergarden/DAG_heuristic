"""One whole legal action followed by the same frozen LT completion."""

from __future__ import annotations

from llm_structured.nonpreemptive.baseline import complete


def compare(adapter, state, actions, mode, budget, config, context=None):
    values = {}
    for action in actions:
        if not budget.reserve("completion_calls", config.max_completion_calls):
            return None
        signature = adapter.signature(state, action)
        transition = (context.transition_cache.get(signature) if context is not None else None)
        if transition is None:
            transition = adapter.step(state, action)
            if context is not None:
                context.transition_cache[signature] = transition
        cache_key = (signature, mode)
        if context is not None and cache_key in context.completion_cache:
            remainder = context.completion_cache[cache_key]
        else:
            remainder, _ = complete(adapter, transition.after, mode)
            if context is not None:
                context.completion_cache[cache_key] = remainder
        values[str(signature)] = transition.after.time - state.time + remainder
    return values
