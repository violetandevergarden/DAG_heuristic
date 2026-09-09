"""Depth-limited complete-action evaluator with a shared hard ledger."""

from __future__ import annotations

from time import perf_counter

from llm_structured.nonpreemptive.baseline.completion import CompletionDeadlineExceeded

from ..baseline.completion import complete, longest_tail_action
from .candidates import generate


class BudgetExhausted(RuntimeError):
    pass


def evaluate(
    adapter, state, candidates, depth, mode, ledger, config, cache, started, precomputed=None
):
    decision_started = perf_counter()
    deadline = min(
        started + config.per_instance_soft_time_s,
        decision_started + config.per_decision_soft_time_s,
    )

    def value(current, remaining_depth):
        if adapter.is_finished(current):
            return 0, 0
        if perf_counter() >= deadline:
            raise BudgetExhausted("soft_wall_time")
        if remaining_depth == 0:
            if not ledger.reserve("completion_calls", config.max_completion_calls):
                raise BudgetExhausted("completion_calls")
            try:
                elapsed, _ = complete(adapter, current, mode, deadline=deadline)
            except CompletionDeadlineExceeded as error:
                raise BudgetExhausted("completion_deadline") from error
            return elapsed, 0
        key = (current, remaining_depth, mode, config.completion_version, config.candidate_version)
        if key in cache:
            ledger.cache_hits += 1
            return cache[key]
        if not ledger.reserve("expanded_decision_states", config.max_expanded_decision_states):
            raise BudgetExhausted("expanded_states")
        branch, _generated, _truncated = generate(
            adapter,
            current,
            mode,
            config.max_candidates_per_decision,
            config.candidate_mode,
        )
        best = None
        actual = 0
        for action in branch:
            transition = adapter.step(current, action)
            suffix, child_depth = value(transition.after, remaining_depth - 1)
            candidate = (transition.after.time - current.time + suffix, max(1, child_depth + 1))
            if (
                best is None
                or candidate[0] < best[0]
                or (
                    candidate[0] == best[0]
                    and action == longest_tail_action(adapter, current, mode)
                )
            ):
                best = candidate
            actual = max(actual, candidate[1])
        assert best is not None
        if len(cache) < config.max_cache_entries:
            cache[key] = (best[0], actual)
            ledger.cache_writes += 1
        return best[0], actual

    scored = []
    for action in candidates:
        transition = (precomputed or {}).get(adapter.signature(state, action)) or adapter.step(
            state, action
        )
        suffix, child_depth = value(transition.after, max(0, depth - 1))
        scored.append(
            (transition.after.time - state.time + suffix, action, max(1, child_depth + 1))
        )
        ledger.evaluated_candidates += 1
    baseline = longest_tail_action(adapter, state, mode)
    scored.sort(key=lambda item: (item[0], item[1] != baseline, adapter.signature(state, item[1])))
    return scored[0][1], scored
