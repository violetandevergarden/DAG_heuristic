"""Bounded maximal-set constructors; they never advance simulation time."""

from __future__ import annotations

from time import perf_counter

from core.execution.preemptive import MultiResourceAction, PreeMultiModel
from muti_channel.preemptive.packing import (
    DecisionBudget, PackingBudget, PackingResult, PackingStats, complete_maximal,
    iter_maximal_actions, validate_maximal_action,
)


def _result(model, state, baseline, candidates, constructor, ledger, *, seeds=0, exchanges=0, truncated=False):
    candidates = tuple(sorted(set(candidates), key=lambda item: item.communications))
    for action in candidates:
        validate_maximal_action(model, state, action)
    reason = ledger.fallback_reason
    return PackingResult(
        baseline=baseline, candidates=candidates, selected=baseline,
        constructor=constructor, selector="unselected", config_version="stage4c-packing-v2",
        truncated=truncated, fallback_reason=reason,
        stats=PackingStats(candidate_count=len(candidates), generated_candidates=ledger.generated_candidates,
                           seed_count=seeds, exchange_count=exchanges, operations=ledger.operations,
                           completion_calls=ledger.completion_calls, budget_exhausted=reason is not None,
                           fallback_reason=reason, runtime_ms=(perf_counter()-ledger.started)*1000),
    )


def _prepare(model, state, scores, budget, ledger=None):
    eligible = tuple(model.eligible(state))
    if set(scores) != set(eligible):
        raise ValueError("scores must cover exactly the eligible communications")
    ordered = tuple(sorted(eligible, key=scores.__getitem__))
    ledger = ledger or DecisionBudget(budget)
    # Baseline remains available even when optional-constructor budget is zero.
    baseline = complete_maximal(model, state, ordered)
    return ordered, baseline, ledger


def greedy(model: PreeMultiModel, state, scores: dict[str, tuple], ledger=None) -> PackingResult:
    ordered, baseline, ledger = _prepare(model, state, scores, PackingBudget(), ledger)
    ledger.operations = len(ordered)
    return _result(model, state, baseline, (), "greedy", ledger)


def multi_seed(model: PreeMultiModel, state, scores: dict[str, tuple], budget: PackingBudget = PackingBudget(), ledger=None) -> PackingResult:
    ordered, baseline, ledger = _prepare(model, state, scores, budget, ledger)
    candidates: list[MultiResourceAction] = []
    seeds = 0
    if budget.max_sets == 0:
        return _result(model, state, baseline, (), "multi_seed", ledger)
    for seed in ordered[:budget.k_seed]:
        if not ledger.consume_operation(len(ordered)):
            break
        action = complete_maximal(model, state, ordered, seed=(seed,))
        seeds += 1
        if action != baseline and action not in candidates:
            if not ledger.retain_candidate():
                break
            candidates.append(action)
    return _result(model, state, baseline, candidates, "multi_seed", ledger, seeds=seeds, truncated=ledger.fallback_reason is not None)


def one_exchange(model: PreeMultiModel, state, scores: dict[str, tuple], budget: PackingBudget = PackingBudget(), ledger=None) -> PackingResult:
    ordered, baseline, ledger = _prepare(model, state, scores, budget, ledger)
    candidates: list[MultiResourceAction] = []
    exchanges = 0
    if budget.max_sets == 0:
        return _result(model, state, baseline, (), "one_exchange", ledger)
    for removed in baseline.communications:
        for replacement in ordered:
            if replacement in baseline.communications:
                continue
            if not ledger.consume_operation(len(ordered)):
                return _result(model, state, baseline, candidates, "one_exchange", ledger, exchanges=exchanges, truncated=True)
            seed = tuple(item for item in baseline.communications if item != removed)
            if not model.compatible((*seed, replacement)):
                continue
            exchanges += 1
            action = complete_maximal(model, state, ordered, seed=(*seed, replacement))
            if action != baseline and action not in candidates:
                if not ledger.retain_candidate():
                    return _result(model, state, baseline, candidates, "one_exchange", ledger, exchanges=exchanges, truncated=True)
                candidates.append(action)
    return _result(model, state, baseline, candidates, "one_exchange", ledger, exchanges=exchanges, truncated=ledger.fallback_reason is not None)


def enumerate_bounded(model: PreeMultiModel, state, scores: dict[str, tuple], budget: PackingBudget = PackingBudget(), ledger=None) -> PackingResult:
    _ordered, baseline, ledger = _prepare(model, state, scores, budget, ledger)
    candidates: list[MultiResourceAction] = []
    if budget.max_sets == 0:
        return _result(model, state, baseline, (), "enumeration", ledger)
    for action in iter_maximal_actions(model, state, ledger):
        if action == baseline or action in candidates:
            continue
        if not ledger.retain_candidate():
            return _result(model, state, baseline, candidates, "enumeration", ledger, truncated=True)
        candidates.append(action)
        if len(candidates) >= budget.max_sets:
            ledger.fallback_reason = "set_budget"
            return _result(model, state, baseline, candidates, "enumeration", ledger, truncated=True)
    return _result(model, state, baseline, candidates, "enumeration", ledger, truncated=ledger.fallback_reason is not None)


def choose_by_depth1_longest_tail(model, state, result: PackingResult, ledger: DecisionBudget):
    """Evaluate candidates one at a time, reserving each completion call first."""
    from muti_channel.preemptive.solver import _complete_pack

    best = result.baseline
    best_value = None
    evaluated = 0
    for action in (result.baseline, *result.candidates):
        if not ledger.reserve_completion():
            break
        value = _complete_pack(model, model.step(state, action))[0].time
        evaluated += 1
        candidate = (value, action.communications)
        if best_value is None or candidate < (best_value, best.communications):
            best_value = value
            best = action
    return best, evaluated
