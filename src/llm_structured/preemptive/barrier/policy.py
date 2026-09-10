"""Preemptive Stage 4 barrier policies over the public single-channel model."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from core.dag import DAG
from core.execution.preemptive import Action, PreeSingleModel, PreemptiveScheduleResult, ScheduleState
from llm_structured.preemptive.barrier.analysis import (
    build_context,
    has_barrier_signal,
    online_barrier_inputs,
    priority_key,
    safe_barrier_prescreen,
)
from single_channel.complex_chain.preemptive.solver import (
    _apply_actions,
    _baseline_choice,
    _children,
    _complete_actions,
    _own_remaining,
    _result,
    residual_tail,
    schedule_longest_tail,
)
from single_channel.complex_chain.preemptive.interface import validate_complex_chain


def barrier_urgency(
    model: PreeSingleModel,
    state: ScheduleState,
    task_id: str,
    tail: dict[str, int] | None = None,
) -> int:
    """Return the residual urgency of distinct reachable joins."""

    tails = tail if tail is not None else residual_tail(model, state, [task_id])
    tasks = model.task_map
    children = _children(model)
    distance: dict[str, int] = {task_id: 0}
    for current in model.task_ids:
        if current not in distance:
            continue
        for child in children[current]:
            candidate = distance[current] + (
                0 if current == task_id else _own_remaining(model, state, current)
            )
            distance[child] = max(distance.get(child, 0), candidate)
    return sum(
        max(0, tails[item] - distance[item])
        for item in distance
        if item != task_id and len(tasks[item].deps) > 1
    )


@dataclass(frozen=True)
class OfflineBarrierUpperBound:
    """Offline comparison of complete LT and barrier schedules."""

    online: bool
    full_schedule_runs: int
    baseline: PreemptiveScheduleResult
    candidate: PreemptiveScheduleResult
    selected_policy: str
    runtime_ms: float


def schedule_barrier_policy(
    dag: DAG,
    mode: str = "tail_barrier",
    *,
    trigger: str | None = None,
) -> PreemptiveScheduleResult:
    """Run an explicit barrier-score ablation on the public simulator.

    ``mode`` is one of ``barrier_only``, ``unlock_only``, ``tail``,
    ``tail_unlock``, ``tail_barrier`` or ``tail_unlock_barrier``.  The context
    is built once per stable decision state and the simulator remains the sole
    owner of legality and time advancement.  When ``trigger`` is set, the
    barrier score is evaluated only for states with a residual barrier or
    unlock signal; other states use the LT choice.
    """

    validate_complex_chain(dag)
    model = PreeSingleModel(dag)
    state = model.initial_state()
    actions: list[Action] = []
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        if not eligible:
            action = Action.wait()
        else:
            context = build_context(model, state, roots=eligible)
            snapshots = {item: priority_key(context, item, mode) for item in eligible}
            selected = min(eligible, key=lambda item: snapshots[item])
            if trigger is not None:
                if trigger not in {"barrier_only", "barrier_or_unlock"}:
                    raise ValueError(f"unsupported barrier trigger: {trigger}")
                triggered = (
                    priority_key(context, selected, "barrier_only")[0] < 0
                    if trigger == "barrier_only"
                    else has_barrier_signal(context, selected)
                )
                if not triggered:
                    selected = _baseline_choice(model, state, "longest_tail")
            action = Action.run(selected)
        actions.append(action)
        state = model.step(state, action).after
    return _result(model, actions)


def offline_best_of_lt_and_barrier(
    dag: DAG,
    *,
    mode: str = "tail_barrier",
    trigger: str = "barrier_or_unlock",
    max_rollouts: int | None = None,
) -> OfflineBarrierUpperBound:
    """Return the offline best of two full schedules, never an online result."""

    if mode not in {"barrier_only", "tail_barrier", "tail_unlock_barrier"}:
        raise ValueError(f"unsupported safeguarded barrier mode: {mode}")
    if trigger not in {"barrier_only", "barrier_or_unlock"}:
        raise ValueError(f"unsupported barrier trigger: {trigger}")
    if max_rollouts is not None and max_rollouts <= 0:
        raise ValueError("offline comparison always requires two complete schedules")

    validate_complex_chain(dag)
    started = perf_counter()
    baseline = schedule_longest_tail(dag)
    candidate_result = schedule_barrier_policy(dag, mode, trigger=trigger)
    if candidate_result.makespan < baseline.makespan:
        selected = "barrier_candidate"
    else:
        selected = "longest_tail"
    return OfflineBarrierUpperBound(
        online=False,
        full_schedule_runs=2,
        baseline=baseline,
        candidate=candidate_result,
        selected_policy=selected,
        runtime_ms=(perf_counter() - started) * 1000,
    )


def schedule_barrier_margin_tiebreak(
    dag: DAG,
    *,
    max_normalized_margin: float = 0.25,
) -> PreemptiveScheduleResult:
    """Online LT enhancement with a frozen, bounded barrier tie-break.

    Longest Tail remains available at every state. A barrier challenger is
    eligible only when its residual exclusive-tail distance from LT is within
    ``max_normalized_margin``. The rule is lexicographic: direct last-missing
    joins, then genuine newly-ready compute, then the stable task ID.
    """

    if max_normalized_margin < 0:
        raise ValueError("max_normalized_margin must be non-negative")
    validate_complex_chain(dag)
    model = PreeSingleModel(dag)
    state = model.initial_state()
    actions: list[Action] = []
    audits: list[str] = []
    decisions = triggered = improvements = 0
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        if not eligible:
            action = Action.wait()
        else:
            decisions += 1
            baseline = _baseline_choice(model, state, "longest_tail")
            context = build_context(model, state, roots=eligible)
            snapshots = {item: online_barrier_inputs(context, item) for item in eligible}
            baseline_tail = snapshots[baseline].exclusive_tail
            eligible_challengers = [
                item
                for item in eligible
                if (baseline_tail - snapshots[item].exclusive_tail) / max(baseline_tail, 1)
                <= max_normalized_margin
                and (snapshots[item].direct_last_missing_join_count > 0 or snapshots[item].newly_ready_compute_work > 0)
            ]
            selected = baseline
            if eligible_challengers:
                challenger = min(
                    eligible_challengers,
                    key=lambda item: (
                        -snapshots[item].direct_last_missing_join_count,
                        -snapshots[item].newly_ready_compute_work,
                        -snapshots[item].downstream_join_tail,
                        item,
                    ),
                )
                margin = (baseline_tail - snapshots[challenger].exclusive_tail) / max(baseline_tail, 1)
                triggered += challenger != baseline
                selected = challenger
                improvements += challenger != baseline
                audits.append(
                    f"baseline={baseline};selected={selected};margin={margin:.6f};"
                    f"last_missing={snapshots[challenger].direct_last_missing_join_count};"
                    f"new_ready={snapshots[challenger].newly_ready_compute_work}"
                )
            action = Action.run(selected)
        actions.append(action)
        state = model.step(state, action).after
    result = _result(model, actions)
    return result.with_stats(
        planner_decisions=decisions,
        planner_triggered=triggered,
        planner_improvements=improvements,
        fallback_details=tuple(audits),
    )


def schedule_barrier_prescreen(dag: DAG) -> PreemptiveScheduleResult:
    """Run the currently safe direct-barrier prefilter before residual LT.

    Direct-only analysis cannot prove a candidate has no indirect barrier
    effect, so the filter deliberately retains every eligible candidate and
    records that no rejection occurred.  The returned trace must equal LT.
    """

    validate_complex_chain(dag)
    model = PreeSingleModel(dag)
    state = model.initial_state()
    actions: list[Action] = []
    audits: list[str] = []
    started = perf_counter()
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        if not eligible:
            action = Action.wait()
        else:
            baseline = _baseline_choice(model, state, "longest_tail")
            retained = safe_barrier_prescreen(
                build_context(model, state, roots=eligible), eligible, baseline
            )
            if baseline not in retained or tuple(retained) != tuple(eligible):
                raise AssertionError("direct-barrier prescreen may not silently alter LT")
            audits.append(f"before={len(eligible)};after={len(retained)};rejected=0")
            action = Action.run(baseline)
        actions.append(action)
        state = model.step(state, action).after
    return _result(model, actions).with_stats(
        runtime_ms=(perf_counter() - started) * 1000,
        planner_decisions=len(audits),
        fallback_details=tuple(audits),
    )


def schedule_selective_barrier_rollout(
    dag: DAG,
    *,
    max_triggers: int = 8,
    time_limit_s: float | None = 2.0,
) -> PreemptiveScheduleResult:
    """Enhance LT only at barrier states using a one-action rollout.

    At a triggered state the planner compares the LT first action with the
    strongest barrier/unlock candidate.  Each action is followed by the same
    LT completion policy in the public simulator.  The candidate is committed
    only on strict residual-cost improvement.  This is an online, state-level
    safeguard; it does not run two complete candidate policies and select one
    after observing their final makespans.
    """

    if max_triggers < 0:
        raise ValueError("max_triggers must be non-negative")
    if time_limit_s is not None and time_limit_s < 0:
        raise ValueError("time_limit_s must be non-negative or None")
    validate_complex_chain(dag)
    model = PreeSingleModel(dag)
    state = model.initial_state()
    actions: list[Action] = []
    started = perf_counter()
    decisions = triggered = improvements = completion_calls = fallback_count = 0
    fallback_reasons: list[str] = []

    def completion_cost(after: ScheduleState) -> int:
        nonlocal completion_calls
        completion_calls += 1
        suffix = _complete_actions(model, after, "longest_tail")
        return _apply_actions(model, after, suffix).time

    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        if not eligible:
            action = Action.wait()
        else:
            decisions += 1
            baseline_id = _baseline_choice(model, state, "longest_tail")
            context = build_context(model, state, roots=eligible)
            candidate_id = min(
                eligible, key=lambda item: priority_key(context, item, "barrier_only")
            )
            has_signal = has_barrier_signal(context, candidate_id)
            budget_ok = triggered < max_triggers and (
                time_limit_s is None or perf_counter() - started < time_limit_s
            )
            selected = baseline_id
            if candidate_id != baseline_id and has_signal and budget_ok:
                triggered += 1
                baseline_after = model.step(state, Action.run(baseline_id)).after
                candidate_after = model.step(state, Action.run(candidate_id)).after
                baseline_cost = completion_cost(baseline_after)
                candidate_cost = completion_cost(candidate_after)
                if candidate_cost < baseline_cost:
                    selected = candidate_id
                    improvements += 1
            elif candidate_id != baseline_id and has_signal and not budget_ok:
                fallback_count += 1
                reason = (
                    "selective_trigger_limit"
                    if triggered >= max_triggers
                    else "selective_time_limit"
                )
                if reason not in fallback_reasons:
                    fallback_reasons.append(reason)
            action = Action.run(selected)
        actions.append(action)
        state = model.step(state, action).after
    result = _result(model, actions)
    return result.with_stats(
        runtime_ms=(perf_counter() - started) * 1000,
        evaluated_candidates=completion_calls,
        fallback_count=fallback_count,
        fallback_reasons=tuple(fallback_reasons),
        planner_decisions=decisions,
        planner_triggered=triggered,
        planner_improvements=improvements,
        completion_calls=completion_calls,
    )

__all__ = [
    "OfflineBarrierUpperBound",
    "offline_best_of_lt_and_barrier",
    "schedule_barrier_margin_tiebreak",
    "schedule_barrier_policy",
    "schedule_barrier_prescreen",
    "schedule_selective_barrier_rollout",
]
