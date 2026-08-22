"""Bounded local forecast using only public simulator transitions."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from core.execution.preemptive import Action, PreemptiveDAGModel, ScheduleState
from single_channel.complex_chain.preemptive import solver

from .accounting import FrontierBudget
from .frontier import states_merged
from .region import LocalRegion


@dataclass(frozen=True)
class FrontierEvaluation:
    action: str
    decisions: int
    events: int
    elapsed_local: int
    residual_lower_bound: int
    residual_proxy: int
    uncertainty: int
    complete: bool
    stop_reason: str
    expansions: int
    simulator_steps: int
    local_nodes_visited: int
    runtime_ms: float
    merged: bool


@dataclass(frozen=True)
class PairEvaluation:
    baseline: FrontierEvaluation
    challenger: FrontierEvaluation
    complete: bool
    recommended_action: str
    proxy_gain: int
    merged: bool
    fallback_reason: str | None


def _advance(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    *,
    depth: int,
    region: LocalRegion,
    budget: FrontierBudget,
) -> tuple[ScheduleState, int, int, str]:
    current = state
    decisions = events = 0
    region_set = set(region.task_ids)
    while not model.is_finished(current):
        eligible = model.eligible_communications(current)
        if eligible and decisions >= depth:
            return current, decisions, events, "decision_depth"
        reason = budget.reserve_step()
        if reason is not None:
            return current, decisions, events, reason
        if eligible:
            local = tuple(item for item in eligible if item in region_set)
            pool = local or eligible
            tails = solver.residual_tail(model, current, pool)
            selected = min(
                pool,
                key=lambda item: (
                    -(tails[item] - solver._own_remaining(model, current, item)), item
                ),
            )
            action = Action.run(selected)
            decisions += 1
        else:
            action = Action.wait()
        transition = model.step(current, action)
        events += len(transition.events)
        current = transition.after
        if not any(
            current.tasks[model.index[item]].status != "completed"
            for item in region.task_ids
        ):
            return current, decisions, events, "local_region_complete"
    return current, decisions, events, "dag_complete"


def evaluate_pair(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    region: LocalRegion,
    *,
    depth: int,
    budget: FrontierBudget,
) -> PairEvaluation:
    started = perf_counter()
    results: list[FrontierEvaluation] = []
    states: list[ScheduleState] = []
    for action_id in (region.baseline_action, region.challenger_action):
        before_expansions = budget.expansions
        first_reason = budget.reserve_step()
        if first_reason is not None:
            stop = first_reason
            current = state
            decisions = events = 0
        else:
            transition = model.step(state, Action.run(action_id))
            current, decisions, events, stop = _advance(
                model, transition.after, depth=max(depth - 1, 0),
                region=region, budget=budget,
            )
            decisions += 1
            events += len(transition.events)
        states.append(current)
        lower = solver.remaining_lower_bound(model, current)
        proxy = current.time + lower
        complete = stop in {"local_region_complete", "dag_complete"}
        results.append(FrontierEvaluation(
            action_id, decisions, events, current.time - state.time, lower, proxy,
            0 if complete else lower, complete, stop,
            budget.expansions - before_expansions,
            budget.simulator_steps, region.node_count,
            (perf_counter() - started) * 1000, False,
        ))
    merged = states_merged(states[0], states[1])
    left, right = results
    left = FrontierEvaluation(**{**left.__dict__, "merged": merged})
    right = FrontierEvaluation(**{**right.__dict__, "merged": merged})
    complete = region.complete and left.complete and right.complete
    gain = left.residual_proxy - right.residual_proxy
    recommended = region.challenger_action if gain > 0 else region.baseline_action
    fallback = None if complete else (
        region.truncation_reason or left.stop_reason if not left.complete else right.stop_reason
    )
    return PairEvaluation(left, right, complete, recommended, gain, merged, fallback)
