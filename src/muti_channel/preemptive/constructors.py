"""Bounded maximal-set constructors separated from simulator execution."""

from __future__ import annotations

from time import perf_counter

from core.execution.multi_resource import MultiResourceAction, PreemptiveMultiResourceModel
from muti_channel.preemptive.packing import (
    PackingBudget,
    PackingResult,
    PackingStats,
    complete_maximal,
    deadline_exceeded,
    validate_maximal_action,
)


def greedy(
    model: PreemptiveMultiResourceModel, state, scores: dict[str, tuple]
) -> PackingResult:
    started = perf_counter()
    eligible = tuple(model.eligible(state))
    if set(scores) != set(eligible):
        raise ValueError("scores must cover exactly the eligible communications")
    action = complete_maximal(model, state, tuple(sorted(eligible, key=scores.__getitem__)))
    return PackingResult(
        action,
        (action,),
        PackingStats(candidate_count=1, operations=len(eligible), runtime_ms=(perf_counter()-started)*1000),
    )


def multi_seed(
    model: PreemptiveMultiResourceModel,
    state,
    scores: dict[str, tuple],
    budget: PackingBudget = PackingBudget(),
) -> PackingResult:
    started = perf_counter()
    baseline = greedy(model, state, scores).selected
    ordered = tuple(sorted(model.eligible(state), key=scores.__getitem__))
    candidates: list[MultiResourceAction] = [baseline]
    operations = len(ordered)
    reason = None
    for seed in ordered[: budget.k_seed]:
        if deadline_exceeded(started, budget):
            reason = "time_limit"
            break
        if operations + len(ordered) > budget.b_pack:
            reason = "pack_budget"
            break
        action = complete_maximal(model, state, ordered, seed=(seed,))
        operations += len(ordered)
        if action not in candidates:
            candidates.append(action)
        if len(candidates) >= budget.max_sets:
            reason = "set_budget" if len(candidates) < len(ordered) else None
            break
    exhausted = reason is not None
    return PackingResult(
        baseline,
        tuple(candidates),
        PackingStats(len(candidates), min(len(ordered), budget.k_seed), 0, operations, exhausted, reason, (perf_counter()-started)*1000),
    )


def one_exchange(
    model: PreemptiveMultiResourceModel,
    state,
    scores: dict[str, tuple],
    budget: PackingBudget = PackingBudget(),
) -> PackingResult:
    """Generate maximal neighbors by replacing one baseline member."""

    started = perf_counter()
    seeded = multi_seed(model, state, scores, budget)
    baseline = seeded.selected
    ordered = tuple(sorted(model.eligible(state), key=scores.__getitem__))
    candidates = list(seeded.candidates)
    operations = seeded.stats.operations
    exchanges = 0
    reason = seeded.stats.fallback_reason
    for removed in baseline.communications:
        for replacement in ordered:
            if replacement in baseline.communications:
                continue
            if deadline_exceeded(started, budget):
                reason = "time_limit"
                break
            if operations + len(ordered) > budget.b_pack:
                reason = "pack_budget"
                break
            seed = tuple(item for item in baseline.communications if item != removed)
            if not model.compatible((*seed, replacement)):
                continue
            action = complete_maximal(model, state, ordered, seed=(*seed, replacement))
            operations += len(ordered)
            exchanges += 1
            if action not in candidates:
                candidates.append(action)
            if len(candidates) >= budget.max_sets:
                reason = "set_budget"
                break
        if reason is not None:
            break
    return PackingResult(
        baseline,
        tuple(candidates),
        PackingStats(len(candidates), seeded.stats.seed_count, exchanges, operations, reason is not None, reason, (perf_counter()-started)*1000),
    )


def enumerate_bounded(
    model: PreemptiveMultiResourceModel,
    state,
    scores: dict[str, tuple],
    budget: PackingBudget = PackingBudget(),
) -> PackingResult:
    started = perf_counter()
    baseline = greedy(model, state, scores).selected
    legal = model.maximal_actions(state)
    candidates = tuple(legal[: budget.max_sets])
    reason = "set_budget" if len(candidates) < len(legal) else None
    for action in candidates:
        validate_maximal_action(model, state, action)
    return PackingResult(
        baseline,
        candidates or (baseline,),
        PackingStats(len(candidates), 0, 0, len(legal), reason is not None, reason, (perf_counter()-started)*1000),
    )


def choose_by_depth1_longest_tail(model, state, result: PackingResult):
    """Evaluate candidates with the same LT-pack completion and strict safeguard."""

    from muti_channel.preemptive.solver import _complete_pack

    baseline_value = _complete_pack(model, model.step(state, result.selected))[0].time
    best = (baseline_value, result.selected.communications, result.selected)
    calls = 1
    for action in result.candidates:
        if action == result.selected:
            continue
        value = _complete_pack(model, model.step(state, action))[0].time
        calls += 1
        if value < best[0]:
            best = (value, action.communications, action)
    return best[2], calls
